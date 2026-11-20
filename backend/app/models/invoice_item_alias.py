"""請求書の品名と、卸商品（＝楽天SKU）の結び付け。

請求書は「DENT. チェックアップ ジェル ｸﾞﾚｰﾌﾟ 60g」、商品マスタは
「チェックアップジェルグレープ（s02-1-grape）」のように書き方が違う。
空白と記号を落とした部分一致では、ほとんどの品目が当たらなかった。

結び付けが無いと、仕入を商品ごとに割り当てられない。割り当てられないと
「期首 ＋ 仕入 − 消費 ＝ 期末」の検算ができず、棚卸差異がどの商品で
出ているのか分からないままになる。

一度選べば覚える。次に同じ品名が来たら自動で当たる。
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from app.core.database import Base


class InvoiceItemAlias(Base):
    __tablename__ = "invoice_item_aliases"

    id = Column(Integer, primary_key=True, index=True)
    # 品名を揃えた形（空白・記号を落として大文字に）。これで引く
    name_norm = Column(String, index=True, unique=True)
    # 画面に出す用の、請求書に書いてあったままの品名
    name_raw = Column(String)
    wholesale_item_id = Column(Integer, index=True)
    # 結び付けた時点の楽天SKU。卸商品の紐付けが変わっても、
    # 過去の割り当てが何を指していたかは残しておきたい
    sku = Column(String, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
