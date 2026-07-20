from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class KeywordUpload(Base):
    __tablename__ = "keyword_uploads"

    id = Column(Integer, primary_key=True)
    uploaded_at = Column(DateTime, server_default=func.now())
    period_from = Column(String)
    period_to = Column(String)
    product_count = Column(Integer, default=0)
    keyword_count = Column(Integer, default=0)


class KeywordData(Base):
    __tablename__ = "keyword_data"

    id = Column(Integer, primary_key=True)
    upload_id = Column(Integer, index=True)
    product_no = Column(Integer)
    product_name = Column(Text)
    total_access = Column(Integer, default=0)
    keyword = Column(String)
    access = Column(Integer, default=0)
    cvr = Column(Float, default=0)
    rank = Column(String)
    action_access = Column(Boolean, default=False)
    action_cvr = Column(Boolean, default=False)
    action_good = Column(Boolean, default=False)


class TitleOptimization(Base):
    __tablename__ = "title_optimizations"

    id = Column(Integer, primary_key=True)
    upload_id = Column(Integer, index=True)
    product_no = Column(Integer)
    product_name = Column(Text)
    current_title = Column(Text)
    suggested_title = Column(Text)
    reasoning = Column(Text)
    status = Column(String, default="pending")  # pending / approved / pushed / skipped
    pushed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
