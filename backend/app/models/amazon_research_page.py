from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class AmazonResearchPage(Base):
    """競合1商品ぶんの調査メモ（商品仕様・レビュー・キーワード・画像の文字）。

    もともとはブラウザの localStorage にだけ置いていた。シート本体のJSONに
    混ぜると同期が重くなるためだが、そのせいでPCを変えると消え、
    「取り込み済みなのに商品仕様が空」という状態が起きていた。
    商品登録の画面からも材料として使いたいので、別テーブルに切り出す。

    row_id はシート側の候補商品の行ID（"idumuw2rk5mtmjz266" のような文字列）。
    レビューは1件で数千文字になるので、シートとは分けて必要なときだけ読む。
    """
    __tablename__ = "amazon_research_pages"

    id        = Column(Integer, primary_key=True, index=True)
    workspace = Column(String, index=True, default="default")
    row_id    = Column(String, index=True)

    spec     = Column(Text)      # 商品仕様（SP-APIの取り込み、または商品ページの貼り付け）
    reviews  = Column(Text)      # レビュー本文
    keywords = Column(Text)      # 競合が使っているキーワード
    imgtext  = Column(Text)      # 商品画像に書かれている文字
    analysis = Column(Text)      # 分析の結果（ChatGPTなどの回答を貼る）

    analysis_at = Column(DateTime(timezone=True), nullable=True)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(),
                         onupdate=func.now())
