from sqlalchemy import (Column, Integer, String, Text, Boolean, DateTime,
                        ForeignKey)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class WorkStatus(Base):
    """商品1つぶんの「いまどうなっているか」。

    チャットワークだけでやり取りしていると、話が流れて
    「これは誰の番なのか」「答えたか答えていないか」が分からなくなる。
    外注さんから、状態を一覧で見たいという声が出たので作った。

    1行＝商品（SKU）1つ。Amazonも楽天も同じ並びに出す。
    チャットワークは事務連絡と詳しい相談に使い、こちらは
    「いま誰の番か」と「答えの出ていない質問」を残す場所にする。
    """
    __tablename__ = "work_statuses"

    id = Column(Integer, primary_key=True, index=True)

    # amazon / rakuten。どちらの商品かで見る場所が変わるので分けて持つ
    channel = Column(String, default="amazon", index=True)
    # リサーチシート側のID。同じ枠から二重に作らないための照合に使う
    research_id = Column(String, index=True)

    sku = Column(String, index=True)
    name = Column(String)
    memo = Column(Text)                       # 一言メモ（申し送り）

    # いまの工程。リサーチシートの並びに合わせてある
    stage = Column(String, default="adopted", index=True)
    # 誰の番か。misa / yuna / none（待ちなし＝完了や保留）
    ball = Column(String, default="yuna", index=True)

    sort_order = Column(Integer, index=True, nullable=True)
    done_at = Column(DateTime(timezone=True), nullable=True)
    is_deleted = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())

    notes = relationship("WorkNote", back_populates="work",
                         cascade="all, delete-orphan")


class WorkNote(Base):
    """商品への質問と、その答え。

    質問と答えを別の行にすると、どの答えがどの質問のものか
    分からなくなる。1行に質問と答えを両方持たせ、答えが空の間は
    「未回答」として一覧の先頭に出す。
    """
    __tablename__ = "work_notes"

    id = Column(Integer, primary_key=True, index=True)
    work_id = Column(Integer, ForeignKey("work_statuses.id"), index=True)

    who = Column(String)                      # 聞いた人（misa / yuna）
    body = Column(Text)                       # 質問・連絡
    answer = Column(Text)                     # 答え。空なら未回答
    answered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    work = relationship("WorkStatus", back_populates="notes")
