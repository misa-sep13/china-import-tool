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
    lead_days: int = 75
    weight_d7: float = 0.05
    weight_d15: float = 0.15
    weight_d30: float = 0.25
    weight_d60: float = 0.25
    weight_d90: float = 0.30
    growth_ratio_threshold: float = 1.3
    growth_multiplier: float = 1.0
    decline_ratio_threshold: float = 0.7
    decline_multiplier: float = 0.8
    min_order_qty: int = 10
    sale_enabled: bool = False
    sale_start: Optional[date] = None
    sale_end: Optional[date] = None
    sale_multiplier: float = 3.0
    exchange_rate: float = 21.0
    price_adjust_enabled: bool = False
    price_drop_threshold: float = 0.20
    price_change_pct: float = 0.03
    min_profit_rate: float = 0.10
    new_product_exclude_vine: bool = True
    order_qty_cap: int = 3
    # FBA納品プラン用リードタイム詳細
    lt_order_to_warehouse: int = 7
    lt_shipping_request: int = 7
    lt_sea_to_fba: int = 18
    lt_air_to_fba: int = 10
    free_storage_days: int = 90
    air_threshold_days: int = 18
    hold_daily_threshold: float = 0.1

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


@router.get("/sp-api/test")
def sp_api_test():
    """SP-APIに繋がるか確かめる。

    アカウントを切り替えたあと、環境変数が正しく入っているかを
    データを動かさずに確認したい。マーケットプレイス一覧を1回だけ
    読む（読むだけで何も変えない、一番軽いAPI）。

    キーそのものは返さない。入っているかどうかだけ示す。
    """
    from app.core.config import settings as cfg
    from app.services.amazon_api import _call_sp_api

    have = {
        "SP_API_REFRESH_TOKEN": bool(cfg.SP_API_REFRESH_TOKEN),
        "SP_API_LWA_APP_ID": bool(cfg.SP_API_LWA_APP_ID),
        "SP_API_LWA_CLIENT_SECRET": bool(cfg.SP_API_LWA_CLIENT_SECRET),
    }
    missing = [k for k, v in have.items() if not v]
    if missing:
        return {"ok": False, "設定": have,
                "理由": f"未設定: {'、'.join(missing)}"}

    try:
        r = _call_sp_api("/sellers/v1/marketplaceParticipations")
    except Exception as e:
        msg = str(e)
        hint = ""
        if "401" in msg or "Unauthorized" in msg:
            hint = "トークンかLWAの値が違います。取り直してください"
        elif "403" in msg:
            hint = "アプリのロール（権限）が足りない可能性があります"
        return {"ok": False, "設定": have,
                "理由": f"{type(e).__name__}: {msg[:300]}", "ヒント": hint}

    # 出品しているマーケットプレイスを返す。どのアカウントに繋がったか分かる
    places = []
    for p in (r.get("payload") or []):
        m = p.get("marketplace") or {}
        places.append({"名前": m.get("name"), "国": m.get("countryCode"),
                       "id": m.get("id")})
    return {"ok": True, "設定": have, "出品先": places}
