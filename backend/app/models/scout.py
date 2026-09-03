from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, Index
from sqlalchemy.sql import func
from app.core.database import Base


class ScoutSeller(Base):
    """巡回するAmazonセラー。

    配布版のセラースカウト（SQLite）と同じ持ち方。ローカルに置いていたものを
    サーバーへ移し、誰が巡回しても同じ一覧を見られるようにする。
    """
    __tablename__ = "scout_sellers"

    seller_id = Column(String, primary_key=True, index=True)
    name = Column(String)
    folder = Column(String, index=True)     # ブックマークのフォルダ名
    url = Column(Text)
    enabled = Column(Boolean, default=True, index=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    last_run_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_status = Column(String)            # ok / blocked / error / NULL=未巡回
    last_note = Column(Text)
    last_run_by = Column(String)            # 誰が巡回したか（外注さんと分担するため）
    product_count = Column(Integer, default=0)


class ScoutProduct(Base):
    """巡回で拾った商品。

    月間販売数（「過去1か月で〇〇点以上購入されました」）はSP-APIでは取れず、
    ここでしか手に入らない。リサーチの要になる数字。
    """
    __tablename__ = "scout_products"

    id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(String, index=True)
    asin = Column(String, index=True)
    title = Column(Text)
    image = Column(Text)
    url = Column(Text)
    price = Column(Integer)                 # 円。取れなければ NULL
    sales_min = Column(Integer, index=True) # 月間販売数の下限。バッジ無しは0
    sales_text = Column(String)             # バッジの原文。仕様変更に気づけるように残す
    reviews = Column(Integer, index=True)
    rating = Column(Float)
    page = Column(Integer)                  # 何ページ目で見つけたか
    rank = Column(Integer)                  # ベストセラー順の通し順位
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# 同じセラーの同じASINは1件にまとめる（巡回のたびに上書きする）
Index("ix_scout_products_key", ScoutProduct.seller_id, ScoutProduct.asin, unique=True)


class ScoutHistory(Base):
    """日別の推移。販売数が伸びているセラー・商品を見つけるために残す。"""
    __tablename__ = "scout_histories"

    id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(String, index=True)
    asin = Column(String, index=True)
    day = Column(String, index=True)        # YYYY-MM-DD
    sales_min = Column(Integer)
    reviews = Column(Integer)
    rating = Column(Float)
    price = Column(Integer)
    rank = Column(Integer)


Index("ix_scout_hist_key", ScoutHistory.seller_id, ScoutHistory.asin,
      ScoutHistory.day, unique=True)


class ScoutBasket(Base):
    """リサーチシートへ送る「かご」。

    巡回結果から気になる商品を貯めておき、シート側でまとめて行にする。
    """
    __tablename__ = "scout_baskets"

    id = Column(Integer, primary_key=True, index=True)
    asin = Column(String, index=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    added_by = Column(String)
    taken_at = Column(DateTime(timezone=True), nullable=True)   # シートへ入れた時刻
    # 「競合リサーチシートに登録」を押した合図。シート側は5秒ごとに見に来て、
    # これが立っていたら取り込む。取り込んだら消す（次の見回りで二重に走らないため）
    register_requested_at = Column(DateTime(timezone=True), nullable=True)


class ScoutRun(Base):
    """巡回の実行記録。誰がいつ何社回したかを残す。"""
    __tablename__ = "scout_runs"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    run_by = Column(String)
    seller_count = Column(Integer, default=0)
    product_count = Column(Integer, default=0)
    blocked_count = Column(Integer, default=0)
    note = Column(Text)


class ScoutCrawlRequest(Base):
    """画面の「更新する」から出された巡回の依頼。

    巡回はブラウザ自動操縦なのでサーバーでは走らせられない（Amazonが
    データセンターのipを弾く）。かといって毎回バッチを探して叩くのは
    外注さんには続かないので、依頼だけをここに積み、手元のPCで常駐して
    いる scout_agent.py が拾って実行する。

    status: pending（未着手） / running（実行中） / done / failed / canceled
    """
    __tablename__ = "scout_crawl_requests"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    requested_by = Column(String)          # 依頼した人の役割（owner / contractor）
    kind = Column(String, default="crawl", index=True)   # crawl / bookmarks
    params = Column(Text)                  # 巡回条件（JSON）。画面の指定をそのまま持つ
    status = Column(String, default="pending", index=True)
    taken_at = Column(DateTime(timezone=True), nullable=True)
    taken_by = Column(String)              # 実際に走らせたPCの名前
    finished_at = Column(DateTime(timezone=True), nullable=True)
    message = Column(Text)
