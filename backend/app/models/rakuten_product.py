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
    supplier_spec = Column(String)              # 仕入れ仕様（中国語：タオタロウB列）
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
    sales_30_recent  = Column(Integer, default=0) # 直近30日販売数（参考用）
    sales_30_prev    = Column(Integer, default=0) # 60日前〜31日前の販売数（参考用）
    sales_90         = Column(Integer, default=0) # 直近63日販売数（発注計算に使用・楽天API上限63日）
    stockout_days_90 = Column(Integer, default=0) # 在庫切れ日数（在庫管理機能実装後に自動更新）
    sales_updated_at = Column(DateTime, nullable=True)
    cost_jpy         = Column(Float)             # 仕入原価（円）
    selling_price    = Column(Float)             # 販売価格（円）
    shipping_fee     = Column(Integer, default=180)  # 送料（円）デフォルト:ネコポス180円
    # メモ
    customer_memo = Column(Text)                # お客様専用メモ（タオタロウG列）
    notes         = Column(Text)                # 備考（タオタロウH列）
    memo          = Column(Text)                # 内部メモ
    invoice_note  = Column(Text)                # 商品内訳メモ（楽天専用・インボイス振り分け用・TAO太郎ASIN欄に出力）
    # セット構成（在庫連動用）: JSON文字列 "[{\"sku\":\"ITEM-001\",\"qty\":2}]"
    set_components = Column(Text)
    # 発注用付属品（在庫連動しない）: JSON文字列 "[{\"sku\":\"ITEM-002\",\"qty\":1,\"memo\":\"付属フィルム\"}]"
    purchase_components = Column(Text)
    is_component = Column(Boolean, default=False)  # 単品（セット構成用内部管理）フラグ
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime, server_default=func.now())
