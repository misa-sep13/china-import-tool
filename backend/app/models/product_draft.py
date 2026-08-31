from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ProductDraft(Base):
    """リサーチで「採用」した商品の登録前ドラフト。

    これまでスプレッドシートで管理していた「SKU・楽天商品名・商品説明・
    1688の情報・備考」をそのままツール内に持たせる。楽天へ登録するまでの
    作業台であり、RMSへ登録したあとも記録として残す（status=registered）。

    参考にしたライバル商品の情報（商品名・説明文）も一緒に持つ。
    カラー展開などが自社と完全に同じとは限らないため、ライバルの情報は
    「そのまま使う値」ではなく「文章を作るときの材料」として保持する。
    """
    __tablename__ = "product_drafts"

    id            = Column(Integer, primary_key=True)
    sku           = Column(String, index=True)
    # draft=作成中 / ready=登録待ち / registered=RMS登録済み
    status        = Column(String, default="draft", index=True)

    # ---- 自社の商品情報（楽天へ登録する値） ----
    rakuten_title  = Column(Text)      # 楽天商品名
    catchcopy      = Column(Text)      # キャッチコピー（tagline）
    description_pc = Column(Text)      # 商品説明（PC）
    description_sp = Column(Text)      # 商品説明（スマホ）
    genre_id       = Column(String)    # 楽天ジャンルID
    price          = Column(Integer)   # 販売価格（円）
    assignee       = Column(String)    # 説明担当者

    # ---- 仕入れ側（1688 / アリババ） ----
    supplier_url       = Column(Text)
    supplier_name_cn   = Column(Text)   # 中国語商品名
    supplier_spec      = Column(Text)   # 色・サイズ等
    supplier_price_cny = Column(Float)
    supplier_note      = Column(Text)   # 商品備考（発注時の指示など）

    # ---- 参考にしたライバル商品 ----
    rival_item_code = Column(String)
    rival_title     = Column(Text)
    rival_caption   = Column(Text)   # ライバルの商品説明（自動取得）
    rival_url       = Column(Text)
    rival_price     = Column(Integer)
    rival_image_url = Column(Text)
    rival_shop_name = Column(String)

    ref_image_urls = Column(Text)   # 参考画像URL（JSON配列）
    memo           = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProductDraftGeneration(Base):
    """タイトル・説明文の生成履歴。

    生成をやり直すたびに前の案が消えると比較できないため、毎回追記する。
    どんな材料（プロンプト）で作ったかも残し、あとから再現・検証できるようにする。
    """
    __tablename__ = "product_draft_generations"

    id         = Column(Integer, primary_key=True)
    draft_id   = Column(Integer, index=True)
    kind       = Column(String, index=True)   # title / description / both
    prompt     = Column(Text)
    output     = Column(Text)
    model      = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
