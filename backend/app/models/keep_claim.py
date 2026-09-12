from datetime import date, datetime, timedelta, timezone

from sqlalchemy import (Column, Integer, String, Text, Date, DateTime,
                        Boolean)
from sqlalchemy.sql import func

from app.core.database import Base


class KeepClaim(Base):
    """商品キープ（被り防止）。

    2人で同じ商品を見ているので、先に見つけたほうが独占権を取る。
    これまでスプレッドシートでやっていたものを移した。

    ルール（相手と決めたもの）:
      1. 早い者勝ち。記入が早い人が独占権を取る
      2. 親ASIN単位。色違い・サイズ違いも丸ごと独占（相乗りNG）
      3. キープ枠は1人7個まで。代行会社から発送された時点で枠が空く
      4. 60日ルール。記入から60日以内に発送できなければ独占権は消滅
    """

    __tablename__ = "keep_claims"

    id = Column(Integer, primary_key=True)

    # 誰が取ったか。スプレッドシートでは C / Y の1文字だった
    owner = Column(String, index=True, nullable=False)

    url = Column(String, nullable=False)
    # 親ASIN。被りの判定はこれで行う（色違いも同じ商品として扱う）
    asin = Column(String, index=True)
    title = Column(String)
    image_url = Column(String)

    # keep / shipped / expired / released
    status = Column(String, default="keep", nullable=False, index=True)

    # 記入日時。早い者勝ちの根拠なので、あとから変えない
    claimed_at = Column(DateTime(timezone=True), server_default=func.now())
    # 発送された日。ここで枠が空く
    shipped_at = Column(Date, nullable=True)

    # 仕入れ先（1688など）。見つけたら控えておく
    supplier_url = Column(Text)
    memo = Column(Text)

    # 採用してリサーチシートへ送ったか。送った先の枠のid
    research_id = Column(String, nullable=True)
    adopted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# 60日以内に発送できなければ独占権は消滅する
KEEP_LIMIT_DAYS = 60


def days_elapsed(row: KeepClaim, today: date = None) -> int:
    """キープしてから何日たったか。発送済みなら発送までの日数。"""
    today = today or date.today()
    if not row.claimed_at:
        return 0
    start = row.claimed_at.date() if hasattr(row.claimed_at, "date") \
        else row.claimed_at
    end = row.shipped_at if row.shipped_at else today
    return max(0, (end - start).days)


def days_left(row: KeepClaim, today: date = None) -> int:
    """あと何日で独占権が消えるか。発送済みなら関係ないので0。"""
    if row.status != "keep":
        return 0
    return KEEP_LIMIT_DAYS - days_elapsed(row, today)
