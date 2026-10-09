from sqlalchemy import (Column, Integer, String, Text, Boolean, DateTime,
                        LargeBinary)
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


class ImageRequestPhoto(Base):
    """画像依頼に添える参考画像。

    「この色で」「この向きで」を言葉で説明するより、現物の写真を1枚
    見せたほうが早い。外注さんは共有URLでこの一覧を見るので、
    そこから見えるところに置く。

    保存するときに小さくしている（表示用は長辺1400px・一覧の縮小は
    長辺240px）。元のままだと通信量がすぐ膨らむため。
    """
    __tablename__ = "image_request_photos"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, index=True, nullable=False)
    name = Column(String)                      # 元のファイル名
    content_type = Column(String, default="image/jpeg")
    data = Column(LargeBinary)                 # 表示用
    thumb = Column(LargeBinary)                # 一覧に並べる縮小
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ImageRequestFile(Base):
    """外注さんから届いた納品データ（画像のZIPなど）の一時置き場。

    チャットワークで受け取ったファイルを、依頼の行に紐づけて置いておく。
    商品登録に使ったら要らなくなるので、進み具合を「完了」にした時点で
    中身を消す。ずっと置くとすぐ容量を食う（10MBのZIPが依頼のぶんだけ増える）。
    """
    __tablename__ = "image_request_files"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, index=True, nullable=False)
    name = Column(String)
    content_type = Column(String, default="application/octet-stream")
    size = Column(Integer, default=0)
    data = Column(LargeBinary)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
