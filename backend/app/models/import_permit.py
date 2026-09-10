"""輸入許可書（輸入許可通知書）の保管。

税理士へ渡す資料として原本のPDFが要るので、メールに埋もれさせず
ツールの中に残す。本文（PDF）ごと持つのは、あとから通関業者の
メールを遡って探す作業をなくすため。

同じ許可書を二度入れないよう、メールのMessage-IDと添付ファイル名の
組で見分ける。許可書自体には一意な番号（申告番号）もあるが、
読み取れないPDFもあるので、取り込み元でも判別できるようにしてある。
"""
from sqlalchemy import (Column, Integer, String, Float, DateTime, Text,
                        LargeBinary, UniqueConstraint)
from sqlalchemy.sql import func

from app.core.database import Base


class ImportPermit(Base):
    __tablename__ = "import_permits"
    __table_args__ = (
        UniqueConstraint("mail_message_id", "filename", name="uq_permit_mail"),
    )

    id = Column(Integer, primary_key=True, index=True)
    # permit=輸入許可書 / invoice=タオタロウの請求書。
    # 税理士へは両方まとめて渡すので、同じ棚に入れて種別で分ける
    kind = Column(String, index=True, default="permit")

    # 許可書から読み取った値。読めなければ空のまま（原本は残る）
    permit_no = Column(String, index=True)          # 申告番号
    permit_date = Column(String, index=True)        # 許可年月日 YYYY-MM-DD
    permit_cny = Column(Float, default=0)           # 仕入書価格（元）
    exchange_rate = Column(Float, default=0)        # 通貨レート
    total_tax = Column(Integer, default=0)          # 納税額合計（円）
    customs_duty = Column(Integer, default=0)       # 関税
    consumption_tax = Column(Integer, default=0)    # 消費税
    local_consumption_tax = Column(Integer, default=0)  # 地方消費税

    # 原本
    filename = Column(String)
    size_bytes = Column(Integer, default=0)
    pdf = Column(LargeBinary)

    # 取り込み元。手で入れたものは mail_ 系が空になる
    source = Column(String, default="mail")         # mail / upload
    mail_message_id = Column(String, index=True)
    mail_subject = Column(String)
    mail_from = Column(String)
    mail_date = Column(String)

    # Googleドライブへ送った場合の控え
    drive_file_id = Column(String)
    drive_url = Column(String)

    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
