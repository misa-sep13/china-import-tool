from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class MaterialOrder(Base):
    """資材（宅配袋・OPP袋など）とレビュープレゼントの発注記録。

    商品の発注（rakuten_order_history）とは別の表にしてある。資材と販促品は
    売り物ではなく、発注推奨にも在庫一覧にも出てこない。同じ表に入れると
    商品の発注一覧に紛れ込んで、どれが売り物の発注か分からなくなる。

    在庫（rakuten_products.stock）は入荷を記録したときに足す。発注しただけでは
    増やさない（届く前に在庫があることにすると、梱包の手配を誤る）。
    """
    __tablename__ = "material_orders"

    id         = Column(Integer, primary_key=True)
    sku        = Column(String, index=True)      # rakuten_products.sku
    name       = Column(String)                  # 発注した時点の名前を残す
    qty        = Column(Integer, default=0)      # 発注数（袋なら「100枚入り」の個数）
    ordered_at = Column(Date, index=True)        # 発注日
    # 届いた日。入れると在庫に足す。未入荷は null
    received_at = Column(Date, nullable=True)
    unit_price_cny = Column(Float, nullable=True)  # 発注時の単価（元）。分かれば残す
    memo       = Column(Text)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
