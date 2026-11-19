"""入荷の履歴（メーカー品の仕入）。

発注1件に入荷日を1つしか持てないと、分納のときにどの月の仕入か
決められない。マレフィオーレは分納が常態で、9月に発注したものが
9月・10月・11月に分かれて届く。発注日で計上すると9月に寄りすぎ、
最後の入荷日で計上すると11月に寄りすぎる。

発生ベースで仕入を立てるには「いつ・何が・何個届いたか」が要る。
入荷のたびに1行ずつ残す。
"""
from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.core.database import Base


class WholesaleReceipt(Base):
    __tablename__ = "wholesale_receipts"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("wholesale_orders.id"), index=True)
    order_item_id = Column(Integer, ForeignKey("wholesale_order_items.id"), index=True)
    supplier_id = Column(Integer, index=True)
    supplier_name = Column(String)

    # 仕入の発生日。ここが月次の計上先になる。
    # さかのぼって作った行で日付が分からないものは空。
    # 空のままだと月に入れられないので、画面で入れてもらう
    received_date = Column(String, index=True)        # YYYY-MM-DD
    ym = Column(String, index=True)                   # YYYY-MM

    item_code = Column(String)
    name = Column(String)
    qty = Column(Integer, default=0)
    # そのときの卸単価（税抜）。マスタの単価を後で変えても過去は動かさない
    unit_price = Column(Float, default=0)
    amount = Column(Float, default=0)                 # qty × unit_price（税抜）

    # backfill … 既存の発注からさかのぼって作った行
    # receive  … 入荷処理のときに作った行
    source = Column(String, default="receive")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
