from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class RmsPushFailure(Base):
    """RMSへの在庫反映(PUT)に失敗したSKUを記録する。
    バックグラウンド実行だと失敗が握りつぶされるため、必ずここへ残して補正pushできるようにする。
    """
    __tablename__ = "rms_push_failures"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, index=True, nullable=True)   # 在庫反映ログと紐付け
    source = Column(String, index=True)                    # shipment_order / manufacturer_receive / stock_edit / bulk_update
    source_label = Column(String, nullable=True)           # 配送依頼 / メーカー入荷 など
    sku = Column(String, index=True)                       # = RMSのvariant_id
    manage_number = Column(String)                         # RMSの商品管理番号
    quantity = Column(Integer, default=0)                  # 反映しようとした在庫数
    http_status = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)
    attempts = Column(Integer, default=0)
    resolved = Column(Boolean, default=False, index=True)  # 補正push成功 or 後続pushで解消
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
