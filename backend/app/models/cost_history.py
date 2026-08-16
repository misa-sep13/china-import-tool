from sqlalchemy import Column, Integer, String, Float, DateTime, Index
from sqlalchemy.sql import func
from app.core.database import Base


class CostHistory(Base):
    """商品ごと・便ごとの原価の記録。

    商品マスタの cost_jpy は「最後に保存した便の原価」で上書きされるため、
    どの便でいくらだったかが残らない。同じ商品でも便によって送料が変わる
    （箱の詰め方しだい）ので、1回の値だけを見ると運に左右される。

    ここに便ごとの実績を残しておけば、後から加重平均（直近ほど重く見る）へ
    切り替えられる。逆にこれが無いと、切り替えた時点から数え直しになる。

    楽天・Amazonどちらの仕入処理からも書き込む。同じ便を再保存したときは
    (source, sku, invoice_no) で上書きする。
    """
    __tablename__ = "cost_histories"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, index=True)          # "rakuten" / "amazon"
    sku = Column(String, index=True)
    invoice_no = Column(String, index=True)      # 便の識別子
    invoice_date = Column(String, index=True)    # 仕入日 YYYY-MM-DD。新しさの判定に使う

    # その便でのこの商品の実績
    qty = Column(Integer, default=0)             # 出荷数（物理個数）
    set_size = Column(Integer, default=1)        # 何個で1セットか
    sell_units = Column(Float, default=0)        # 販売セット数 = qty / set_size。加重平均の重み
    cost_jpy = Column(Float, default=0)          # 1セットあたり原価（円）

    # 内訳（後から「なぜこの原価か」を追えるように残す）
    total_price_cny = Column(Float, default=0)
    freight_alloc_cny = Column(Float, default=0)
    tax_alloc_jpy = Column(Float, default=0)
    customs_fee_alloc_jpy = Column(Float, default=0)
    exchange_rate = Column(Float, default=0)

    # 数字の信用度。低いものを代表原価から外す判断に使う
    coverage_rate = Column(Float, default=0)     # その便のカバー率(%)
    freight_method = Column(String, default="")  # "weight" / "money"（重量按分か金額比か）

    created_at = Column(DateTime(timezone=True), server_default=func.now())


# 商品ごとの履歴を新しい順に引く／同一便の重複を潰すのに使う
Index("ix_cost_histories_lookup", CostHistory.source, CostHistory.sku, CostHistory.invoice_date)
Index("ix_cost_histories_unique", CostHistory.source, CostHistory.sku, CostHistory.invoice_no)
