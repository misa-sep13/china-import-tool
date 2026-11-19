"""請求書から読み取った明細。

月次管理表の販管費は、率からの見込みではなく請求書の実額で出したい。
読み取った1行ずつをここに置き、月次はここを合算する。

いちばん大事なのは ym（計上月）が請求書の発行月ではなく
「精算対象期間」から決まること。楽天は3月分のシステム利用料が
6月発行の請求書に載り、品目によって遅れ方も違う。
発行月で計上すると、まるごとずれる。
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from app.core.database import Base


class BillingLine(Base):
    __tablename__ = "billing_lines"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, index=True)        # rakuten_rms / yamato
    document_id = Column(Integer, index=True)  # 原本（import_permits.id）
    # 店舗別内訳書No。楽天は同じ内容が翌月に「再掲」で出るので、
    # 枝番（-31/-32）を落とした番号で同じものと見なし、二重に数えない
    doc_no = Column(String, index=True)
    shop_id = Column(String, index=True)
    shop = Column(String)

    bucket = Column(String, index=True)        # ad/promo/payment_fee/system_fee/rent/shipping/other
    name = Column(String)                      # 品目
    period_start = Column(String)
    period_end = Column(String)
    ym = Column(String, index=True)            # 計上月＝精算対象期間の月

    amount = Column(Integer, default=0)        # 税抜
    created_at = Column(DateTime(timezone=True), server_default=func.now())
