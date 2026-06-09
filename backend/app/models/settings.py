from sqlalchemy import Column, Integer, String, Float, Boolean, Date
from app.core.database import Base

class OrderSettings(Base):
    __tablename__ = "order_settings"

    id = Column(Integer, primary_key=True, default=1)
    threshold_days = Column(Integer, default=75)
    target_days_normal = Column(Integer, default=75)
    target_days_sale = Column(Integer, default=90)
    weight_d7 = Column(Float, default=0.05)
    weight_d15 = Column(Float, default=0.10)
    weight_d30 = Column(Float, default=0.30)
    weight_d60 = Column(Float, default=0.55)
    growth_ratio_threshold = Column(Float, default=1.3)
    growth_multiplier = Column(Float, default=1.0)
    decline_ratio_threshold = Column(Float, default=0.7)
    decline_multiplier = Column(Float, default=0.8)
    min_order_qty = Column(Integer, default=10)
    lead_days = Column(Integer, default=75)
    sale_enabled = Column(Boolean, default=False)
    sale_start = Column(Date, nullable=True)
    sale_end = Column(Date, nullable=True)
    sale_multiplier = Column(Float, default=3.0)
    exchange_rate = Column(Float, default=21.0)          # 円/元
    price_adjust_enabled = Column(Boolean, default=False) # 価格自動調整ON/OFF
    price_drop_threshold = Column(Float, default=0.20)    # 値下げ判定: 前期比20%減
    price_change_pct = Column(Float, default=0.03)        # 変更幅3%
    min_profit_rate = Column(Float, default=0.10)         # 下限利益率10%
    new_product_exclude_vine = Column(Boolean, default=True) # VINEを販売数から除外
