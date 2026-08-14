"""発送用梱包資材（宅配袋・ダンボール等）の費用集計API。

資材は商品原価には計上せず販売費として扱うため、商品マスタのcost_jpyとは別に
material_costs テーブルへ記録している。ここではその月次集計を返す。
楽天・Amazonどちらの仕入からも書き込まれるので、集計は両方をまとめて行う。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.models.material_cost import MaterialCost

router = APIRouter(prefix="/material-costs", tags=["material-costs"])


@router.get("/monthly")
def monthly_summary(db: Session = Depends(get_db)):
    """月ごとの資材費合計を新しい順に返す（仕入れた月に計上する方式）。"""
    rows = (
        db.query(
            func.substr(MaterialCost.invoice_date, 1, 7).label("month"),
            func.sum(MaterialCost.total_cost_jpy).label("total_jpy"),
            func.count(MaterialCost.id).label("line_count"),
        )
        .filter(MaterialCost.invoice_date != None)  # noqa: E711
        .group_by("month")
        .order_by(func.substr(MaterialCost.invoice_date, 1, 7).desc())
        .all()
    )
    return {
        "months": [
            {
                "month": r.month,
                "total_jpy": round(r.total_jpy or 0),
                "line_count": r.line_count,
            }
            for r in rows
        ]
    }


@router.get("/")
def list_material_costs(month: str = None, db: Session = Depends(get_db)):
    """資材費の明細。month='2026-08' を指定するとその月だけ絞り込む。"""
    q = db.query(MaterialCost)
    if month:
        q = q.filter(MaterialCost.invoice_date.like(f"{month}%"))
    rows = q.order_by(MaterialCost.invoice_date.desc(), MaterialCost.id.desc()).all()
    return {
        "items": [
            {
                "id": r.id,
                "invoice_no": r.invoice_no,
                "invoice_date": r.invoice_date,
                "source": r.source,
                "sku": r.sku,
                "name": r.name,
                "qty": r.qty,
                "unit_price_cny": r.unit_price_cny,
                "total_price_cny": r.total_price_cny,
                "freight_alloc_cny": r.freight_alloc_cny,
                "tax_alloc_jpy": r.tax_alloc_jpy,
                "total_cost_jpy": r.total_cost_jpy,
                "exchange_rate": r.exchange_rate,
            }
            for r in rows
        ]
    }
