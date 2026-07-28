from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, func
from app.core.database import Base

class OrderHistory(Base):
    __tablename__ = "order_history"

    id = Column(Integer, primary_key=True, index=True)
    ordered_at = Column(DateTime(timezone=True), server_default=func.now())
    sku = Column(String)
    name = Column(String)
    color = Column(String)
    size = Column(String)
    qty = Column(Integer)
    price = Column(Float, default=0)
    buy_url = Column(String)
    photo_url = Column(String)
    asin = Column(String)
    fnsku = Column(String)
    note = Column(String)
    is_deleted = Column(Boolean, default=False)
    status = Column(String, default="ordered")    # ordered / arrived / shipped
    arrived_at = Column(DateTime(timezone=True), nullable=True)
    taotaro_order_id = Column(String, nullable=True)
