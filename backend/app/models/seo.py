from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, Float
from sqlalchemy.sql import func
from app.core.database import Base


class SeoKeyword(Base):
    __tablename__ = "seo_keywords"

    id          = Column(Integer, primary_key=True)
    keyword     = Column(String, nullable=False)
    product_sku = Column(String, index=True)
    product_name = Column(String)
    is_active   = Column(Boolean, default=True)
    memo        = Column(Text)
    created_at  = Column(DateTime, server_default=func.now())


class SeoRanking(Base):
    __tablename__ = "seo_rankings"

    id             = Column(Integer, primary_key=True)
    seo_keyword_id = Column(Integer, index=True)
    keyword        = Column(String, nullable=False)
    product_sku    = Column(String)
    rank           = Column(Integer)
    page           = Column(Integer)
    total_items    = Column(Integer)
    card_type      = Column(String)
    checked_at     = Column(DateTime)
    created_at     = Column(DateTime, server_default=func.now())
