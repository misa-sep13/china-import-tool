from sqlalchemy import Column, Integer, String, Date, Boolean, UniqueConstraint
from app.core.database import Base


class RakutenDailySales(Base):
    __tablename__ = "rakuten_daily_sales"

    id = Column(Integer, primary_key=True)
    sale_date = Column(Date, nullable=False, index=True)
    sku = Column(String, nullable=False, index=True)
    qty = Column(Integer, default=0)
    is_stockout = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("sale_date", "sku", name="uq_daily_sales_date_sku"),
    )
