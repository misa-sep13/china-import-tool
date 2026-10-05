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


class SeoTidyIgnore(Base):
    """整理の一覧に出さないもの。

    自社制作品（チラシ・置き配ステッカーなど）は在庫を管理しないので
    商品マスタに無いが、商品としては存在する。毎回「終売では」と
    出されても困るので、一度「出さない」と決めたものを覚えておく。
    """
    __tablename__ = "seo_tidy_ignores"

    id         = Column(Integer, primary_key=True)
    kind       = Column(String, index=True)   # keyword / page
    value      = Column(String, index=True)   # キーワードid / 商品ページコード
    note       = Column(String)
    created_at = Column(DateTime, server_default=func.now())
