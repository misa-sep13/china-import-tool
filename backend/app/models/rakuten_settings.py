from sqlalchemy import Column, Integer, String, Float, Boolean, Date
from app.core.database import Base

class RakutenSettings(Base):
    __tablename__ = "rakuten_settings"

    id                  = Column(Integer, primary_key=True, default=1)
    lead_days           = Column(Integer, default=20)       # 発注〜入荷日数
    target_days         = Column(Integer, default=30)       # 予測販売数の期間
    safety_stock_rate   = Column(Float,   default=0.10)     # 安全在庫率（10%）
    threshold_days      = Column(Integer, default=60)       # 発注タイミング閾値（在庫量設定日数）
    # スーパーセール
    super_sale_enabled  = Column(Boolean, default=False)
    super_sale_mode     = Column(String,  default='A')      # 'A'=除外, 'B'=追加
    super_sale_start    = Column(Date,    nullable=True)
    super_sale_end      = Column(Date,    nullable=True)
