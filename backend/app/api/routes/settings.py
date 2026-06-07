from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date
from pydantic import BaseModel
from app.core.database import get_db
from app.models.settings import OrderSettings

router = APIRouter(prefix="/settings", tags=["settings"])

class SettingsSchema(BaseModel):
    threshold_days: int = 75
    target_days_normal: int = 75
    target_days_sale: int = 90
    weight_d7: float = 0.05
    weight_d15: float = 0.10
    weight_d30: float = 0.30
    weight_d60: float = 0.55
    growth_ratio_threshold: float = 1.3
    growth_multiplier: float = 1.0
    decline_ratio_threshold: float = 0.7
    decline_multiplier: float = 0.8
    min_order_qty: int = 10
    sale_enabled: bool = False
    sale_start: Optional[date] = None
    sale_end: Optional[date] = None
    exchange_rate: float = 21.0
    price_adjust_enabled: bool = False
    price_drop_threshold: float = 0.20
    price_change_pct: float = 0.03
    min_profit_rate: float = 0.10
    new_product_required_days: int = 30
    new_product_exclude_vine: bool = True

    class Config:
        from_attributes = True

@router.get("/", response_model=SettingsSchema)
def get_settings(db: Session = Depends(get_db)):
    row = db.query(OrderSettings).first()
    if not row:
        row = OrderSettings()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row

@router.put("/", response_model=SettingsSchema)
def update_settings(data: SettingsSchema, db: Session = Depends(get_db)):
    row = db.query(OrderSettings).first()
    if not row:
        row = OrderSettings(**data.model_dump())
        db.add(row)
    else:
        for k, v in data.model_dump().items():
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row
