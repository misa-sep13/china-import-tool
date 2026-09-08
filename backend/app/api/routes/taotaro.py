"""タオタロウAPIの窓口。

トークンは発注権限そのものなので、ブラウザには渡さずここで持つ。
画面はこのサーバー経由で呼ぶ（仕様書もサーバー間通信を前提としている）。

支払い（/send-orders/pay）は用意していない。取り消せないため、
仕様書の推奨どおり「検知と金額の取得」までをツールで行い、
実際の支払いは管理画面で目視確認のうえ実行する。
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services import taotaro

router = APIRouter(prefix="/taotaro", tags=["taotaro"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except taotaro.TaotaroError as e:
        # 認証や権限の問題はそのまま画面に出したいので、文言を保つ
        raise HTTPException(status_code=502, detail=e.message)


@router.get("/ping")
def ping():
    """繋がるかどうかの確認。設定直後の切り分け用。"""
    if not taotaro.is_configured():
        return {"ok": False, "detail": "トークンが未設定です（TAOTARO_API_TOKEN）"}
    return _call(taotaro.ping)


@router.get("/send-orders")
def list_send_orders(
    page: int = 1,
    limit: int = Query(20, ge=1, le=100),
    state: Optional[int] = None,
    keyword: str = "",
):
    """配送依頼の一覧。state=7 がお支払い待ち。"""
    return _call(taotaro.list_send_orders, page=page, limit=limit,
                 state=state, keyword=keyword)


@router.get("/send-orders/{sid:int}")
def get_send_order(sid: int):
    """配送依頼の詳細。費用の内訳と同梱注文の明細。"""
    return _call(taotaro.get_send_order, sid)


@router.get("/awaiting-payment")
def awaiting_payment():
    """お支払い待ちの配送依頼。支払い忘れによる出荷遅延を防ぐため。"""
    d = _call(taotaro.list_send_orders, page=1, limit=100, state=7)
    items = d.get("items") or []
    return {
        "count": len(items),
        "total_cny": round(sum((x.get("total_send_fee") or 0) for x in items), 2),
        "items": items,
    }
