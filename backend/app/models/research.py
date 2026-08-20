from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ResearchTarget(Base):
    """リサーチ対象として登録したジャンルID・検索キーワード・ショップ。
    ローカルバッチがこれを読んで週次で楽天APIを叩く。"""
    __tablename__ = "research_targets"

    id          = Column(Integer, primary_key=True)
    type        = Column(String, nullable=False)   # "keyword" | "genre" | "shop"
    value       = Column(String, nullable=False)    # キーワード文字列 / ジャンルID / shopCode
    label       = Column(String)                    # 画面表示用の名前（未指定ならvalueを表示）
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, server_default=func.now())


class ResearchCandidate(Base):
    """バッチが直近に取得した候補商品。対象ごとに毎回洗い替えするが、
    洗い替える前のレビュー数を prev_* に引き継ぐ。
    楽天で検索すれば分かる情報（価格・レビュー数）だけでは意味がなく、
    「前回から何件レビューが増えたか」＝伸びが判断材料になるため。"""
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
    # 商品URLから作る "ショップ名/商品コード"。Nintのデータと突き合わせるためのキー
    url_key           = Column(String, index=True, nullable=True)
    # 前回バッチ時点の値。差分（レビュー増加数）を出すために引き継ぐ
    prev_review_count = Column(Integer, nullable=True)
    prev_fetched_at   = Column(DateTime, nullable=True)


class NintSales(Base):
    """NintのCSVから取り込んだ月別の売上・販売個数。

    楽天APIは販売数を一切返さないため、売上はNintの書き出し機能で得た値を使う
    （Nintは規約でスクレイピングを禁じているので、画面からのDL＝提供機能を使う）。
    月別に持つのは、直近何ヶ月かの伸びを後から自由に計算できるようにするため。
    """
    __tablename__ = "nint_sales"

    id           = Column(Integer, primary_key=True)
    # "luckyhill/nz-48ss" の形。楽天APIのitemCodeとは体系が違うので、
    # 商品URLから作ったこのキーで候補・ウォッチリストと突き合わせる
    url_key      = Column(String, index=True)
    ym           = Column(String, index=True)   # "202604"
    sales_amount = Column(Integer)              # 売上指数（円）
    units        = Column(Integer)              # 販売個数
    item_name    = Column(String)
    shop_name    = Column(String)
    item_url     = Column(String)
    image_url    = Column(String)
    updated_at   = Column(DateTime, server_default=func.now())


class RakutenGenre(Base):
    """楽天のジャンル階層。ジャンルIDを手で調べるのは現実的でないため、
    画面から選べるようにローカルバッチで取り込んで保持する
    （RenderからはIP制限で楽天APIを呼べないので、DBに持っておく必要がある）。"""
    __tablename__ = "rakuten_genres"

    genre_id    = Column(Integer, primary_key=True)
    name        = Column(String, index=True)
    level       = Column(Integer, index=True)
    parent_id   = Column(Integer, index=True, nullable=True)
    # 「レディースファッション > トップス > Tシャツ」のような表示用の道筋。
    # 階層を辿らずに検索結果へ文脈を出せるようにするため持たせる
    path        = Column(String)
    updated_at  = Column(DateTime, server_default=func.now())


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
    url_key        = Column(String, index=True, nullable=True)  # Nintデータとの照合用
    monthly_sales  = Column(Integer, nullable=True)  # 手動入力（Nint取り込み分とは別に残す）
    folder         = Column(String, nullable=True)   # 整理用のフォルダ名
    memo           = Column(Text, nullable=True)
    picked_at      = Column(DateTime, server_default=func.now())
