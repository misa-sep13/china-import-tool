from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class ReviewCampaign(Base):
    __tablename__ = "review_campaigns"

    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, index=True)  # review-A, review-C etc
    name = Column(String)                            # 魔法のクロス, シリコン耳栓 etc
    product_sku = Column(String)                     # 対応する楽天SKU (optional)
    keywords = Column(Text)                          # 判定キーワード（カンマ区切り）
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class ReviewEntry(Base):
    __tablename__ = "review_entries"

    id = Column(Integer, primary_key=True)
    order_number = Column(String, index=True)
    zip1 = Column(String)
    zip2 = Column(String)
    prefecture = Column(String)
    city = Column(String)
    address = Column(String)
    last_name = Column(String)
    first_name = Column(String)
    campaign_code = Column(String, index=True)
    campaign_name = Column(String)
    quantity = Column(Integer, default=1)
    phone1 = Column(String)
    phone2 = Column(String)
    phone3 = Column(String)
    status = Column(String, default="pending")  # pending / confirmed / shipped / skipped
    batch_date = Column(String)                 # import batch identifier (e.g. "2026-07-09")
    inquiry_message = Column(Text)
    buyer_name = Column(String)
    buyer_differs = Column(Boolean, default=False)
    item_name = Column(String)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
