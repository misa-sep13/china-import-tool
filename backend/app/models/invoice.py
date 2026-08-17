from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.core.database import Base

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    invoice_no = Column(String, index=True)       # インボイス番号
    invoice_date = Column(String)                  # 仕入日
    exchange_rate = Column(Float, default=20.0)    # 為替レート（円/元）
    domestic_freight = Column(Float, default=0)    # 国内運費（元）
    international_freight = Column(Float, default=0)  # 国際運費（元）
    total_weight = Column(Float, default=0)        # 総重量（kg）
    total_volume = Column(Float, default=0)        # 総容積（m3）
    note = Column(Text)
    # 輸入許可書から取得する税額
    customs_duty = Column(Integer, default=0)          # 関税
    consumption_tax = Column(Integer, default=0)       # 消費税
    local_consumption_tax = Column(Integer, default=0) # 地方消費税
    total_tax = Column(Integer, default=0)             # 納税額合計
    import_tax_jpy = Column(Float, default=0)          # 輸入税合計（原価按分に使う）
    customs_fee_jpy = Column(Float, default=0)         # 通関料（船便のみ一律。許可書に載らない）
    bl_number = Column(String)                         # B/L番号
    declaration_no = Column(String)                    # 申告番号
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), index=True)
    sku = Column(String, index=True)               # タオタロウSKU番号
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    name_cn = Column(String)                       # 中文品名
    name_jp = Column(String)                       # 日本語品名
    qty = Column(Integer, default=0)               # 数量
    unit_price_cny = Column(Float, default=0)      # 単価（元）
    total_price_cny = Column(Float, default=0)     # 合計（元）
    freight_alloc_cny = Column(Float, default=0)   # 按分送料（元）
    cost_per_unit_jpy = Column(Float, default=0)   # 1個あたり原価（円）
    buy_url = Column(String)                       # 1688リンク
    # 申告欄ごとの税率で計算した内訳
    tax_alloc_jpy = Column(Float, default=0)       # 按分された輸入税（円）
    customs_fee_alloc_jpy = Column(Float, default=0)  # 按分された通関料（円）
    duty_jpy = Column(Float, default=0)            # 関税（円）
    col_no = Column(Integer)                       # 対応する申告欄番号
    tariff_rate = Column(Float, default=0)         # 適用した関税率（%）
