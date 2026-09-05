from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class AmazonListing(Base):
    """Amazonへ出す1商品ぶんの出品内容。

    元になるのは競合リサーチシートで、そこには商品タイトル・検索キーワード・
    要点の5行・サイズ・重量まで揃っている。ただしシートはHTML1枚をまるごと
    JSONで持つ作りなので、出品の途中経過（発番したJAN・Amazonが返した
    エラー・商品タイプ）を書き戻す先には向かない。そこで出品の分だけ
    ここに切り出し、シートからは取り込む形にしている。

    research_id はシート側のリサーチID（"idtu05xf4nmtmjz266" のような文字列）。
    """
    __tablename__ = "amazon_listings"

    id = Column(Integer, primary_key=True, index=True)
    research_id = Column(String, index=True, unique=True)
    research_title = Column(Text)          # 一覧に出す名前。シートの見出し

    # ---- 出品の中身。取り込んだあと、この画面で直せる ----
    title       = Column(Text)             # 親の商品タイトル
    keywords    = Column(Text)             # 検索キーワード（generic_keyword）
    bullets     = Column(Text)             # 要点。JSON配列（5行まで）
    description = Column(Text)             # 商品説明
    brand       = Column(String)
    price       = Column(Integer)

    # ---- 寸法と重量。出品に要るが、これまで送れていなかった ----
    len_a  = Column(Float)                 # 長辺cm
    len_b  = Column(Float)                 # 中辺cm
    len_c  = Column(Float)                 # 短辺cm
    weight = Column(Float)                 # 実重量kg

    # ---- 商品タイプ。競合ASINから引く ----
    rival_asin   = Column(String)
    product_type = Column(String)
    attrs        = Column(Text)            # 商品タイプごとの必須項目。JSON

    # ---- 親子 ----
    # Amazonは単品でも親子で作るのが推奨とされているので、親は常に持つ。
    #   単品          a05（親） / a05_1（子）
    #   バリエーション a06（親） / a06_black・a06_s（子）
    parent_sku = Column(String, index=True)
    variation_theme = Column(String)       # COLOR / SIZE / SIZE_COLOR など
    axis1_label = Column(String)           # 画面に出す軸の名前（例: カラー）
    axis2_label = Column(String)

    # ---- 判断根拠。シートから写して一覧に出す（出品には送らない）----
    monthly_sales = Column(Integer)
    review_count  = Column(Integer)
    review_rate   = Column(Float)
    profit_rate   = Column(Float)
    rival_image   = Column(Text)

    status      = Column(String, default="draft", index=True)  # draft/ready/submitted/live/failed
    synced_at   = Column(DateTime(timezone=True), nullable=True)  # 最後にシートから取り込んだ時刻
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AmazonListingChild(Base):
    """出品するSKU1件。単品なら1件だけ、バリエーションなら子の数だけ並ぶ。

    JANはSKUごとに要る（同じ番号を2商品に使うと同一商品として扱われる）。
    Amazonが返したエラーもSKUごとに違うので、ここに持たせる。
    """
    __tablename__ = "amazon_listing_children"

    id         = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, index=True)
    sort_order = Column(Integer, default=0)

    sku   = Column(String, index=True)     # 出品用SKU
    jan   = Column(String)                 # 発番したJAN
    title = Column(Text)                   # 子の商品タイトル。単品なら親と同じ
    axis1 = Column(String)                 # 軸の値（例: ブラック）
    axis2 = Column(String)
    price = Column(Integer)                # 子ごとに変える場合。空なら親の値

    status       = Column(String, default="draft")   # draft/submitted/live/failed
    asin         = Column(String)
    error        = Column(Text)
    submitted_at = Column(DateTime(timezone=True), nullable=True)


class AmazonListingImage(Base):
    """出品に使う商品画像。

    Amazonは画像を「公開URLで取りに行く」方式なので、ファイルそのものを
    渡せない。ここに預かって、トークン付きの公開URLで読ませる。
    child_id が入っていればその子だけの画像（カラー違いなど）。
    """
    __tablename__ = "amazon_listing_images"

    id         = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, index=True)
    child_id   = Column(Integer, index=True, nullable=True)
    file_name  = Column(String)
    mime       = Column(String)
    size       = Column(Integer)
    data       = Column(Text)              # base64
    sort_order = Column(Integer, default=0)   # 0がメイン画像
    public_token = Column(String, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
