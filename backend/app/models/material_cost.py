from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class MaterialCost(Base):
    """発送用梱包資材（宅配袋・ダンボール等）の仕入記録。

    商品原価(cost_jpy)には計上せず、販売費として月次で集計するために別管理する。
    is_component（商品に付属して一緒に売るもの＝売上原価）とは扱いが異なる。

    楽天・Amazonどちらの仕入処理からも書き込む。集計は invoice_date の年月で行う
    （仕入れた月に計上する方式）。
    """
    __tablename__ = "material_costs"

    id = Column(Integer, primary_key=True, index=True)
    invoice_no = Column(String, index=True)        # インボイス番号（便の識別用）
    invoice_date = Column(String, index=True)      # 仕入日 YYYY-MM-DD。月次集計のキー
    source = Column(String, index=True)            # "rakuten" / "amazon"（どちらの画面から登録したか）
    sku = Column(String, index=True)
    name = Column(String)
    qty = Column(Integer, default=0)
    unit_price_cny = Column(Float, default=0)
    total_price_cny = Column(Float, default=0)     # 商品代（元）
    freight_alloc_cny = Column(Float, default=0)   # 按分された送料（元）
    tax_alloc_jpy = Column(Float, default=0)       # 按分された輸入税（円）
    total_cost_jpy = Column(Float, default=0)      # 資材費合計（円）= (商品代+送料)×為替+税
    exchange_rate = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
