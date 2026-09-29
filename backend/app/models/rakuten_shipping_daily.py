from sqlalchemy import (Column, Integer, Float, Date, DateTime,
                        UniqueConstraint)
from sqlalchemy.sql import func

from app.core.database import Base


class RakutenShippingDaily(Base):
    """楽天の1日ぶんの発送件数と売上金額。

    受注APIから毎回数え直すと、1年ぶんで数百回の呼び出しになって重い。
    一度数えたものはここに置いて、次からは足りない日だけ取りに行く。

    日付は「発送日」。注文日ではない。実際に出した日で並べたい、という
    用途のもの。1注文に送付先が複数あることがあるので、注文の件数と
    送付先の件数を分けて持つ。
    """
    __tablename__ = "rakuten_shipping_daily"
    __table_args__ = (
        UniqueConstraint("day", name="uq_rakuten_shipping_daily_day"),
    )

    id = Column(Integer, primary_key=True)
    day = Column(Date, nullable=False, index=True)

    order_count = Column(Integer, default=0)      # 発送した注文の件数
    package_count = Column(Integer, default=0)    # 送付先の件数（同梱ぶんを分ける）
    total_price = Column(Float, default=0)        # 請求金額の合計（送料・手数料込み）
    goods_price = Column(Float, default=0)        # 商品代の合計

    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
