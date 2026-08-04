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
    supplier = Column(String, default="タオタロウ")  # 仕入先
    photo_url = Column(String)
    color = Column(String)
    size = Column(String)
    price = Column(Float, default=0)        # 仕入れ単価（元）
    cost_jpy = Column(Float, nullable=True) # 1個あたり原価（円）: 送料・輸入税込み
    repack = Column(String)                 # リパック要否
    spec = Column(String)                   # 仕様（Excel用・色/サイズをまとめた表示用）
    customer_memo = Column(Text)            # お客様専用メモ（Excel出力用）
    note = Column(Text)
    set_size = Column(Integer, default=1)   # 1セットあたりのピース数
    extra_stock = Column(Integer, default=0)  # 別個数在庫
    order_qty = Column(Integer, default=0)  # 手動発注数
    # 発注用付属品（在庫連動しない）: JSON文字列 "[{\"sku\":\"y48_bag\",\"qty\":1}]"
    # 楽天のrakuten_products.purchase_componentsと同じ役割。
    # 本体を発注するとき、この部品も一緒にタオタロウへ発注する必要があるが、
    # FBA在庫の計算には一切関与しない（main.pyの在庫連動ロジックはこれを参照しない）
    purchase_components = Column(Text, nullable=True)
    is_component = Column(Boolean, default=False)  # 付属品（他商品から参照される側）フラグ
    # 利益計算用
    selling_price = Column(Float, nullable=True)       # 販売価格（円）
    fba_fee = Column(Float, nullable=True)             # FBA手数料（円）
    amazon_fee_rate = Column(Float, default=0.1)       # Amazon手数料率（例: 0.10 = 10%）
    fees_updated_at = Column(DateTime(timezone=True), nullable=True)  # 最終取得日時
    price_auto_adjust = Column(Boolean, default=True)   # 価格自動調整対象
    price_max = Column(Float, nullable=True)            # 上限価格（円）
    category = Column(String, default='標準')             # 区分: 標準/ファッション/大型
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
