from sqlalchemy import Column, String, Float, DateTime
from sqlalchemy.sql import func

from app.core.database import Base


class TaotaroOrderChannel(Base):
    """タオタロウの注文ごとの販路（Amazon向けか楽天向けか）。

    タオタロウの入出金明細は注文（oid）ごとに引き落とされる。月次の仕入を
    楽天とAmazonに分けるため、注文ごとにどちら向けかを覚えておく。
    見分け方は配送依頼の画面と同じ（FBAの印・ASIN/FNSKU・楽天マスタ）。
    見分けがつかない注文は楽天にする（2026-11-20 ユーザー決定）。
    """
    __tablename__ = "taotaro_order_channels"

    oid = Column(String, primary_key=True)
    sid = Column(String, index=True)            # 入った配送依頼（便）
    sku = Column(String)
    channel = Column(String, index=True)        # amazon / rakuten
    how = Column(String)                        # 判定の根拠（amazon_mark / master / unknown など）
    amount_cny = Column(Float)                  # 注文の金額（便の費用を配る割合に使う）
    ordered_at = Column(String)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
