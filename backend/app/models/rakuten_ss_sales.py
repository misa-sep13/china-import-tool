from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.core.database import Base


class RakutenSsSales(Base):
    """スーパーセール期間（3/6/9/12月 4日20時〜11日2時）のSKU別販売数を保存する。

    楽天受注APIは63日前までしか遡れないため、SS終了後にこのテーブルへ保存しておけば
    63日を過ぎても過去SSの実績が残り続ける（蓄積）。
    """
    __tablename__ = "rakuten_ss_sales"
    __table_args__ = (UniqueConstraint("sku", "ss_period", name="uq_ss_sku_period"),)

    id         = Column(Integer, primary_key=True)
    sku        = Column(String, index=True)              # 商品管理番号 または 楽天SKU管理番号
    ss_period  = Column(String, index=True)              # SS期間キー "2026-06" 形式（開催月）
    qty        = Column(Integer, default=0)              # その期間に売れた数
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
