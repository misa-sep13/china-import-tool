from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func

from app.core.database import Base


class RepackInstruction(Base):
    """代行会社への再梱包指示。リサーチ1件につき1つ。

    リサーチシートの中に持たせていたが、シートは1枚のJSONを丸ごと
    読み書きするため、指示を1文字直すだけでシート全体の保存が走る。
    指示だけを見たい代行会社の画面からも、シートを全部読むことになる。

    指示は採用したあとの作業の話で、リサーチそのものとは別物なので、
    テーブルを分けて単独で持つ。
    """
    __tablename__ = "repack_instructions"

    id = Column(Integer, primary_key=True, index=True)
    # シート側のリサーチID。シートはサーバーに1枚しかないので、これで一意
    research_id = Column(String, index=True, unique=True)

    note = Column(Text)                  # 指示の本文
    box_note = Column(Text)              # 外箱・入数の指示（別に書きたいことが多い）

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
