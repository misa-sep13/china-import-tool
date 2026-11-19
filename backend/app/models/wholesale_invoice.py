"""卸の請求書から読み取った明細（メーカー品の仕入）。

発注どおりに届くとは限らない。9/4の請求書はバナナ480本なのに発注は
360本で、ピーチ60本は発注自体が無かった。実際に請求された額が仕入なので、
請求書を正にする。

請求書は納品のたびに発行されているので、請求日をそのまま発生日に使える。

請求書のDL漏れもあるため、請求書が無い月は入荷履歴で埋める。
どちらで出したかは画面に出す。
"""
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func

from app.core.database import Base


class WholesaleInvoiceLine(Base):
    __tablename__ = "wholesale_invoice_lines"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, index=True)      # 原本（import_permits.id）
    supplier = Column(String, index=True)          # マレフィオーレ など
    # 請求No。同じ番号で「修正版」が後から来ることがあるので、
    # 取り込み直すときは同じ番号の行を入れ替える
    doc_no = Column(String, index=True)
    issued = Column(String, index=True)            # 請求日 YYYY-MM-DD
    ym = Column(String, index=True)                # 計上月＝請求日の月

    name = Column(String)                          # 品名（請求書の書き方のまま）
    qty = Column(Integer, default=0)
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)              # 税抜
    note = Column(String)                          # 摘要（「追加分」など）

    created_at = Column(DateTime(timezone=True), server_default=func.now())
