from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class InventoryReflectionLog(Base):
    __tablename__ = "inventory_reflection_logs"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, index=True)
    source = Column(String, index=True)        # shipment_order / manufacturer_receive
    source_label = Column(String)              # 配送依頼 / メーカー入荷
    source_id = Column(Integer, nullable=True)
    source_ref = Column(String, nullable=True) # 追跡番号・配送依頼Noなど
    sku = Column(String, index=True)
    name = Column(String)
    supplier = Column(String)
    received_qty = Column(Integer, default=0)
    stock_before = Column(Integer, default=0)
    stock_after = Column(Integer, default=0)
    inbound_before = Column(Integer, default=0)
    inbound_after = Column(Integer, default=0)
    standard_stock_before = Column(Integer, default=0)
    standard_stock_after = Column(Integer, default=0)
    rms_push_items = Column(Integer, default=0)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
