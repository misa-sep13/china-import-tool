from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ImageRequest(Base):
    """画像作成の依頼1件。

    リサーチシートから指示書をチャットワークへ送ると1件できる。
    送ったあとは「誰に何を頼んでいて、いまどうなっているか」を追える場所が
    どこにも無く、チャットの履歴をさかのぼるしかなかった。

    楽天や、シートを通さない依頼も手で足せるようにしてある。
    外注さんには合言葉つきのURLでこの一覧だけを見せ、進み具合を
    自分で変えてもらう（毎回こちらへ連絡してもらわなくて済む）。
    """
    __tablename__ = "image_requests"

    id = Column(Integer, primary_key=True, index=True)

    # どこから来た依頼か。amazon（リサーチシート）／ rakuten ／ manual
    source = Column(String, default="amazon", index=True)
    # シート側のリサーチID。同じ枠から2回送ったときに見分ける用
    research_id = Column(String, index=True)

    sku = Column(String, index=True)          # 親SKU
    name = Column(String)                     # 商品名（短縮でよい）
    doc_name = Column(String)                 # 送ったWordのファイル名
    detail = Column(Text)                     # 依頼の中身・伝えたいこと
    ref_url = Column(Text)                    # 競合のAmazon商品ページ
    # 仕入元（1688）のページ。デザイナーが画像素材と実物の作りを見るのに要る
    main_url = Column(Text)

    room_id = Column(String)                  # チャットワークのルーム
    room_name = Column(String)
    sent_at = Column(DateTime(timezone=True), nullable=True)  # 送った時刻

    # requested=依頼済 / working=作業中 / review=確認待ち / done=完了
    status = Column(String, default="requested", index=True)
    assignee = Column(String)                 # 担当（外注さんの名前）
    due_date = Column(String)                 # 希望納期。日付は文字で持つ
    reply = Column(Text)                      # 外注さんからの連絡
    deliverable_url = Column(Text)            # 納品先（ギガファイル等）

    # 並び順。画面で上下に動かせるようにするためのもの。
    # 新しく足したものが下に来るよう、作った順（id）を初期値にする
    sort_order = Column(Integer, index=True, nullable=True)

    done_at = Column(DateTime(timezone=True), nullable=True)
    is_deleted = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
