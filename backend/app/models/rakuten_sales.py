from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class RakutenSalesImport(Base):
    __tablename__ = "rakuten_sales_imports"
    __table_args__ = (UniqueConstraint("period", name="uq_rakuten_sales_import_period"),)

    id = Column(Integer, primary_key=True)
    period = Column(String, index=True)  # YYYY-MM
    order_file_name = Column(String)
    rpp_file_name = Column(String)
    coupon_ad_file_name = Column(String)
    affiliate_file_name = Column(String)
    order_rows = Column(Integer, default=0)
    rpp_rows = Column(Integer, default=0)
    coupon_ad_rows = Column(Integer, default=0)
    affiliate_rows = Column(Integer, default=0)
    total_units = Column(Float, default=0)
    total_sales = Column(Float, default=0)
    total_profit = Column(Float, default=0)
    status = Column(String, default="completed")
    message = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class RakutenSalesSummary(Base):
    __tablename__ = "rakuten_sales_summaries"
    __table_args__ = (
        UniqueConstraint("period", "level", "product_key", "sku_key", name="uq_rakuten_sales_summary_row"),
    )

    id = Column(Integer, primary_key=True)
    period = Column(String, index=True)  # YYYY-MM
    level = Column(String, index=True)   # parent / sku
    product_key = Column(String, index=True)
    sku_key = Column(String, index=True)
    product_name = Column(String)
    units = Column(Float, default=0)
    sales = Column(Float, default=0)
    point_cost = Column(Float, default=0)
    all_coupon = Column(Float, default=0)
    store_coupon = Column(Float, default=0)
    coupon_fee = Column(Float, default=0)
    rpp_cost = Column(Float, default=0)
    coupon_ad_cost = Column(Float, default=0)
    affiliate_cost = Column(Float, default=0)
    affiliate_fee = Column(Float, default=0)
    sales_store_coupon_excluded = Column(Float, default=0)
    sales_all_coupon_excluded = Column(Float, default=0)
    pc_sales = Column(Float, default=0)
    mobile_sales = Column(Float, default=0)
    platform_fee = Column(Float, default=0)
    platform_fee_rate = Column(Float, default=0)
    shipping_cost = Column(Float, default=0)
    product_cost = Column(Float, default=0)
    profit = Column(Float, default=0)
    profit_rate = Column(Float)
    rpp_rate = Column(Float)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
