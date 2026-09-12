"""発注ロジック（日別実績版）の窓口。

日別の取り込み、セール期間の管理、鮮度の確認、試算をここでまとめる。
発注画面への差し替えは、実データが溜まって数字を見比べてから行う。
"""
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.daily_sales import DailySales, SaleWindow
from app.models.product import Product
from app.services import amazon_reports, daily_sales_sync, order_logic, order_plan
from app.services.order_logic import LogicSettings

router = APIRouter(prefix="/order-logic", tags=["order-logic"])


# ---------- 日別データの取り込み ----------

@router.get("/freshness")
def freshness(db: Session = Depends(get_db)):
    """どこまで取り込めているか。

    古いまま発注すると、直近日が欠品扱いになって「セールを信じすぎる」
    方向に倒れる。7日以上遅れていたら発注計算を止める。
    """
    return daily_sales_sync.freshness(db)


@router.post("/sync")
def sync(kind: str = Query("all", pattern="^(all|orders|ledger)$"),
         days: Optional[int] = None,
         db: Session = Depends(get_db)):
    """レポートから日別実績を取り込む。数分かかる。

    days を渡すとその日数ぶん遡って取り直す（初回や、抜けを埋めるとき）。
    """
    start = (date.today() - timedelta(days=days)) if days else None
    out = {}
    try:
        if kind in ("all", "orders"):
            out["orders"] = daily_sales_sync.sync_orders(db, start=start)
        if kind in ("all", "ledger"):
            out["ledger"] = daily_sales_sync.sync_ledger(db, start=start)
    except amazon_reports.ReportError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return out


@router.get("/days/{sku}")
def days(sku: str, limit: int = 90, db: Session = Depends(get_db)):
    """1商品の日別実績。数字が合わないときに中身を見るため。"""
    rows = (db.query(DailySales)
            .filter(DailySales.sku == sku)
            .order_by(DailySales.day.desc()).limit(limit).all())
    return {"sku": sku, "days": [{
        "day": str(r.day), "units": r.units, "vine": r.vine_units,
        "revenue": r.revenue, "promo": r.promo_discount,
        "in_stock": r.in_stock, "sellable_end": r.sellable_end,
    } for r in rows]}


# ---------- セール期間 ----------

class SaleIn(BaseModel):
    name: str = ""
    start_date: date
    end_date: date
    planned_target: float = 2.5
    planned_other: float = 1.2
    manual_target: Optional[float] = None
    manual_other: Optional[float] = None


def _sale_out(w: SaleWindow) -> dict:
    return {
        "id": w.id, "name": w.name,
        "start_date": str(w.start_date), "end_date": str(w.end_date),
        "planned_target": w.planned_target, "planned_other": w.planned_other,
        "actual_target": w.actual_target, "actual_other": w.actual_other,
        "manual_target": w.manual_target, "manual_other": w.manual_other,
    }


@router.get("/sales")
def list_sales(db: Session = Depends(get_db)):
    rows = db.query(SaleWindow).order_by(SaleWindow.start_date.desc()).all()
    return {"items": [_sale_out(w) for w in rows]}


@router.post("/sales")
def create_sale(data: SaleIn, db: Session = Depends(get_db)):
    if data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="終了日が開始日より前です")
    w = SaleWindow(**data.model_dump())
    db.add(w)
    db.commit()
    return _sale_out(w)


@router.put("/sales/{sid:int}")
def update_sale(sid: int, data: SaleIn, db: Session = Depends(get_db)):
    w = db.query(SaleWindow).filter(SaleWindow.id == sid).first()
    if not w:
        raise HTTPException(status_code=404, detail="そのセールがありません")
    for k, v in data.model_dump().items():
        setattr(w, k, v)
    db.commit()
    return _sale_out(w)


@router.delete("/sales/{sid:int}")
def delete_sale(sid: int, db: Session = Depends(get_db)):
    w = db.query(SaleWindow).filter(SaleWindow.id == sid).first()
    if not w:
        raise HTTPException(status_code=404, detail="そのセールがありません")
    db.delete(w)
    db.commit()
    return {"deleted": sid}


@router.post("/sales/{sid:int}/measure")
def measure_sale(sid: int, db: Session = Depends(get_db)):
    """実測倍率を出して保存する。セール3日目から効く。"""
    w = db.query(SaleWindow).filter(SaleWindow.id == sid).first()
    if not w:
        raise HTTPException(status_code=404, detail="そのセールがありません")
    return order_plan.recompute_sale_mult(db, w)


# ---------- 試算 ----------

class PreviewIn(BaseModel):
    """設定を変えて試せるようにする。既定は order_logic の値。"""
    window_days: Optional[int] = None
    trend_min: Optional[float] = None
    trend_max: Optional[float] = None
    sale_cap_mult: Optional[float] = None
    sale_ramp_days: Optional[int] = None
    base_target_days: Optional[int] = None
    trigger_slack: Optional[int] = None
    min_order_qty: Optional[int] = None
    sale_rescale: Optional[bool] = None
    skus: Optional[List[str]] = None


