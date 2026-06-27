from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class WelfareInventoryItem(Base):
    __tablename__ = "welfare_inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("rakuten_products.id"), nullable=True, index=True)
    sku = Column(String, index=True)
    name_jp = Column(String)
    name_cn = Column(Text)
    supplier_spec = Column(String)
    buy_url = Column(Text)
    unit_per_set = Column(Integer, default=1)
    total_received_units = Column(Integer, default=0)
    total_received_qty = Column(Integer, default=0)
    withdrawn_qty = Column(Integer, default=0)
    remaining_qty = Column(Integer, default=0)
    instruction = Column(Text)
    note = Column(Text)
    last_received_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WelfareInventoryMovement(Base):
    __tablename__ = "welfare_inventory_movements"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("welfare_inventory_items.id"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("rakuten_products.id"), nullable=True, index=True)
    sku = Column(String, index=True)
    movement_type = Column(String, index=True)  # import / withdraw / adjust
    source_file = Column(String)
    source_order_no = Column(String)
    name_cn = Column(Text)
    supplier_spec = Column(String)
    buy_url = Column(Text)
    units = Column(Integer, default=0)
    qty = Column(Integer, default=0)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WelfareWorkInstruction(Base):
    __tablename__ = "welfare_work_instructions"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("rakuten_products.id"), nullable=True, index=True)
    sku = Column(String, index=True)
    order_date = Column(String, index=True)
    source_file = Column(String)
    source_sheet = Column(String)
    source_order_no = Column(String, index=True)
    name_jp = Column(String)
    supplier_spec = Column(String)
    buy_url = Column(Text)
    units = Column(Integer, default=0)
    unit_per_set = Column(Integer, default=1)
    qty = Column(Integer, default=0)
    instruction = Column(Text)
    remaining_qty = Column(Integer, default=0)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
