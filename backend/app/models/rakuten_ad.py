from sqlalchemy import (Column, Integer, String, Float, Date, DateTime,
                        UniqueConstraint, Index)
from sqlalchemy.sql import func

from app.core.database import Base


class RakutenAdDaily(Base):
    """楽天RPPの、1日ぶんの消化。

    RMSのパフォーマンスレポートで、集計単位「すべての広告」＋期間
    「日ごとに表示」で落としたCSVを入れる。日ごとに出せるのはここまでで、
    商品別は月ごと・全期間でしか出せない（楽天の仕様）。
    """
    __tablename__ = "rakuten_ad_daily"
    __table_args__ = (
        UniqueConstraint("day", "campaign", name="uq_rakuten_ad_daily"),
    )

    id = Column(Integer, primary_key=True)
    day = Column(Date, nullable=False, index=True)
    campaign = Column(String, default="")      # すべての広告なら空

    clicks = Column(Integer, default=0)
    cost = Column(Float, default=0)            # 実績額（広告費）
    sales = Column(Float, default=0)           # 広告経由の売上
    orders = Column(Integer, default=0)        # 売上件数
    cpc = Column(Float, default=0)
    roas = Column(Float, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())


class RakutenAdProduct(Base):
    """楽天RPPの、商品ごとの実績。

    「全商品レポートダウンロード」のCSVを入れる。期間は月単位。
    どの商品がどれだけクリックされ、どれだけ売れたか（CVR）を見る。
    """
    __tablename__ = "rakuten_ad_product"
    __table_args__ = (
        UniqueConstraint("period", "manage_number",
                         name="uq_rakuten_ad_product"),
        Index("ix_rakuten_ad_product_period", "period"),
    )

    id = Column(Integer, primary_key=True)
    period = Column(String, nullable=False)    # YYYY-MM
    manage_number = Column(String, nullable=False, index=True)
    item_name = Column(String, default="")

    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    ctr = Column(Float, default=0)             # %
    cost = Column(Float, default=0)            # 実績額
    cpc = Column(Float, default=0)
    sales = Column(Float, default=0)           # 広告経由の売上
    orders = Column(Integer, default=0)        # 売上件数
    cvr = Column(Float, default=0)             # %
    roas = Column(Float, default=0)            # %
    bid = Column(Float, default=0)             # 入札単価
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())


class RakutenAdItemDaily(Base):
    """楽天RPPの、商品ごと・1日ぶんの実績。

    商品別は「月ごと／全期間」でしか検索できないが、全商品レポートの
    集計期間を1日だけにすれば、その日の商品別が出る。クリックの暴走は
    商品単位で起きるので、見張るにはこの粒度が要る。
    """
    __tablename__ = "rakuten_ad_item_daily"
    # day は index=True で自動的に ix_rakuten_ad_item_daily_day が作られる。
    # ここで同じ名前のIndexを足すと名前がぶつかって起動できなくなる
    __table_args__ = (
        UniqueConstraint("day", "manage_number", name="uq_rakuten_ad_item_daily"),
    )

    id = Column(Integer, primary_key=True)
    day = Column(Date, nullable=False, index=True)
    manage_number = Column(String, nullable=False, index=True)
    item_name = Column(String, default="")

    clicks = Column(Integer, default=0)
    ctr = Column(Float, default=0)
    cost = Column(Float, default=0)
    cpc = Column(Float, default=0)
    sales = Column(Float, default=0)
    orders = Column(Integer, default=0)
    cvr = Column(Float, default=0)
    roas = Column(Float, default=0)
    bid = Column(Float, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
