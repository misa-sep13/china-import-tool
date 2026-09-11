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
    # 画面に出すのは訳（読みやすい）。ただし訳語は商品マスタの書き方と
    # 揃わないことが多いので、照合には原文も使う。両方持たせておく
    names = d.get("props_list_trans") or d.get("props_list") or {}
    raw_names = d.get("props_list") or {}
    imgs = d.get("props_img") or {}
    for s in d.get("skus") or []:
        # properties は "0:0;1:1" の形。props_list を引くと日本語になる
        keys = [k for k in str(s.get("properties") or "").split(";") if k]
        parts = [str(names.get(k) or k) for k in keys]
        raw_parts = [str(raw_names.get(k) or k) for k in keys]
        # 属性ごとの画像。色の属性にだけ付いていることが多いので、
        # 見つかった最初のものを使う。無ければ商品の1枚目で代える
        img = ""
        for k in keys:
            if imgs.get(k):
                img = imgs[k]
                break
        if not img:
            pics = d.get("item_pics") or []
            img = pics[0] if pics else ""
        # 「//img.alicdn.com/...」の形で返ることがある。そのままでは
        # 画面から読めないので、httpsを補う
        img = str(img or "").strip()
        if img.startswith("//"):
            img = "https:" + img
        # 画面に出すのは中国語の原文。タオタロウのExcel取込画面が
        # 「颜色：灰色；规格：30*30cm-拷边加厚；」と中国語で出るので、
        # 同じ書き方にしておかないと同じものかどうか見比べられない。
        # 原文が無い商品だけ訳で代える
        # 区切りもタオタロウの取込画面に合わせる（全角のコロンと semicolon）
        raw_label = "；".join([x.replace(":", "：") for x in raw_parts if x])
        if raw_label:
            raw_label += "；"
        skus.append({
            "sku_id": str(s.get("sku_id") or ""),
            "label": raw_label or " / ".join(parts),
            # 訳。原文だけでは分からないときの手がかりに残す
            "label_ja": " / ".join(parts),
            # 照合用の原文
            "label_raw": " / ".join(raw_parts),
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


# 日本語の漢字と簡体字で同じ色を指すもの。仕入先は簡体字、こちらの
# 商品マスタは日本語で書かれていることがあり、そのままでは一致しない
# 訳が「ブルー」、商品マスタが「藍色」のように、同じ色でも書き方が違う。
# よく使う色だけ、漢字の色名へ寄せてから比べる
_COLOR_SAME = {
    "ブルー": "蓝", "ネイビー": "藏青", "ダークブルー": "深蓝",
    "ホワイト": "白", "ブラック": "黑", "レッド": "红", "ピンク": "粉",
    "グリーン": "绿", "ダークグリーン": "深绿", "イエロー": "黄",
    "オレンジ": "橙", "パープル": "紫", "グレー": "灰", "ブラウン": "棕",
    "ベージュ": "米", "ゴールド": "金", "シルバー": "银", "カーキ": "卡其",
    "クリア": "透明", "ローズレッド": "玫红", "アイボリー": "象牙",
    "肌の色": "肤", "肌色": "肤",
}

# 数量の単位。訳が「12カプセル」、商品マスタが「12粒」のように
# 同じものを別の言葉で書いている。数字だけ残るよう単位を落とす
_UNIT_WORDS = [
    "カプセル", "錠剤", "錠", "個入り", "個", "粒", "枚", "セット", "組",
    "pcs", "pc", "set",
]

_HAN_SAME = {
    "藍": "蓝", "灰": "灰", "緑": "绿", "紅": "红", "黒": "黑", "白": "白",
    "銀": "银", "褐": "褐", "紫": "紫", "橙": "橙", "黄": "黄", "粉": "粉",
    "図": "图", "無": "无", "號": "号", "号": "号", "碼": "码", "码": "码",
    "標": "标", "準": "准", "軍": "军", "楓": "枫", "櫻": "樱", "藍色": "蓝色",
}


def _norm(s: str) -> str:
    """照合用に、記号と空白を落として比べやすくする。

    仕入先は簡体字、商品マスタは日本語で書かれていることがあるので、
    よく出る漢字だけ簡体字へ寄せてから比べる。
    """
    import re
    t = str(s or "")
    # 長い名前から先に置き換える。「ダークブルー」が「ブルー」で
    # 先に潰れないようにするため
    for a in sorted(_COLOR_SAME, key=len, reverse=True):
        t = t.replace(a, _COLOR_SAME[a])
    for a, b in _HAN_SAME.items():
        t = t.replace(a, b)
    return re.sub(r"[\s　・/／,、。.\-_（）()【】\[\]]", "", t).lower()


def _parts(s: str) -> list:
    """仕様の文字列を、属性ごとの断片に割る。

    商品マスタの仕様は「藍色12粒、HS-88」のように複数の属性が
    1つの文字列にまとまっている。仕入先のラベルは属性ごとに
    分かれているので、こちらも割ってから突き合わせる。
    """
    import re
    out = []
    # 【】は「白色【2粒】」のように属性の切れ目として使われるので、
    # 記号として落とさず、ここで区切りとして扱う
    for x in re.split(r"[、,/／|｜\s　【】\[\]（）()]+", str(s or "")):
        x = _norm(x)
        if x:
            out.append(x)
    return out


def _label_parts(label: str) -> list:
    """仕入先のラベル「カラー：赤 / サイズ：M」を、値だけの断片にする。

    属性名（カラー・颜色分类など）は商品マスタに入っていないので落とす。
    """
    out = []
    for seg in str(label or "").split("/"):
        seg = seg.strip()
        if not seg:
            continue
        # 「颜色分类：蓝色」→「蓝色」。区切りが無ければそのまま
        for sep in ("：", ":"):
            if sep in seg:
                seg = seg.split(sep, 1)[1]
                break
        seg = _norm(seg)
        if seg:
            out.append(seg)
    return out


def _drop_units(s: str) -> str:
    """数量の単位と、色名の「色」を落とす。

    「蓝色12粒」と「蓝12カプセル」のように、同じものでも単位の訳語が
    違ったり、色名に「色」が付いたり付かなかったりする。
    数と色の字だけ残せば、同じものは同じ形になる。
    """
    t = str(s or "")
    for w in sorted(_UNIT_WORDS, key=len, reverse=True):
        t = t.replace(w, "")
    return t.replace("色", "")


def _fits(want: str, parts: list) -> bool:
    """欲しい断片が、ラベルのどれかに当てはまるか。

    表記のゆれ（「白色2粒」と「白色 2粒装」など）で完全一致しないため、
    どちらかがもう一方を含んでいれば同じとみなす。
    単位の言い換え（粒／カプセル）も揃えてから比べる。
    """
    if any(want == p or want in p or p in want for p in parts):
        return True
    w = _drop_units(want)
    if not w:
        return False
    return any(w == _drop_units(p) for p in parts)


def match_sku(skus: list, color: str, size: str, spec: str = "") -> dict:
    """色・サイズから、どのSKUかを当てる。

    当たらなければ None を返す。**推測で近いものを返さない**。
    間違った色を発注するくらいなら、画面で選んでもらったほうがよい。

    商品マスタの書き方が仕入先と揃っていないので、
      1. 属性ごとに割って、全部そろうものを探す
      2. それで決まらなければ、いちばん特徴の出る先頭（たいてい色）だけで探す
    の順に絞る。どちらも1つに決まらなければ諦める。
    """
    want = []
    for x in (color, size, spec):
        want.extend(_parts(x))
    if not want or not skus:
        return None

    # 訳と原文の両方を候補にする。どちらかで当たればよい
    labels = []
    for s in skus:
        parts = _label_parts(s.get("label")) + _label_parts(s.get("label_raw"))
        if parts:
            labels.append((s, parts))
    if not labels:
        return None

    # 完全一致を先に見る。部分一致だけで絞ると、「蓝色」を探したときに
    # 「深蓝色（ダークブルー）」まで拾ってしまい、決まらなくなる
    def exact(w, parts):
        return any(w == p for p in parts)

    for test in (exact, _fits):
        # 1. 指定された属性がすべて当てはまるもの
        hit = [s for s, parts in labels if all(test(w, parts) for w in want)]
        if len(hit) == 1:
            return hit[0]

        # 2. 先頭の断片（色であることが多い）だけで絞る。
        #    「藍色12粒、HS-88」の HS-88 が仕入先のラベルに無い、という形で
        #    落ちることが多いため
        hit = [s for s, parts in labels if test(want[0], parts)]
        if len(hit) == 1:
            return hit[0]

    return None


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


# ---------- 残高・入出金・請求書 ----------


def balance() -> dict:
    """残高。発注の前に足りているか見るためのもの。"""
    d = _request("/api/v1/account/balance")
    return {
        "money": d.get("money"),
        "currency": d.get("currency") or "CNY",
        "updated_at": _ts(d.get("updated_at")),
    }


# 取引種別のうち、仕入原価として按分に回すもの。
# 「商品購入」は注文ごと、配送費は便ごとに出るので、集計の単位が違う
def _txn(x: dict) -> dict:
    money = x.get("money")
    return {
        "id": x.get("id"),
        "at": _ts(x.get("add_time")),
        # debit=引落（マイナス）、credit=入金
        "kind": x.get("kind"),
        "action": x.get("action_name"),
        "money": money,
        "balance_after": x.get("account_money"),
        "exchange_rate": x.get("exchange_rate"),
        "exchange_money": x.get("exchange_money"),
        # ここが肝。明細が注文・配送依頼に1対1で紐づくので突合できる
        "oid": x.get("oid"),
        "sid": x.get("sid"),
        "sn": x.get("sn"),
        "product_total_price": x.get("product_total_price"),
        "service_charge": x.get("service_charge"),
        "remark": x.get("remark"),
    }


def transactions(page: int = 1, limit: int = 50,
                 start_time: Optional[int] = None,
                 end_time: Optional[int] = None) -> dict:
    """入出金明細。会計との突合と、便ごとの実額を取るのに使う。"""
    d = _request("/api/v1/account/transactions", {
        "page": page, "limit": limit,
        "start_time": start_time, "end_time": end_time,
    })
    return {
        "items": [_txn(x) for x in (d.get("items") or [])],
        "page": d.get("page") or page,
        "has_more_pages": bool(d.get("has_more_pages")),
    }


def transactions_for(sid: int, max_pages: int = 6) -> list:
    """ある配送依頼に紐づく明細だけを集める。

    絞り込みの条件が仕様書に無いので、新しいほうから何ページか見て
    sid が一致するものを拾う。便は新しいものを扱うことがほとんどなので、
    これで足りる（見つからなければページを増やす）。
    """
    out = []
    for page in range(1, max_pages + 1):
        d = transactions(page=page, limit=100)
        for x in d["items"]:
            if str(x.get("sid") or "") == str(sid):
                out.append(x)
        if not d["has_more_pages"]:
            break
    return out


def invoice(sid: int) -> dict:
    """請求書PDFのダウンロード先。

    URLは期限付きなので、受け取ったらすぐ落として自社側で保管する
    （仕様書にもそう書かれている）。まだ生成されていないことがあるので、
    status を見て呼び出し側で分ける。
    """
    d = _request(f"/api/v1/send-orders/{int(sid)}/invoice")
    inv = d.get("invoice") or {}
    return {
        "ready": int(inv.get("status") or 0) == 200,
        "status": inv.get("status"),
        "message": inv.get("msg") or "",
        "url": inv.get("url") or "",
        "expires_in": inv.get("exp"),
        "shipping_info": d.get("shipping_info") or [],
    }


def invoice_file(sid: int) -> tuple:
    """請求書の中身を取ってくる。(ファイル名, bytes) を返す。

    仕様書には「請求書PDF」と書かれているが、実際に落ちてくるのは
    いつも手で添付してもらっているインボイスのExcelそのもので、
    箱ごとの寸法・重量（箱规）と、箱と注文の対応（箱单）まで入っている。
    拡張子は中身を見て決める。決め打ちにすると、PDFに戻ったときに壊れる。
    """
    import urllib.request

    inv = invoice(sid)
    if not inv["ready"] or not inv["url"]:
        raise TaotaroError(inv["message"] or "請求書がまだ発行されていません")
    try:
        req = urllib.request.Request(inv["url"], headers={
            "User-Agent": "china-import-tool/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            raw = res.read()
    except Exception as e:
        raise TaotaroError(f"請求書を取得できませんでした（{type(e).__name__}）")
    if not raw:
        raise TaotaroError("請求書が空でした")
    ext = "pdf" if raw[:5] == b"%PDF-" else ("xlsx" if raw[:2] == b"PK" else "bin")
    return (f"{sid}.{ext}", raw)


def invoice_workbook(sid: int) -> bytes:
    """請求書のExcelを取ってくる。仕入管理の取り込みで使う。"""
    name, raw = invoice_file(sid)
    if not name.endswith(".xlsx"):
        raise TaotaroError(
            "この便の請求書はExcelではありませんでした。"
            "お手元のインボイスを使ってください")
    return raw