def _settings(p: PreviewIn) -> LogicSettings:
    s = LogicSettings()
    for k, v in p.model_dump(exclude={"skus"}).items():
        if v is not None:
            setattr(s, k, v)
    return s


@router.post("/preview")
def preview(p: PreviewIn, db: Session = Depends(get_db)):
    """新方式で発注数を試算する。まだ発注はしない。

    在庫はAmazonのAPIから取る。取れなければ0として出す
    （数字が出ないより、在庫0の前提だと分かる形で出したほうがよい）。
    """
    s = _settings(p)
    fresh = daily_sales_sync.freshness(db)

    q = db.query(Product).filter(Product.is_active == True)
    if p.skus:
        q = q.filter(Product.sku.in_(p.skus))
    products = q.all()

    stocks = {}
    try:
        from app.services.amazon_api import fetch_inventory
        inv = fetch_inventory()
        for sku, v in (inv or {}).items():
            stocks[sku] = (v.get("available", 0) + v.get("inbound", 0)
                           + v.get("processing", 0))
    except Exception:
        pass

    out = []
    for prod in products:
        stock = stocks.get(prod.sku, 0) + (prod.extra_stock or 0)
        r = order_plan.plan_for(db, prod, stock, s)
        b = r.breakdown
        out.append({
            "sku": prod.sku, "name": prod.name,
            "daily": r.daily, "trend": r.trend,
            "target_days": r.target_days, "stock": r.stock,
            "days_left": r.days_left, "need": r.need,
            "qty": r.qty, "qty_pieces": r.qty_pieces,
            "ordered": r.ordered, "hold_reason": r.hold_reason,
            "breakdown": None if not b else {
                "plain_daily": b.plain_daily, "plain_days": b.plain_days,
                "counted_days": b.counted_days, "skipped_oos": b.skipped_oos,
                "vine_removed": b.vine_removed, "spike_capped": b.spike_capped,
                "sale_days": b.sale_days, "sale_capped": b.sale_capped,
                "confidence": round(b.confidence, 3), "notes": b.notes,
            },
        })
    out.sort(key=lambda x: (not x["ordered"], -x["qty_pieces"]))
    return {
        "fresh": fresh,
        "count": len(out),
        "ordered_count": len([x for x in out if x["ordered"]]),
        "items": out,
    }


@router.post("/compare")
def compare(p: PreviewIn, db: Session = Depends(get_db)):
    """新方式と今の方式を並べる。

    式を変えたら、変わった行を1行ずつ説明できるか確かめてから入れる。
    そのための画面。
    """
    from app.services import calc as old_calc
    from app.models.settings import OrderSettings

    s = _settings(p)
    new = {x["sku"]: x for x in preview(p, db)["items"]}

    row = db.query(OrderSettings).first()
    old_s = old_calc.CalcSettings()
    if row:
        for k in ("lead_days", "min_order_qty"):
            v = getattr(row, k, None)
            if v is not None:
                setattr(old_s, k, v)

    try:
        from app.services.amazon_api import fetch_all_sales, fetch_inventory
        inv = fetch_inventory() or {}
        asins = [x.asin for x in db.query(Product)
                 .filter(Product.is_active == True).all() if x.asin]
        s7, s15, s30, s60, s90 = fetch_all_sales(asins)
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"今の方式の数字が取れませんでした: {e}")

    out = []
    for prod in db.query(Product).filter(Product.is_active == True).all():
        n = new.get(prod.sku)
        if not n:
            continue
        iv = inv.get(prod.sku, {})
        old = old_calc.calc_order_qty(
            available=iv.get("available", 0), inbound=iv.get("inbound", 0),
            processing=iv.get("processing", 0),
            extra_stock=prod.extra_stock or 0,
            sales_7=(s7.get(prod.asin) or 0) / 7,
            sales_15=(s15.get(prod.asin) or 0) / 15,
            sales_30=(s30.get(prod.asin) or 0) / 30,
            sales_60=(s60.get(prod.asin) or 0) / 60,
            sales_90=(s90.get(prod.asin) or 0) / 90,
            set_size=prod.set_size or 1, s=old_s,
        )
        out.append({
            "sku": prod.sku, "name": prod.name,
            "old": {"daily": old.daily, "qty_pieces": old.qty_pieces,
                    "days_left": old.days_left, "target": old.target},
            "new": {"daily": n["daily"], "qty_pieces": n["qty_pieces"],
                    "days_left": n["days_left"],
                    "target_days": n["target_days"],
                    "hold_reason": n["hold_reason"]},
            "diff_qty": n["qty_pieces"] - old.qty_pieces,
        })
    out.sort(key=lambda x: -abs(x["diff_qty"]))
    return {
        "count": len(out),
        "changed": len([x for x in out if x["diff_qty"] != 0]),
        "old_total": sum(x["old"]["qty_pieces"] for x in out),
        "new_total": sum(x["new"]["qty_pieces"] for x in out),
        "items": out,
    }
