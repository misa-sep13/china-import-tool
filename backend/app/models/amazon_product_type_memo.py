from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class AmazonProductTypeMemo(Base):
    """商品タイプ（カテゴリ）ごとに覚えておく入力値。

    Amazonの商品タイプは数百あり、必須項目を先に網羅するのは現実的でない。
    そこで「検証を押す → 足りない項目が出る → 入れる → 覚える」を繰り返し、
    同じカテゴリの2件目からは入力が要らないようにする。

    values は {属性名: 値}。商品ごとに変わるもの（素材・カラーなど）は
    覚えさせず、そのカテゴリで毎回同じになるものだけ入れる想定。
    どの項目を覚えるかは画面で選べる。

    asked は、そのカテゴリでAmazonから「足りない」と言われた項目の一覧。
    次に同じカテゴリを出すとき、先回りして入力欄に出すために貯める。
    """
    __tablename__ = "amazon_product_type_memos"

    id           = Column(Integer, primary_key=True, index=True)
    product_type = Column(String, unique=True, index=True)
    display_name = Column(String)

    values = Column(Text)      # 覚えている入力値（JSON）
    asked  = Column(Text)      # Amazonに聞かれた項目の一覧（JSON配列）

    used_count = Column(Integer, default=0)   # このカテゴリで出品した回数
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
