from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from datetime import date, datetime
from pydantic import BaseModel
from app.core.database import get_db
from app.models.rakuten_product import RakutenProduct
from app.models.rakuten_order import RakutenOrderHistory
from app.models.rakuten_settings import RakutenSettings
from app.services.rakuten_calc import calc_rakuten_order, RakutenCalcSettings

router = APIRouter(prefix="/rakuten", tags=["rakuten"])


# ============================================================
# Settings
# ============================================================

class RakutenSettingsSchema(BaseModel):
    lead_days:         int   = 20
    target_days:       int   = 30
    safety_stock_rate: float = 0.15
    threshold_days:    int   = 30
    super_sale_enabled: bool = False
    super_sale_mode:   str   = 'A'
    super_sale_start:  Optional[date] = None
    super_sale_end:    Optional[date] = None

    class Config:
        from_attributes = True

def _get_or_create_settings(db: Session) -> RakutenSettings:
    row = db.query(RakutenSettings).first()
    if not row:
        row = RakutenSettings()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row

@router.get("/settings", response_model=RakutenSettingsSchema)
def get_settings(db: Session = Depends(get_db)):
    return _get_or_create_settings(db)

@router.put("/settings", response_model=RakutenSettingsSchema)
def update_settings(data: RakutenSettingsSchema, db: Session = Depends(get_db)):
    row = _get_or_create_settings(db)
    for k, v in data.model_dump().items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


# ============================================================
# Products (商品マスタ)
# ============================================================

class RakutenProductIn(BaseModel):
    sku:             str
    name:            Optional[str] = None
    jan_code:        Optional[str] = None
    buy_url:         Optional[str] = None
    price:           Optional[float] = None
    set_size:        int = 1
    stock:           int = 0
    inbound:         int = 0
    sales_30_recent: int = 0
    sales_30_prev:   int = 0
    memo:            Optional[str] = None
    is_active:       bool = True

class RakutenProductOut(RakutenProductIn):
    id:               int
    sales_updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

