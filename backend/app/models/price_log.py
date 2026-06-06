from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base

class PriceAdjustmentLog(Base):
    __tablename__ = "price_adjustment_log"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    sku = Column(String, nullable=False)
    old_price = Column(Float, nullable=False)
    new_price = Column(Float, nullable=False)
    reason = Column(String, nullable=False)   # "up" | "down" | "revert"
    daily_before = Column(Float, nullable=True)  # 前期14日日販
    daily_after = Column(Float, nullable=True)   # 今期14日日販
    status = Column(String, default="pending")   # "pending" | "approved" | "rejected" | "applied"
    suggested_at = Column(DateTime(timezone=True), server_default=func.now())
    applied_at = Column(DateTime(timezone=True), nullable=True)
