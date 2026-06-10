from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base

class RakutenOrderHistory(Base):
    __tablename__ = "rakuten_order_history"

    id           = Column(Integer, primary_key=True)
    sku          = Column(String, index=True)
    name         = Column(String)
    qty          = Column(Integer)
    ordered_at   = Column(Date)
    is_delivered = Column(Boolean, default=False)
    is_deleted   = Column(Boolean, default=False)
    memo         = Column(Text)
    created_at   = Column(DateTime, server_default=func.now())
