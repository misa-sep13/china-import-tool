"""タオタロウ（代理購入）APIの呼び出し。

配送依頼・注文・費用の内訳を取ってくる。これまで配送依頼のExcelを
解析して商品を推測していたが、APIには out_id（自社の管理番号）が
そのまま入るので、推測による取り違えが起きなくなる。

仕様上の注意点をここに集約している:
  ・成功でも失敗でも {code, message, data} の形で返る。HTTPが200でも
    code が200でなければ失敗なので、code で判定する
  ・Accept-Language: ja を付けないとエラーが中国語で返る
  ・レート制限は1分100回。残り回数がヘッダーで返る
  ・日時は秒単位のUNIXタイムスタンプ（ミリ秒ではない）
  ・支払いAPIは取り消せないため、ここでは実装しない（管理画面で行う）
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings

TIMEOUT = 30
# 残りがこれを下回ったら少し待つ。一覧を全ページ取るときに効く
RATE_LOW = 5


class TaotaroError(Exception):
    """業務エラー。message はそのまま画面に出せる日本語。"""

    def __init__(self, message: str, code: int = 0, status: int = 0):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def is_configured() -> bool:
    return bool(settings.TAOTARO_API_TOKEN)


def _request(path: str, params: Optional[dict] = None,
             body: Optional[dict] = None, method: str = "GET") -> dict:
    if not is_configured():
        raise TaotaroError("タオタロウのトークンが未設定です（TAOTARO_API_TOKEN）")

    url = settings.TAOTARO_API_BASE.rstrip("/") + path
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)

    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {settings.TAOTARO_API_TOKEN}",
        "Accept": "application/json",
        # 付けないとエラーが中国語で返る
        "Accept-Language": "ja",
        "Content-Type": "application/json",
        # 自社サービス名を入れるよう仕様書で勧められている
        "User-Agent": "china-import-tool/1.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            raw = res.read()
            remaining = res.headers.get("X-RateLimit-Remaining")
    except urllib.error.HTTPError as e:
        raw = e.read()
        remaining = e.headers.get("X-RateLimit-Remaining")
        try:
            j = json.loads(raw)
        except Exception:
            raise TaotaroError(f"タオタロウAPIがエラーを返しました（HTTP {e.code}）",
                               status=e.code)
        # 存在しないパスのときだけ code を含まない形で返ってくる
        raise TaotaroError(j.get("message") or f"HTTP {e.code}",
                           code=j.get("code") or 0, status=e.code)
    except Exception as e:
        raise TaotaroError(f"タオタロウAPIに繋がりませんでした（{type(e).__name__}）")

    try:
        j = json.loads(raw)
    except Exception:
        raise TaotaroError("タオタロウAPIの応答を読めませんでした")

    if j.get("code") != 200:
        raise TaotaroError(j.get("message") or "タオタロウAPIがエラーを返しました",
                           code=j.get("code") or 0)

    # 一覧を全ページ取るときに上限へ当たらないよう、残りが少なければ休む
    try:
        if remaining is not None and int(remaining) <= RATE_LOW:
            time.sleep(3)
    except ValueError:
        pass
    return j.get("data") or {}


def _ts(value) -> Optional[str]:
    """秒単位のタイムスタンプをISO文字列にする。0やNoneはNoneのまま。"""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return datetime.fromtimestamp(n, tz=timezone.utc).isoformat()


def ping() -> dict:
    """疎通確認。注文を1件だけ取って、繋がるかどうかを見る。"""
    data = _request("/api/v1/orders", {"page": 1, "limit": 1})
    items = data.get("items") or []
    return {
        "ok": True,
        "orders_sample": len(items),
        "has_more_pages": bool(data.get("has_more_pages")),
    }


def list_send_orders(page: int = 1, limit: int = 20, state: Optional[int] = None,
                     keyword: str = "", start_time: Optional[int] = None) -> dict:
    """配送依頼の一覧。state は「ステータス一覧」参照（7=お支払い待ち）。"""
    data = _request("/api/v1/send-orders", {
        "page": page, "limit": limit, "state": state,
        "keyword": keyword or None, "start_time": start_time,
    })
    items = data.get("items") or []
    return {
        "items": [_send_order_brief(x) for x in items],
        "page": data.get("page") or page,
        "has_more_pages": bool(data.get("has_more_pages")),
    }


def _latest_trace(x: dict) -> dict:
    """いちばん新しい追跡の1件。どの便かを見分けるのに使う。

    一覧では追跡が付かないこともあるので、無ければ None を返す。
    """
    best = None
    for a in x.get("airbills") or []:
        for t in (a.get("trace_info") or a.get("trace_info_array") or []):
            if not isinstance(t, dict):
                continue
            when = str(t.get("time") or "")
            if not best or when > str(best.get("time") or ""):
                best = t
    if not best:
        return None
    return {"time": best.get("time"), "location": best.get("location")}


def _summary(x: dict) -> dict:
    """便の中身のあらまし。番号だけではどの便か分からないので添える。

    商品名は原文（中国語）のままだと読みにくいので、呼び出し側で
    自社の商品名に置き換えられるよう、照合の材料も一緒に返す。
    """
    orders = x.get("orders") or []
    lines = []
    for o in orders:
        props = o.get("good_skus") or []
        lines.append({
            "buy_url": (o.get("goods_url") or o.get("url") or "").strip(),
            "supplier_spec": _prop(props, _COLOR_KEYS),
            "size": _prop(props, _SIZE_KEYS),
            "customer_memo": str(o.get("out_id") or "").strip(),
            "name_cn": (o.get("goods_name_trans") or o.get("goods_name") or "").strip(),
        })
    return {"order_count": len(orders), "lines": lines}


def _send_order_brief(x: dict) -> dict:
    sm = _summary(x)
    return {
        # どの便か見分けるための情報。番号と金額だけでは判断できない
        "latest_trace": _latest_trace(x),
        "tracking_url": x.get("shipping_website_url"),
        "order_count": sm["order_count"],
        "lines": sm["lines"],
        "sid": x.get("sid"),
        "sn": x.get("sn"),
        "state": x.get("state"),
        "state_label": SEND_ORDER_STATES.get(x.get("state"), ""),
        "consignee": x.get("consignee"),
        "delivery_name": x.get("delivery_name"),
        "count_weight": x.get("count_weight"),
        "total_send_fee": x.get("total_send_fee"),
        "have_invoice": x.get("have_invoice"),
        "created_at": _ts(x.get("created_at")),
        "updated_at": _ts(x.get("updated_at")),
    }


def get_send_order(sid: int) -> dict:
    """配送依頼の詳細。費用の内訳と、同梱されている注文の明細。"""
    x = _request(f"/api/v1/send-orders/{int(sid)}")
    orders = x.get("orders") or []
    return {
        "sid": x.get("sid"),
        "sn": x.get("sn"),
        "state": x.get("state"),
        "state_label": SEND_ORDER_STATES.get(x.get("state"), ""),
        "consignee": x.get("consignee"),
        "address": x.get("address"),
        "delivery_name": x.get("delivery_name"),
        "count_weight": x.get("count_weight"),
        # 費用は荷物がたどる順。単位はすべて人民元
        "send_price": x.get("send_price"),        # 中国国内運賃
        "server_fee": x.get("server_fee"),        # 代行手数料（検品オプション込み）
        "freight": x.get("freight"),              # 国際送料
        "customs_fee": x.get("customs_fee"),      # 通関手数料（関税そのものではない）
        "remote_fee": x.get("remote_fee"),        # 遠隔地配送
        "total_send_fee": x.get("total_send_fee"),
        "airbills": x.get("airbills") or [],
        "have_invoice": x.get("have_invoice"),
        "comment": x.get("comment"),
        "created_at": _ts(x.get("created_at")),
        "updated_at": _ts(x.get("updated_at")),
        "orders": [_order_brief(o) for o in orders],
    }


def _order_brief(o: dict) -> dict:
    """同梱注文の1明細。out_id が自社の管理番号（SKU）。"""
    return {
        "oid": o.get("oid"),
        "out_id": o.get("out_id"),
        "state": o.get("state"),
        "state_label": ORDER_STATES.get(o.get("state"), ""),
        "title": o.get("goods_name"),
        "title_trans": o.get("goods_name_trans"),
        "url": o.get("goods_url") or o.get("url"),
        "image": o.get("goods_img"),
        "sku_props": o.get("good_skus") or [],
        "quantity": o.get("goods_num"),
        # 値下げ交渉が成立していれば bargain_price が実際の単価
        "unit_price": o.get("bargain_price") or o.get("goods_price"),
        "list_price": o.get("goods_price"),
        "bargain_total": o.get("bargain_total"),
        "send_price": o.get("send_price"),        # この注文に按分された中国国内運賃
        "express_no": o.get("express_no"),
        "remark": o.get("goods_remark"),
        "created_at": _ts(o.get("created_at")),
        "arrived_at": _ts(o.get("arrived_at")),
    }


# 注文ステータス（仕様書「ステータス一覧」より）
ORDER_STATES = {
    1: "買付中", 2: "買付完了", 3: "ショップから出荷", 4: "入庫済み",
    7: "オプションサービス中", 5: "配送依頼提出済", 8: "航空禁輸",
    9: "不良対応中", 6: "無効オーダー・返金待ち", 10: "無効オーダー・返金済み",
    11: "無効・廃棄済み",
}

# 配送依頼ステータス。7=お支払い待ちを監視すると出荷遅延を防げる
SEND_ORDER_STATES = {
    1: "配送依頼提出済", 6: "審査待ち", 5: "梱包作業中", 7: "お支払い待ち",
    8: "出荷待ち", 2: "出荷済み", 3: "受け取り済み", 4: "無効な配送依頼",
}


# ---------- 取り込み用（配送依頼Excelの代わり） ----------
#
# 配送依頼のExcelを解析して商品を推測していたが、色とサイズの取り違えや
# URLの空白で紐づかない事故が続いた。APIなら
#   ・out_id に自社の管理番号が入る（推測が要らない）
#   ・sid で便が一意に決まる（二重取り込みの判定が確実）
#   ・入庫日・注文ごとの中国国内送料まで取れる（Excelには無い）
# ため、同じ形に整えて既存の取り込み処理へそのまま渡せるようにする。

_COLOR_KEYS = ("颜色", "颜色分类", "颜色名称", "主色")
_SIZE_KEYS = ("规格", "规格型号", "尺码", "尺寸", "型号")


def _prop(props: list, keys: tuple) -> str:
    for p in props or []:
        if str(p.get("name") or "").strip() in keys:
            return str(p.get("value") or "").strip()
    return ""


def send_order_rows(sid: int) -> dict:
    """配送依頼1件を、Excel取り込みと同じ形の行にして返す。

    既存の _import_rows / 配送依頼の照合がそのまま使える形に揃える。
    """
    d = get_send_order(sid)
    rows = []
    for o in d.get("orders") or []:
        props = o.get("sku_props") or []
        color = _prop(props, _COLOR_KEYS)
        size = _prop(props, _SIZE_KEYS)
        # 色欄が空でサイズ欄に色まで入っている商品がある（Excelでも同じ）。
        # 照合側が両方を見るので、取れたものをそのまま渡す
        rows.append({
            "sheet": d.get("sn") or f"taotaro:{sid}",
            "shipment_no": str(d.get("sid") or ""),
            "order_date": (o.get("created_at") or "")[:10],
            "order_no": str(o.get("oid") or ""),
            "name_cn": o.get("title") or "",
            "supplier_spec": color,
            "size": size,
            "buy_url": (o.get("url") or "").strip(),
            "image_data_url": "",          # 画像はURLで来るので取り込み時は持たない
            "unit_price": str(o.get("unit_price") or ""),
            "units": int(o.get("quantity") or 0),
            "instruction": "",
            "note": "",
            "remaining_units": None,
            # ここが肝。発注時に自社SKUを入れておけば照合が要らなくなる
            "customer_memo": str(o.get("out_id") or "").strip(),
            # Excelには無い情報。原価計算や進捗表示に使える
            "arrived_at": o.get("arrived_at"),
            "state": o.get("state"),
            "state_label": o.get("state_label"),
            "domestic_freight_cny": o.get("send_price"),
            "image_url": o.get("image"),
        })
    return {
        "sid": d.get("sid"),
        "sn": d.get("sn"),
        "state": d.get("state"),
        "state_label": d.get("state_label"),
        "count_weight": d.get("count_weight"),
        "fees": {
            "send_price": d.get("send_price"),
            "server_fee": d.get("server_fee"),
            "freight": d.get("freight"),
            "customs_fee": d.get("customs_fee"),
            "remote_fee": d.get("remote_fee"),
            "total_send_fee": d.get("total_send_fee"),
        },
        "rows": rows,
    }


def _shipped_date(d: dict) -> str:
    """出荷日。APIに専用の項目が無いので、いちばん古い追跡（中国側の集荷）を使う。

    Excelの「出荷日」に当たるものが仕様書に無い。追跡の最初の記録が
    実際に荷物が動き出した日なので、これがいちばん近い。
    追跡がまだ付いていない便（出荷待ちなど）は更新日で代える。
    """
    times = []
    for a in d.get("airbills") or []:
        for t in (a.get("trace_info") or a.get("trace_info_array") or []):
            if isinstance(t, dict) and t.get("time"):
                times.append(str(t["time"]))
    if times:
        return min(times)[:10].replace("/", "-")
    return str(d.get("updated_at") or d.get("created_at") or "")[:10]


def _tracking_no(d: dict) -> str:
    """追跡番号。分割発送だと複数あるので、まとめて1つの文字列にする。"""
    nos = [str(a.get("express_no") or "").strip()
           for a in d.get("airbills") or []]
    return ",".join([n for n in nos if n])


def send_order_shipment(sid: int) -> dict:
    """配送依頼1件を、楽天発注管理の配送依頼Excelと同じ形にして返す。

    parse-excel の戻り値に合わせてあるので、そのあとの照合・保存・
    入荷反映は今までどおり動く。Excelと違うのは:
      ・お客様管理番号（out_id）が必ず入る。色とサイズの取り違えが起きない
      ・URLに余計な空白や改行が入らない
      ・箱数はAPIに無いので0。必要なら画面で入れてもらう
    """
    d = get_send_order(sid)
    items = []
    for o in d.get("orders") or []:
        props = o.get("sku_props") or []
        items.append({
            # 中国語の原文より訳のほうが画面で分かりやすい。照合には使わない
            "name_cn": (o.get("title_trans") or o.get("title") or "").strip(),
            "color": _prop(props, _COLOR_KEYS),
            "size": _prop(props, _SIZE_KEYS),
            "buy_url": (o.get("url") or "").strip(),
            "unit_price_cny": float(o.get("unit_price") or 0),
            "qty": int(o.get("quantity") or 0),
            "customer_memo": str(o.get("out_id") or "").strip(),
        })
    return {
        "shipped_date": _shipped_date(d),
        "tracking_no": _tracking_no(d),
        "order_no": str(d.get("sn") or d.get("sid") or ""),
        "box_count": 0,          # 仕様書に箱数が無い
        "total_weight_kg": float(d.get("count_weight") or 0),
        "sid": d.get("sid"),
        "state_label": d.get("state_label"),
        "items": items,
    }


# ---------- 発注（注文の作成） ----------
#
# これまではExcelを作って管理画面へ手で上げていた。APIで直接作れば
# 転記が消えるが、代わりに「どのSKU（色・サイズ）を買うか」を機械が
# 決めることになる。ここを間違えると違う色が届くので、
#   ・一度人が確認した組み合わせは商品マスタに覚える
#   ・自動で決められなかったものは発注せず、画面で選んでもらう
# という形にしてある。黙って推測で発注はしない。

# 検品オプション。var8/var9/var11/var12 は仕様書上「使用しない」
INSPECT_FLAGS = {
    "var1": "オプション検品・アパレル検品",
    "var10": "全量開封検品",
    "var2": "OPP袋交換",
    "var3": "織ネーム取り外し",
    "var4": "織ネーム縫い付け",
    "var5": "下げ札取り付け",
    "var6": "下げ札取り外し",
}
INSPECT_TEXT = {"var7": "その他のご要望"}


def _platform_of(url: str) -> str:
    """URLから仕入元を見分ける。仕様書の platform に渡す値。"""
    u = (url or "").lower()
    if "1688.com" in u:
        return "1688"
    if "taobao.com" in u or "tmall.com" in u:
        return "taobao"
    return ""


def goods_detail(url: str) -> dict:
    """商品詳細。product_id と sku_id はここからしか取れない。

    仕様書の注意:
      ・淘宝で商品が無いと 400。1688で無い場合はサーバーエラーになることが
        あるため、リトライせずスキップする実装が推奨されている
      ・価格と在庫はキャッシュされるので、発注の直前に取り直す
    """
    d = _request("/api/v1/goods/detail", {"url": (url or "").strip()})
    skus = []
    names = d.get("props_list_trans") or d.get("props_list") or {}
    imgs = d.get("props_img") or {}
    for s in d.get("skus") or []:
        # properties は "0:0;1:1" の形。props_list を引くと日本語になる
        keys = [k for k in str(s.get("properties") or "").split(";") if k]
        parts = [str(names.get(k) or k) for k in keys]
        img = ""
        for k in keys:
            if imgs.get(k):
                img = imgs[k]
                break
        skus.append({
            "sku_id": str(s.get("sku_id") or ""),
            "label": " / ".join(parts),
            "properties": s.get("properties"),
            # offer_price（仕入価格）が本来の発注単価。無ければ price
            "price": s.get("offer_price") if s.get("offer_price") is not None
                     else s.get("price"),
            "list_price": s.get("price"),
            "stock": s.get("quantity"),
            "image": img,
        })
    return {
        "product_id": d.get("product_id"),
        "platform": d.get("platform") or _platform_of(url),
        "title": d.get("title"),
        "title_trans": d.get("title_trans") or d.get("title"),
        "status": d.get("status"),
        "min_order_quantity": d.get("min_order_quantity") or 1,
        "price_range": d.get("price_range") or [],
        "location": d.get("location"),
        "images": d.get("item_pics") or [],
        "skus": skus,
    }


def _norm(s: str) -> str:
    """照合用に、記号と空白を落として比べやすくする。"""
    import re
    return re.sub(r"[\s　・/／,、。.\-_（）()【】\[\]]", "", str(s or "")).lower()


def match_sku(skus: list, color: str, size: str, spec: str = "") -> dict:
    """色・サイズから、どのSKUかを当てる。

    当たらなければ None を返す。**推測で近いものを返さない**。
    間違った色を発注するくらいなら、画面で選んでもらったほうがよい。
    """
    want = [_norm(x) for x in (color, size, spec) if str(x or "").strip()]
    if not want or not skus:
        return None

    exact = []
    for s in skus:
        lab = _norm(s.get("label"))
        if not lab:
            continue
        # 指定された語がすべてラベルに含まれていれば候補
        if all(w in lab for w in want):
            exact.append(s)
    # 候補が1つに絞れたときだけ採用する。複数なら人が選ぶ
    return exact[0] if len(exact) == 1 else None


def inspect_options(raw) -> dict:
    """商品マスタに覚えた検品オプションを、リクエストに載せる形にする。"""
    import json as _json
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw or "{}")
        except Exception:
            return {}
    out = {}
    for k in INSPECT_FLAGS:
        if raw and raw.get(k):
            out[k] = 1
    for k in INSPECT_TEXT:
        v = str((raw or {}).get(k) or "").strip()
        if v:
            out[k] = v
    return out


def create_orders(goods_list: list) -> dict:
    """注文を作成する。goods_list は1件以上。

    仕様書に data の中身の記載が無いため、返ってきた形から注文IDを
    拾えるだけ拾う。拾えなくても「作成された」ことは code=200 で分かるので、
    IDが取れない場合は out_id で照会し直せるようにしている。
    """
    if not goods_list:
        raise TaotaroError("発注する商品がありません")
    data = _request("/api/v1/orders", body={"goods_list": goods_list},
                    method="POST")
    return {"oids": _pick_oids(data), "raw": data}


def _pick_oids(data) -> list:
    """応答から注文IDらしきものを集める。形が違っても落ちないようにする。"""
    out = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("oid", "order_id", "id") and isinstance(v, (int, str)):
                    s = str(v).strip()
                    if s and s not in out:
                        out.append(s)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(data)
    return out


def find_orders_by_out_id(out_id: str, limit: int = 20) -> list:
    """自社の管理番号で注文を探す。作成直後の確認に使う。"""
    d = _request("/api/v1/orders", {"page": 1, "limit": limit,
                                    "out_id": (out_id or "").strip()})
    return [_order_brief(o) for o in (d.get("items") or [])]


def cancel_orders(order_ids: list) -> list:
    """買付開始前の注文を取り消す。実際に消えたIDが返る。

    渡した数より少ないことがある（買付が始まっていた分）ので、
    呼び出し側で件数を突き合わせること。
    """
    ids = ",".join([str(x).strip() for x in order_ids if str(x).strip()])
    if not ids:
        raise TaotaroError("取り消す注文がありません")
    d = _request("/api/v1/orders/cancel", body={"order_ids": ids}, method="POST")
    return [str(x) for x in (d.get("order_ids") or [])]
