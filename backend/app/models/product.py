from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    no = Column(Integer)
    sku = Column(String, unique=True, index=True)
    fnsku = Column(String, index=True)
    asin = Column(String, index=True)
    name = Column(String)
    amazon_url = Column(String)
    buy_url = Column(String)        # 仕入れURL（1688/TAOBao）
    photo_url = Column(String)
    color = Column(String)
    size = Column(String)
    price = Column(Float, default=0)        # 仕入れ単価（元）
    repack = Column(String)                 # リパック要否
    note = Column(Text)
    set_size = Column(Integer, default=1)   # 1セットあたりのピース数
    extra_stock = Column(Integer, default=0)  # 別個数在庫
    order_qty = Column(Integer, default=0)  # 手動発注数
    # 利益計算用
    selling_price = Column(Float, nullable=True)       # 販売価格（円）
    fba_fee = Column(Float, nullable=True)             # FBA手数料（円）
    amazon_fee_rate = Column(Float, default=0.1)       # Amazon手数料率（例: 0.10 = 10%）
    fees_updated_at = Column(DateTime(timezone=True), nullable=True)  # 最終取得日時
    price_auto_adjust = Column(Boolean, default=True)   # 価格自動調整対象
    price_max = Column(Float, nullable=True)            # 上限価格（円）
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
