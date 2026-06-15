from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class ShipmentOrder(Base):
    __tablename__ = "shipment_orders"

    id = Column(Integer, primary_key=True, index=True)
    tracking_no = Column(String, index=True)        # 追跡番号（VIP...）
    order_no = Column(String)                        # 配送依頼No
    shipped_date = Column(String)                    # 出荷日
    box_count = Column(Integer, default=0)           # 箱数
    total_weight_kg = Column(Float, default=0)       # 実際重量(KG)
    status = Column(String, default="pending")       # pending / received
    received_at = Column(DateTime(timezone=True), nullable=True)  # 入荷日時
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ShipmentOrderItem(Base):
    __tablename__ = "shipment_order_items"

    id = Column(Integer, primary_key=True, index=True)
    shipment_order_id = Column(Integer, ForeignKey("shipment_orders.id"), index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)  # NULL = 未照合
    name_cn = Column(String)         # 中国語商品名
    color = Column(String)           # 色
    size = Column(String)            # サイズ
    buy_url = Column(String)         # 1688 URL
    unit_price_cny = Column(Float, default=0)
    qty = Column(Integer, default=0)
    is_matched = Column(Boolean, default=False)  # 商品マスタと照合済みか
