from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class RakutenProduct(Base):
    __tablename__ = "rakuten_products"

    id           = Column(Integer, primary_key=True)
    sku          = Column(String, unique=True, index=True)  # 商品管理番号（URL）: 楽天URLキー・ITEM-001形式
    name         = Column(String)
    jan_code     = Column(String)               # JANコード
    buy_url      = Column(String)               # 仕入れURL（タオタロウ発注URL）
    price        = Column(Float)                # 仕入れ値（元）
    spec         = Column(String)               # システム連携用SKU番号（全角48文字）
    set_size     = Column(Integer, default=1)   # セット入数
    # 楽天管理情報
    rakuten_item_url = Column(String)           # 在庫管理番号（社内管理用）
    rakuten_sku_id   = Column(String)           # 楽天SKU管理番号（半角32文字: y60_4_black形式）
    supplier         = Column(String)           # 仕入先
    standard_stock   = Column(Integer, default=0)  # 規定在庫数
    # 在庫
    stock        = Column(Integer, default=0)    # 実在庫（手持ち）
    inbound      = Column(Integer, default=0)    # 輸送中
    # 販売実績（楽天APIまたは手動入力）
    sales_30_recent  = Column(Integer, default=0) # 直近30日販売数
    sales_30_prev    = Column(Integer, default=0) # 60日前〜31日前の30日販売数
    sales_updated_at = Column(DateTime, nullable=True)
    # メモ
    customer_memo = Column(Text)                # お客様専用メモ（TAO太郎G列）
    notes         = Column(Text)                # 備考（TAO太郎H列）
    memo          = Column(Text)                # 内部メモ
    # セット構成（単品管理）: JSON文字列 "[{\"sku\":\"ITEM-001\",\"qty\":2}]"
    set_components = Column(Text)
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, server_default=func.now())
