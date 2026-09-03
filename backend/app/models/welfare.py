from sqlalchemy import Boolean, Column, Integer, Float, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class WelfareInventoryItem(Base):
    __tablename__ = "welfare_inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("rakuten_products.id"), nullable=True, index=True)
    sku = Column(String, index=True)
    name_jp = Column(String)
    name_cn = Column(Text)
    supplier_spec = Column(String)
    buy_url = Column(Text)
    image_data_url = Column(Text)
    unit_per_set = Column(Integer, default=1)
    total_received_units = Column(Integer, default=0)
    total_received_qty = Column(Integer, default=0)
    withdrawn_qty = Column(Integer, default=0)
    remaining_qty = Column(Integer, default=0)
    instruction = Column(Text)
    note = Column(Text)
    last_received_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WelfareInventoryMovement(Base):
    __tablename__ = "welfare_inventory_movements"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("welfare_inventory_items.id"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("rakuten_products.id"), nullable=True, index=True)
    sku = Column(String, index=True)
    movement_type = Column(String, index=True)  # import / withdraw / adjust
    source_file = Column(String)
    source_sheet = Column(String)
    source_order_no = Column(String)
    # 配送依頼No（便の番号）。同じ発注を2便に分けて送ることがあるため、
    # 「どの便で届いたか」が分からないと分納の2便目を重複と誤判定する
    shipment_no = Column(String, index=True)
    name_cn = Column(Text)
    supplier_spec = Column(String)
    buy_url = Column(Text)
    units = Column(Integer, default=0)
    qty = Column(Integer, default=0)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WelfareWorkInstruction(Base):
    __tablename__ = "welfare_work_instructions"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("rakuten_products.id"), nullable=True, index=True)
    sku = Column(String, index=True)
    order_date = Column(String, index=True)
    source_file = Column(String)
    source_sheet = Column(String)
    source_order_no = Column(String, index=True)
    shipment_no = Column(String, index=True)   # 配送依頼No。重複判定に使う
    name_jp = Column(String)
    source_product_name = Column(Text)
    color = Column(String)
    size = Column(String)
    supplier_spec = Column(String)
    buy_url = Column(Text)
    image_data_url = Column(Text)
    unit_price = Column(String)
    units = Column(Integer, default=0)
    unit_per_set = Column(Integer, default=1)
    qty = Column(Integer, default=0)
    instruction = Column(Text)
    remaining_units = Column(Integer, default=0)
    remaining_qty = Column(Integer, default=0)
    note = Column(Text)
    # 就労支援在庫へ反映済みか。取込時点では反映せず、荷受け処理（指示・残の確定）後に
    # 「就労支援在庫に反映」で残の数量だけを在庫化する。二重計上防止用。
    is_reflected = Column(Boolean, default=False, index=True)
    reflected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WelfarePackingTask(Base):
    """再梱包の作業マスタ。

    「この商品はこう梱包する」を1件1作業として持つ。商品マスタには持たせない。
    再梱包は販売商品と1対1ではなく、同じ商品でも入数違いで作業が分かれたり
    （キッチンタオル4色/同色）、逆にマスタに無い作業もある（レビュー特典など）
    ため、就労支援の中で独立して管理する。

    sku は楽天商品マスタへの参考リンク。空でもよい。
    """
    __tablename__ = "welfare_packing_tasks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)          # 作業名（就労支援さんが見る名前）
    sku = Column(String, index=True)           # 楽天の商品コード。紐づけない場合は空
    set_qty = Column(Integer)                  # 1セットに入れる数
    unit_price = Column(Float, default=0)      # 1セットあたりの報酬（円）
    packing_material = Column(Text)            # 梱包材の種類
    packing_method = Column(Text)              # 梱包方法（作業内容）
    note = Column(Text)
    sort_order = Column(Integer, default=0)
    # "seed"=一括取り込みで作った / "manual"=画面から手で足した。
    # 取り込みボタンで一覧を整理するとき、手で足した作業まで消さないために使う
    source = Column(String, default="manual", index=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WelfarePackingOrder(Base):
    """就労支援さんへの再梱包の作業依頼。

    従来はスプレッドシートで毎回シートを複製し、作る商品にセット数を書いて
    渡していた。それをツール内で完結させる。

    金額は「セット数 × 1セットあたりの単価」。単価・梱包材・梱包方法は
    商品ごとに毎回同じなので商品マスタ(rakuten_products.packing_*)に持たせ、
    依頼作成時にコピーしてくる。今回だけ違う場合はこちらで上書きできる
    （後からマスタを直しても、過去の依頼の金額が変わらないようにするため）。

    請求は order_month（YYYY-MM）single単位で集計する。
    """
    __tablename__ = "welfare_packing_orders"

    id = Column(Integer, primary_key=True, index=True)
    order_month = Column(String, index=True)   # 請求の単位 YYYY-MM
    order_date = Column(String, index=True)    # 依頼日 YYYY-MM-DD
    priority = Column(Integer)                 # 優先順位（小さいほど先）

    task_id = Column(Integer, ForeignKey("welfare_packing_tasks.id"), nullable=True, index=True)
    # どの便の荷受けから作った依頼か（"8/25"）。同じ便から二重に作らないために持つ。
    # 便が違えば同じ作業でも作れる（別の便で同じ商品が来ることがあるため）
    source_batch = Column(String, index=True)
    product_id = Column(Integer, ForeignKey("rakuten_products.id"), nullable=True, index=True)
    sku = Column(String, index=True)
    name_jp = Column(String)
    image_data_url = Column(Text)

    set_qty = Column(Integer, default=0)       # 1セットに入れる数（全数量）
    set_count = Column(Integer, default=0)     # 作るセット数
    unit_price = Column(Float, default=0)      # 1セットあたりの報酬（円）
    amount = Column(Float, default=0)          # set_count × unit_price

    packing_material = Column(Text)            # 梱包材の種類
    packing_method = Column(Text)              # 梱包方法
    note = Column(Text)

    # 依頼中 / 完了。完了にした分も請求には含める
    status = Column(String, default="open", index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    completed_count = Column(Integer, default=0)   # 実際に作れた数（未入力なら set_count）

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
