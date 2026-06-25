from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ProcessedOrder(Base):
    __tablename__ = "processed_orders"

    id = Column(Integer, primary_key=True)
    order_number = Column(String, unique=True, index=True, nullable=False)
    state = Column(String, nullable=False)  # "active" or "cancelled"
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
