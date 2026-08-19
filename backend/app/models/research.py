from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ResearchTarget(Base):
    """リサーチ対象として登録したジャンルID・検索キーワード。
    ローカルバッチがこれを読んで週次で楽天APIを叩く。"""
    __tablename__ = "research_targets"

    id          = Column(Integer, primary_key=True)
    type        = Column(String, nullable=False)   # "keyword" | "genre"
    value       = Column(String, nullable=False)    # キーワード文字列 or ジャンルID
    label       = Column(String)                    # 画面表示用の名前（未指定ならvalueを表示）
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, server_default=func.now())


class ResearchCandidate(Base):
    """バッチが直近に取得した候補商品。対象ごとに毎回洗い替えする
    （履歴は持たず「今の最新候補」のみを保持するシンプルな設計）。"""
    __tablename__ = "research_candidates"

    id                = Column(Integer, primary_key=True)
    research_target_id = Column(Integer, index=True)
    item_code         = Column(String, index=True)
    item_name         = Column(String)
    item_price        = Column(Integer)
    review_count      = Column(Integer, default=0)
    review_average    = Column(Float, default=0)
    shop_code         = Column(String)
    shop_name         = Column(String)
    item_url          = Column(String)
    image_url         = Column(String)
    rank              = Column(Integer, nullable=True)  # ランキングAPI由来のときだけ入る
    fetched_at        = Column(DateTime)


class ResearchWatchlistItem(Base):
    """ピックアップして保存した商品。取得時点のスナップショットを保持し、
    月間売上は楽天APIでは取れないため手動入力する。"""
    __tablename__ = "research_watchlist_items"

    id             = Column(Integer, primary_key=True)
    item_code      = Column(String, unique=True, index=True)
    item_name      = Column(String)
    item_price     = Column(Integer)
    review_count   = Column(Integer, default=0)
    review_average = Column(Float, default=0)
    shop_code      = Column(String)
    shop_name      = Column(String)
    item_url       = Column(String)
    image_url      = Column(String)
    monthly_sales  = Column(Integer, nullable=True)  # 手動入力（自分で見た月間売上）
    folder         = Column(String, nullable=True)   # 整理用のフォルダ名
    memo           = Column(Text, nullable=True)
    picked_at      = Column(DateTime, server_default=func.now())
