"""商品ごと・便ごとの原価実績を返すAPI。

商品マスタの cost_jpy は「最後に保存した便の原価」で上書きされるため、
同じ商品でも便によって送料が変わる（箱の詰め方しだい）ことが見えない。
ここでは便ごとの実績を並べ、後から加重平均へ切り替えられるようにしている。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.models.cost_history import CostHistory

router = APIRouter(prefix="/cost-histories", tags=["cost-histories"])


@router.get("/")
def list_histories(
    sku: str | None = Query(None, description="SKUで絞り込む"),
    source: str | None = Query(None, description="rakuten / amazon"),
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
):
    """原価履歴を新しい順に返す。"""
    q = db.query(CostHistory)
    if sku:
        q = q.filter(CostHistory.sku == sku)
    if source:
        q = q.filter(CostHistory.source == source)
    rows = (
        q.order_by(CostHistory.invoice_date.desc(), CostHistory.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "source": r.source,
            "sku": r.sku,
            "invoice_no": r.invoice_no,
            "invoice_date": r.invoice_date,
            "qty": r.qty,
            "set_size": r.set_size,
            "sell_units": r.sell_units,
            "cost_jpy": r.cost_jpy,
            "total_price_cny": r.total_price_cny,
            "freight_alloc_cny": r.freight_alloc_cny,
            "tax_alloc_jpy": r.tax_alloc_jpy,
            "customs_fee_alloc_jpy": r.customs_fee_alloc_jpy,
            "exchange_rate": r.exchange_rate,
            "coverage_rate": r.coverage_rate,
            "freight_method": r.freight_method,
        }
        for r in rows
    ]


@router.get("/by-sku")
def summary_by_sku(
    source: str | None = Query(None, description="rakuten / amazon"),
    db: Session = Depends(get_db),
):
    """SKUごとに、何便ぶんの実績があるか・原価が便ごとにどれだけ振れているかを返す。

    便が2件以上あるSKUは、最小と最大の開きを見れば
    「1回だけの値で値付けするのが危ういか」が判断できる。
    """
    q = db.query(
        CostHistory.source,
        CostHistory.sku,
        func.count(CostHistory.id).label("shipments"),
        func.min(CostHistory.cost_jpy).label("min_cost"),
        func.max(CostHistory.cost_jpy).label("max_cost"),
        func.max(CostHistory.invoice_date).label("latest_date"),
    )
    if source:
        q = q.filter(CostHistory.source == source)
    rows = q.group_by(CostHistory.source, CostHistory.sku).all()

    out = []
    for r in rows:
        lo, hi = r.min_cost or 0, r.max_cost or 0
        out.append({
            "source": r.source,
            "sku": r.sku,
            "shipments": r.shipments,
            "min_cost_jpy": round(lo, 1),
            "max_cost_jpy": round(hi, 1),
            # 便ごとの振れ幅。大きいほど1回の値で値付けするのが危ない
            "spread_ratio": round(hi / lo, 2) if lo > 0 else None,
            "latest_date": r.latest_date,
        })
    out.sort(key=lambda x: (-(x["spread_ratio"] or 0), x["sku"]))
    return out
