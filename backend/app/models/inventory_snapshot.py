from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class InventorySnapshot(Base):
    """月末（期末）在庫のスナップショット。

    在庫数は現在値しか保持していないため、決算・月次で必要な期末在庫金額を
    後から出せるように、確定時点の SKU 別在庫数と原価を保存する。
    """
    __tablename__ = "inventory_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    period = Column(String, index=True)        # "2026-06"（対象月）
    platform = Column(String, index=True)      # rakuten / amazon
    category = Column(String, index=True)      # china（中国輸入） / manufacturer（日本メーカー品）
    sku = Column(String, index=True)
    name = Column(String)
    supplier = Column(String)
    stock = Column(Integer, default=0)         # 実在庫
    cost_jpy = Column(Float, default=0)        # 1個あたり原価（円）
    amount = Column(Float, default=0)          # stock * cost_jpy
    note = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
