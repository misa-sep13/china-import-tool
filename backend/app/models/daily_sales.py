from sqlalchemy import (Column, Integer, String, Float, Boolean, Date,
                        DateTime, UniqueConstraint, Index)
from sqlalchemy.sql import func

from app.core.database import Base


class DailySales(Base):
    """SKU×日ごとの実績。発注ロジックの土台。

    これまでは7/15/30/60/90日の集計値しか持っていなかったが、それでは
      ・在庫切れの日をノーカウントにする
      ・セール日を実測倍率で割り戻す
      ・まとめ買いの日を頭打ちにする
    ができない。どれも「その日どうだったか」を知らないと判断できない。

    1日1行を毎日ためていく。過去分はレポートから遡って埋められる。
    """

    __tablename__ = "daily_sales"
    __table_args__ = (
        UniqueConstraint("sku", "day", name="uq_daily_sales_sku_day"),
        Index("ix_daily_sales_day", "day"),
    )

    id = Column(Integer, primary_key=True)
    sku = Column(String, index=True, nullable=False)
    asin = Column(String, index=True)
    day = Column(Date, nullable=False)

    # 売れた数（Vineを含む生の数）
    units = Column(Integer, default=0)
    # そのうちVine（レビュー用の無料配布）。有償の需要ではないので後で引く
    vine_units = Column(Integer, default=0)
    # 売上（円）。実効単価を出してセール対象かどうかを見分けるのに使う
    revenue = Column(Float, default=0)
    # プロモーションの値引き（円）。実効単価 =(revenue - promo)/units
    promo_discount = Column(Float, default=0)

    # その日の終わりにFBAの販売可能在庫があったか。
    # 無い日は「売れなかった」のではなく「売れなかっただけ」なので数えない
    in_stock = Column(Boolean, default=True)
    # FBA在庫元帳の期末残（SELLABLE）。in_stock の根拠として残す
    sellable_end = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SaleWindow(Base):
    """セール期間と、その実測倍率。

    セール日を「無かったこと」にすると、セール中に出した新商品が
    日販0になったり、直近7日窓が暦基準だと有効日数0日になって
    発注が半減→倍増する崖が起きる。そこで除外せず、実測倍率で
    平常日に換算して数える。倍率はここに持つ。
    """

    __tablename__ = "sale_windows"

    id = Column(Integer, primary_key=True)
    name = Column(String)                       # プライムデー など
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    # 開始前〜2日目に使う、人が入れた見込み倍率
    planned_target = Column(Float, default=2.5)     # セール対象商品
    planned_other = Column(Float, default=1.2)      # 対象外商品

    # 3日目以降に使う実測。夜間の集計で入る
    actual_target = Column(Float, nullable=True)
    actual_other = Column(Float, nullable=True)

    # 手で決め打ちしたいとき。優先順は 手動 > 実測 > 見込み
    manual_target = Column(Float, nullable=True)
    manual_other = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class DailySalesSync(Base):
    """日別データをどこまで取り込めたか。

    古いまま気づかず発注すると、直近日が欠品扱いになって
    「セールを信じすぎる」方向に倒れる。鮮度が落ちたら発注を止めるため、
    最後に取り込めた日を残しておく。
    """

    __tablename__ = "daily_sales_sync"

    id = Column(Integer, primary_key=True)
    kind = Column(String, unique=True)      # orders / ledger
    last_day = Column(Date, nullable=True)  # ここまで取り込めた
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String, nullable=True)
