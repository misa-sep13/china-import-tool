from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func

from app.core.database import Base


class TaotaroSendOrder(Base):
    """タオタロウの配送依頼（便）ごとの費用。

    入出金明細には国際運賃の行がほとんど出てこない（支払いがまとめて
    引かれるため）。便ごとの送料を月次で拾えるよう、配送依頼の詳細から
    費用の内訳をそのまま保存しておく。単位はすべて人民元。

    計上月は出荷日（いちばん古い追跡＝中国側の集荷）の月。
    """
    __tablename__ = "taotaro_send_orders"

    sid = Column(Integer, primary_key=True)          # 配送依頼ID
    sn = Column(String, index=True)                  # 配送依頼番号（＝インボイス番号）
    state = Column(Integer)
    state_label = Column(String)
    delivery_name = Column(String)
    count_weight = Column(Float)

    shipped_date = Column(String)                    # "2026-11-05"
    ym = Column(String, index=True)                  # 出荷日の月

    send_price = Column(Float)                       # 中国国内運賃
    server_fee = Column(Float)                       # 代行手数料（検品オプション込み）
    freight = Column(Float)                          # 国際送料
    customs_fee = Column(Float)                      # 通関手数料
    remote_fee = Column(Float)                       # 遠隔地配送
    total_send_fee = Column(Float)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
