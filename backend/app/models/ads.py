from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class AdsCampaign(Base):
    __tablename__ = "ads_campaigns"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    campaign_type = Column(String, index=True)
    parent_asin = Column(String, index=True)
    state = Column(String)
    targeting_type = Column(String)
    budget_amount = Column(Float)
    budget_type = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    bidding_strategy = Column(String)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    cost = Column(Float, default=0)
    orders = Column(Integer, default=0)
    sales = Column(Float, default=0)
    synced_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AdsAdGroup(Base):
    __tablename__ = "ads_ad_groups"

    id = Column(Integer, primary_key=True, index=True)
    ad_group_id = Column(String, unique=True, index=True, nullable=False)
    campaign_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    state = Column(String)
    default_bid = Column(Float)
    synced_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AdsKeyword(Base):
    __tablename__ = "ads_keywords"

    id = Column(Integer, primary_key=True, index=True)
    keyword_id = Column(String, unique=True, index=True, nullable=False)
    campaign_id = Column(String, index=True, nullable=False)
    ad_group_id = Column(String, index=True, nullable=False)
    keyword_text = Column(String, nullable=False)
    match_type = Column(String)
    state = Column(String)
    bid = Column(Float)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    cost = Column(Float, default=0)
    orders = Column(Integer, default=0)
    sales = Column(Float, default=0)
    acos = Column(Float)
    cpc = Column(Float)
    report_days = Column(Integer)
    synced_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AdsTarget(Base):
    __tablename__ = "ads_targets"

    id = Column(Integer, primary_key=True, index=True)
    target_id = Column(String, unique=True, index=True, nullable=False)
    campaign_id = Column(String, index=True, nullable=False)
    ad_group_id = Column(String, index=True, nullable=False)
    expression_type = Column(String)
    expression = Column(Text)
    resolved_asin = Column(String, index=True)
    state = Column(String)
    bid = Column(Float)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    cost = Column(Float, default=0)
    orders = Column(Integer, default=0)
    sales = Column(Float, default=0)
    acos = Column(Float)
    cpc = Column(Float)
    report_days = Column(Integer)
    synced_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AdsSearchTerm(Base):
    __tablename__ = "ads_search_terms"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(String, index=True, nullable=False)
    ad_group_id = Column(String, index=True)
    keyword_id = Column(String, index=True)
    search_term = Column(String, nullable=False, index=True)
    match_type = Column(String)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    cost = Column(Float, default=0)
    orders = Column(Integer, default=0)
    sales = Column(Float, default=0)
    acos = Column(Float)
    cpc = Column(Float)
    report_start_date = Column(String)
    report_end_date = Column(String)
    synced_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AdsSyncLog(Base):
    __tablename__ = "ads_sync_logs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, unique=True, index=True)
    sync_type = Column(String, nullable=False)
    status = Column(String, nullable=False)
    records_fetched = Column(Integer, default=0)
    records_upserted = Column(Integer, default=0)
    error_message = Column(Text)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
