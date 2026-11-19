from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func

from app.core.database import Base


class BankPayment(Base):
    """銀行（楽天銀行）からの卸への支払い。

    請求書が残っていない仕入がある（再発行もできない）。最終的には
    実際にお金が出た記録で仕入を合わせるため、卸への出金だけを持つ。
    明細のほかの行（個人への振込・売上の入金など）は保存しない。

    key は「日付|金額|取引先|同じ日の何件目か」。同じCSVを何度入れても増えない。
    """
    __tablename__ = "bank_payments"

    key = Column(String, primary_key=True)
    paid_on = Column(String, index=True)        # "2026-09-01"
    ym = Column(String, index=True)
    supplier = Column(String, index=True)       # 卸の仕入と同じ名前
    amount = Column(Float)                      # 出金額（税込・円）
    bank = Column(String, default="rakuten")

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BankStatement(Base):
    """取り込んだ明細の期間。その月の出金が全部そろっているかの判定に使う。

    卸への出金だけを持つと、出金の無い日が明細の外なのか、ただ払って
    いないだけなのか区別がつかないので、CSVの最初と最後の日付を残す。
    """
    __tablename__ = "bank_statements"

    key = Column(String, primary_key=True)      # "rakuten|2026-06-01|2026-11-19"
    bank = Column(String, default="rakuten")
    from_day = Column(String)
    to_day = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