@router.get("/products", response_model=List[RakutenProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.query(RakutenProduct).filter(RakutenProduct.is_active == True).order_by(RakutenProduct.id).all()

@router.post("/products", response_model=RakutenProductOut)
def create_product(data: RakutenProductIn, db: Session = Depends(get_db)):
    if db.query(RakutenProduct).filter(RakutenProduct.sku == data.sku).first():
        raise HTTPException(400, "SKUが既に存在します")
    p = RakutenProduct(**data.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p

@router.put("/products/{product_id}", response_model=RakutenProductOut)
def update_product(product_id: int, data: RakutenProductIn, db: Session = Depends(get_db)):
    p = db.query(RakutenProduct).filter(RakutenProduct.id == product_id).first()
    if not p:
        raise HTTPException(404, "商品が見つかりません")
    dup = db.query(RakutenProduct).filter(
        RakutenProduct.sku == data.sku, RakutenProduct.id != product_id
    ).first()
    if dup:
        raise HTTPException(400, "SKUが既に存在します")
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p

@router.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    p = db.query(RakutenProduct).filter(RakutenProduct.id == product_id).first()
    if not p:
        raise HTTPException(404)
    p.is_active = False
    db.commit()
    return {"ok": True}

@router.patch("/products/{product_id}/stock")
def update_stock(product_id: int, body: dict, db: Session = Depends(get_db)):
    p = db.query(RakutenProduct).filter(RakutenProduct.id == product_id).first()
    if not p:
        raise HTTPException(404)
    if "stock" in body:
        p.stock = body["stock"]
    if "inbound" in body:
        p.inbound = body["inbound"]
    if "sales_30_recent" in body:
        p.sales_30_recent = body["sales_30_recent"]
    if "sales_30_prev" in body:
        p.sales_30_prev = body["sales_30_prev"]
        p.sales_updated_at = datetime.now()
    db.commit()
    return {"ok": True}


# ============================================================
# Order Recommendations（発注推奨リスト）
# ============================================================

@router.get("/orders/recommendations")
def get_recommendations(db: Session = Depends(get_db)):
    settings_row = _get_or_create_settings(db)
    s = RakutenCalcSettings(
        lead_days=settings_row.lead_days,
        target_days=settings_row.target_days,
        safety_stock_rate=settings_row.safety_stock_rate,
        threshold_days=settings_row.threshold_days,
    )

    # 発注済み（未納品）の数量をSKUごとに集計
    ordered_by_sku = dict(
        db.query(RakutenOrderHistory.sku, func.sum(RakutenOrderHistory.qty))
        .filter(RakutenOrderHistory.is_delivered == False, RakutenOrderHistory.is_deleted == False)
        .group_by(RakutenOrderHistory.sku)
        .all()
    )

    # スーパーセールmodeB: 前回のセール販売数（簡易: super_sale_qty は未来の実装）
    super_sale_qty = 0  # TODO: 実装時に商品ごとのセール数を参照

    products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
    items = []
    for p in products:
        ordered = ordered_by_sku.get(p.sku, 0) or 0
        calc = calc_rakuten_order(
            stock=p.stock or 0,
            inbound=p.inbound or 0,
            ordered=ordered,
            sales_30_recent=p.sales_30_recent or 0,
            sales_30_prev=p.sales_30_prev or 0,
            super_sale_qty=super_sale_qty,
            s=s,
        )
        items.append({
            "product_id":     p.id,
            "sku":            p.sku or "",
            "name":           p.name or "",
            "jan_code":       p.jan_code or "",
            "buy_url":        p.buy_url or "",
            "set_size":       p.set_size or 1,
            "stock":          p.stock or 0,
            "inbound":        p.inbound or 0,
            "ordered":        ordered,
            "total_stock":    calc.total_stock,
            "daily_avg":      calc.daily_avg,
            "days_left":      calc.days_left,
            "growth_rate":    calc.growth_rate,
            "predicted_30":   calc.predicted_30,
            "lead_sales":     calc.lead_sales,
            "safety_stock":   calc.safety_stock,
            "order_qty":      calc.order_qty,
            "needs_order":    calc.needs_order,
            "sales_30_recent": p.sales_30_recent or 0,
            "sales_30_prev":   p.sales_30_prev or 0,
        })

    return {"items": items, "settings": RakutenSettingsSchema.model_validate(settings_row)}


# ============================================================
# Order History（発注済みリスト）
# ============================================================

class RakutenOrderIn(BaseModel):
    sku:       str
    name:      Optional[str] = None
    qty:       int
    ordered_at: Optional[date] = None
    memo:      Optional[str] = None

class RakutenOrderOut(BaseModel):
    id:          int
    sku:         str
    name:        Optional[str] = None
    qty:         int
    ordered_at:  Optional[date] = None
    is_delivered: bool
    memo:        Optional[str] = None

    class Config:
        from_attributes = True

@router.get("/orders/history", response_model=List[RakutenOrderOut])
def list_orders(db: Session = Depends(get_db)):
    return (
        db.query(RakutenOrderHistory)
        .filter(RakutenOrderHistory.is_deleted == False)
        .order_by(RakutenOrderHistory.ordered_at.desc())
        .all()
    )

@router.post("/orders/history", response_model=RakutenOrderOut)
def create_order(data: RakutenOrderIn, db: Session = Depends(get_db)):
    o = RakutenOrderHistory(
        sku=data.sku,
        name=data.name,
        qty=data.qty,
        ordered_at=data.ordered_at or date.today(),
        memo=data.memo,
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o

@router.patch("/orders/history/{order_id}/deliver")
def mark_delivered(order_id: int, db: Session = Depends(get_db)):
    o = db.query(RakutenOrderHistory).filter(RakutenOrderHistory.id == order_id).first()
    if not o:
        raise HTTPException(404)
    o.is_delivered = True
    db.commit()
    return {"ok": True}

@router.delete("/orders/history/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db)):
    o = db.query(RakutenOrderHistory).filter(RakutenOrderHistory.id == order_id).first()
    if not o:
        raise HTTPException(404)
    o.is_deleted = True
    db.commit()
    return {"ok": True}
