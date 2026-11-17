from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func

from app.core.database import Base


class TaotaroTransaction(Base):
    """タオタロウの入出金明細。

    試算表はいまデポジット（チャージ）した日で仕入を計上している。
    チャージは前払金の入金であって、その月に仕入れたものではないので、
    月ごとの利益の見え方が大きく振れる。

    その月に実際に発生したものだけを拾えるよう、明細を1行ずつ持っておく。
    明細は注文（oid）・配送依頼（sid）に1対1で紐づくので、あとから
    SKUや便へ按分できる。

    id はタオタロウ側の明細IDをそのまま使う。取り込みを何度やっても
    同じ行が増えないようにするため。
    """
    __tablename__ = "taotaro_transactions"

    id = Column(Integer, primary_key=True)            # タオタロウの明細ID
    occurred_at = Column(DateTime(timezone=True), index=True)
    ym = Column(String, index=True)                   # "2026-11"。月次集計を速くするため

    kind = Column(String)                             # debit=引落 / credit=入金
    action = Column(String, index=True)               # タオタロウの区分名（商品購入など）
    # 会計上の扱い。action から決める（_category）
    category = Column(String, index=True)

    money = Column(Float)                             # 元。引落はマイナス
    balance_after = Column(Float)
    exchange_rate = Column(Float)
    exchange_money = Column(Float)                    # 円換算（タオタロウが出した値）

    oid = Column(String, index=True)                  # 注文ID
    sid = Column(String, index=True)                  # 配送依頼ID（便）
    sn = Column(String)

    product_total_price = Column(Float)
    service_charge = Column(Float)
    remark = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
