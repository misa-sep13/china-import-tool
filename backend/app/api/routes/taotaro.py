"""タオタロウAPIの窓口。

トークンは発注権限そのものなので、ブラウザには渡さずここで持つ。
画面はこのサーバー経由で呼ぶ（仕様書もサーバー間通信を前提としている）。

支払い（/send-orders/pay）は用意していない。取り消せないため、
仕様書の推奨どおり「検知と金額の取得」までをツールで行い、
実際の支払いは管理画面で目視確認のうえ実行する。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
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


def _to_our_names(items: list, db: Session) -> None:
    """中身の商品名を自社の日本語名に置き換える。

    原文（中国語）のままでは、どの便か見分けるのが難しい。
    荷受けの取り込みと同じ照合を使うので、同じ商品なら同じ名前になる。
    照合できなかった行は原文のまま残す（消すと中身が分からなくなる）。
    """
    from app.api.routes.welfare import _match_product, _product_indexes
    by_url_spec, unique_url, by_url_all, by_sku = _product_indexes(db)
    for x in items:
        names = []
        for line in x.pop("lines", []) or []:
            product, _ = _match_product(line, by_url_spec, unique_url, by_url_all, by_sku)
            name = (product.name if product else "") or line.get("name_cn") or ""
            name = name.strip()
            if name and name not in names:
                names.append(name[:26])
            if len(names) >= 3:
                break
        x["titles"] = names


@router.get("/send-orders")
def list_send_orders(
    page: int = 1,
    limit: int = Query(20, ge=1, le=100),
    state: Optional[int] = None,
    keyword: str = "",
    db: Session = Depends(get_db),
):
    """配送依頼の一覧。state=7 がお支払い待ち。"""
    d = _call(taotaro.list_send_orders, page=page, limit=limit,
              state=state, keyword=keyword)
    _to_our_names(d.get("items") or [], db)
    return d


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
