from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class InventoryEvent(Base):
    __tablename__ = "inventory_events"

    id = Column(Integer, primary_key=True)
    event_time = Column(DateTime, nullable=False)
    event_type = Column(String, nullable=False)
    order_numbers = Column(Text)
    sold = Column(Text)
    changed = Column(Text)
    recalculated = Column(Text)
    pushed = Column(Text)
    push_ok = Column(Integer)
    push_fail = Column(Integer)
    errors = Column(Text)
    stock_before = Column(Text)
    stock_after = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
