from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class ActivityLog(Base):
    """誰が・いつ・何を変更したかの記録。

    外注さんに全機能を開放する代わりに、トップページから
    「更新履歴」として一覧できるようにするための汎用ログ。
    在庫の書き換え・商品マスタの登録/更新/削除など、
    影響の大きい操作を中心に記録する（すべての操作は網羅していない）。
    """
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor = Column(String, index=True)        # owner / contractor / service
    action = Column(String, index=True)       # create / update / delete / stock_change
    entity_type = Column(String, index=True)  # rakuten_product / rakuten_stock / rakuten_order / amazon_product / welfare_item
    entity_id = Column(String, nullable=True)
    sku = Column(String, index=True, nullable=True)
    summary = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
