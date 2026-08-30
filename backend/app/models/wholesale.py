"""卸発注（メーカー品）。

中国輸入（タオタロウ）とは発注の出し方がまったく違う。あちらは
サイトへ入力するが、こちらは発注書のExcelを作ってメールで送る。
様式も取引先が決めたものなので、楽天の商品マスタとは分けて持つ。

楽天マスタにも同じ商品はあるが、そちらは自社の販売用（税込原価・
自社での商品名）。発注書には取引先の名前と税抜単価を出す必要が
あるので、ここで別に持つ。
"""
from sqlalchemy import Boolean, Column, Integer, Float, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func

from app.core.database import Base


class WholesaleSupplier(Base):
    """取引先。発注書の宛先と、メールの送り先。"""
    __tablename__ = "wholesale_suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)              # 株式会社エジソン販売
    honorific = Column(String, default="御中")      # 御中 / 様
    # 発注の出し方。excel_mail … 発注書を作ってメール
    #                text_line  … LINEに貼る文面を作る（Excelもメールも使わない）
    order_method = Column(String, default="excel_mail")
    email_to = Column(String)                      # order@edisonmama.com
    email_cc = Column(String)                      # 複数はカンマ区切り
    mail_subject = Column(String, default="発注書になります")
    mail_greeting = Column(String)                 # ご担当者様 / 乾様
    mail_body = Column(Text)                       # 本文（署名の前まで）
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())


class WholesaleItem(Base):
    """卸商品。発注書に出す名前・単価・納品先を持つ。

    納品先を商品ごとに持つのは、同じリビック宛でもヘアカット
    モンスターはあざみ共同作業所へ、モミモミは美園工芸社へ、と
    送り先が分かれるため（過去の発注書がそうなっていた）。
    """
    __tablename__ = "wholesale_items"

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("wholesale_suppliers.id"), index=True)
    # 楽天マスタと結び付けて在庫を見せる。切れていても発注はできる
    rakuten_product_id = Column(Integer, ForeignKey("rakuten_products.id"),
                                nullable=True, index=True)

    item_code = Column(String)        # 商品番号（発注書A列）
    jan_code = Column(String)         # JANコード（発注書B列）。無くてもよい
    name = Column(String)             # 発注書に出す商品名（取引先の呼び方）
    unit_price = Column(Float)        # 卸単価（税抜）
    note = Column(String)             # 備考（発注書G列）

    # 納品場所。発注書のB8とC9に入る
    deliver_zip = Column(String)
    deliver_address = Column(String)
    deliver_note = Column(String)     # あざみ共同作業所　小野川様宛

    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())


class WholesaleOrder(Base):
    """発注。作った発注書とその送信結果。"""
    __tablename__ = "wholesale_orders"

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("wholesale_suppliers.id"), index=True)
    order_date = Column(String, index=True)       # 2026-09-01
    order_no = Column(String)                     # 発注書のNo欄。使っていなければ空

    subject = Column(String)                      # 件名
    delivery_date = Column(String)                # 納期
    deliver_zip = Column(String)                  # 実際に出した納品場所
    deliver_address = Column(String)
    deliver_note = Column(String)
    payment_terms = Column(String)                # 支払条件

    subtotal = Column(Float, default=0)           # 税抜合計
    tax = Column(Float, default=0)                # 消費税
    total = Column(Float, default=0)              # 税込合計（切り捨て）

    # 送信の記録。送ったかどうかが後から分かるように
    status = Column(String, default="draft")      # draft / sent / failed
    sent_at = Column(DateTime(timezone=True), nullable=True)
    sent_to = Column(String)
    sent_cc = Column(String)
    sent_subject = Column(String)
    sent_body = Column(Text)
    file_name = Column(String)
    error = Column(Text)                          # 送信に失敗したときの理由

    # LINEで送る発注のとき、実際に送った文面。あとで何を頼んだか
    # 見返せるように残す
    message_text = Column(Text)

    # 入荷。発注してから届くまでを追えるように、発注と同じ行に持つ
    received_at = Column(DateTime(timezone=True), nullable=True)
    received_mode = Column(String)   # add_stock（在庫に足す）/ clear_only（発注済を消すだけ）

    # 発注済への反映。二重に足さないよう、反映したかどうかを覚えておく
    inbound_applied = Column(Boolean, default=False)

    memo = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now())


class WholesaleOrderItem(Base):
    """発注の明細。

    単価と商品名はここにも写す。あとでマスタの単価を変えても、
    過去に出した発注書の内容は変わってはいけないため。
    """
    __tablename__ = "wholesale_order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("wholesale_orders.id"), index=True)
    item_id = Column(Integer, ForeignKey("wholesale_items.id"), nullable=True)

    item_code = Column(String)
    jan_code = Column(String)
    name = Column(String)
    unit_price = Column(Float)
    qty = Column(Integer, default=0)
    amount = Column(Float, default=0)
    note = Column(String)
    sort_order = Column(Integer, default=0)

    # 実際に届いた数。欠品や分納があるので、発注数とは別に持つ
    received_qty = Column(Integer, default=0)
