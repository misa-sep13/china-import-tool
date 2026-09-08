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


def _send_order_brief(x: dict) -> dict:
    return {
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
