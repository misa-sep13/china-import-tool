"""Amazonの売上管理（暫定）。

楽天には月ごとの売上管理があるが、Amazonには無かった。日ごとの実績
（daily_sales）は溜まっているので、それを月でまとめて出す。

楽天のようにCSVを取り込むのではなく、手元にある数字から組み立てる。
そのため次のものは入っていない。
  ・広告費（広告管理の画面にキャンペーン単位でしか無く、月ごとに割れない）
  ・返品・返金
画面にもその旨を出して、見た人が「全部入っている」と思わないようにする。
"""
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.daily_sales import DailySales
from app.models.product import Product

router = APIRouter(prefix="/amazon-sales", tags=["amazon-sales"])


def _period_range(period: str):
    try:
        y, m = int(period[:4]), int(period[5:7])
        start = date(y, m, 1)
    except (ValueError, IndexError):
        raise HTTPException(400, "対象月の形が違います（2026-08 の形で）")
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, nxt - timedelta(days=1)


@router.get("/months")
def months(db: Session = Depends(get_db)):
    """実績のある月。新しい順。"""
    rows = (db.query(func.to_char(DailySales.day, "YYYY-MM").label("p"))
            .distinct().all()) if db.bind.dialect.name == "postgresql" else None
    if rows is None:
        # SQLite など。日付を持ってきて手元で丸める
        days = db.query(DailySales.day).distinct().all()
        ps = sorted({d[0].strftime("%Y-%m") for d in days if d[0]}, reverse=True)
    else:
        ps = sorted({r[0] for r in rows if r[0]}, reverse=True)
    return {"months": ps}


@router.get("/summary")
def summary(period: str, db: Session = Depends(get_db)):
    """その月の売上・原価・利益を、SKUごとと合計で返す。"""
    start, end = _period_range(period)

    rows = (db.query(DailySales)
            .filter(DailySales.day >= start, DailySales.day <= end).all())
    if not rows:
        return {"period": period, "items": [], "totals": _empty_totals(),
                "note": "この月の実績がまだありません"}

    products = {p.sku: p for p in db.query(Product).all()}

    by_sku: dict = {}
    for r in rows:
        v = by_sku.setdefault(r.sku, {
            "sku": r.sku, "name": "", "units": 0, "vine_units": 0,
            "revenue": 0.0, "promo": 0.0,
        })
        v["units"] += r.units or 0
        v["vine_units"] += r.vine_units or 0
        v["revenue"] += r.revenue or 0
        v["promo"] += r.promo_discount or 0

    items = []
    for sku, v in by_sku.items():
        p = products.get(sku)
        # 原価は「売れた数 × 1個あたり原価」。Vineも仕入れているので数に入れる
        cost = (v["units"]) * float(getattr(p, "cost_jpy", 0) or 0) if p else 0
        fee_rate = float(getattr(p, "amazon_fee_rate", 0.1) or 0.1) if p else 0.1
        amazon_fee = v["revenue"] * fee_rate
        fba_fee = (v["units"] - v["vine_units"]) * float(
            getattr(p, "fba_fee", 0) or 0) if p else 0
        profit = v["revenue"] - v["promo"] - cost - amazon_fee - fba_fee
        items.append({
            **v,
            "name": (getattr(p, "name", "") or "") if p else "",
            "cost": round(cost),
            "amazon_fee": round(amazon_fee),
            "fba_fee": round(fba_fee),
            "profit": round(profit),
            "profit_rate": round(profit / v["revenue"] * 100, 1) if v["revenue"] else 0,
            "cost_rate": round(cost / v["revenue"] * 100, 1) if v["revenue"] else 0,
            "revenue": round(v["revenue"]),
            "promo": round(v["promo"]),
            "has_product": bool(p),
        })
    items.sort(key=lambda x: x["revenue"], reverse=True)

    totals = {
        "units": sum(i["units"] for i in items),
        "vine_units": sum(i["vine_units"] for i in items),
        "revenue": sum(i["revenue"] for i in items),
        "promo": sum(i["promo"] for i in items),
        "cost": sum(i["cost"] for i in items),
        "amazon_fee": sum(i["amazon_fee"] for i in items),
        "fba_fee": sum(i["fba_fee"] for i in items),
        "profit": sum(i["profit"] for i in items),
    }
    totals["profit_rate"] = (round(totals["profit"] / totals["revenue"] * 100, 1)
                             if totals["revenue"] else 0)
    totals["cost_rate"] = (round(totals["cost"] / totals["revenue"] * 100, 1)
                           if totals["revenue"] else 0)
    # 原価の入っていない商品があると、利益が多めに出る
    no_cost = [i["sku"] for i in items if i["units"] and not i["cost"]]
    return {"period": period, "items": items, "totals": totals,
            "no_cost_skus": no_cost[:20], "no_cost_count": len(no_cost)}


def _empty_totals() -> dict:
    return {"units": 0, "vine_units": 0, "revenue": 0, "promo": 0, "cost": 0,
            "amazon_fee": 0, "fba_fee": 0, "profit": 0,
            "profit_rate": 0, "cost_rate": 0}
