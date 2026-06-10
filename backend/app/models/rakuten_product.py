from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class RakutenProduct(Base):
    __tablename__ = "rakuten_products"

    id           = Column(Integer, primary_key=True)
    sku          = Column(String, unique=True, index=True)  # 商品管理番号
    name         = Column(String)
    jan_code     = Column(String)          # JANコード
    buy_url      = Column(String)          # 仕入れURL
    price        = Column(Float)           # 仕入れ値（元）
    set_size     = Column(Integer, default=1)
    # 在庫
    stock        = Column(Integer, default=0)    # 実在庫（手持ち）
    inbound      = Column(Integer, default=0)    # 輸送中
    # 販売実績（楽天APIまたは手動入力）
    sales_30_recent = Column(Integer, default=0) # 直近30日販売数
    sales_30_prev   = Column(Integer, default=0) # 60日前〜31日前の30日販売数
    sales_updated_at = Column(DateTime, nullable=True)
    # メモ
    memo         = Column(Text)
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, server_default=func.now())
