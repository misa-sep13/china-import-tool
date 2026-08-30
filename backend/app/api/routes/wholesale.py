"""卸発注（メーカー品）。

発注書のExcelを作り、内容を確認してからメールで送る。
送信は取り消せないので、作る（draft）と送る（send）を必ず分けている。
"""
import base64
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.wholesale import (
    WholesaleSupplier, WholesaleItem, WholesaleOrder, WholesaleOrderItem,
)
from app.models.rakuten_product import RakutenProduct
from app.services import wholesale_excel as wx
from app.services import mailer

router = APIRouter(prefix="/wholesale", tags=["wholesale"])

XLSX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet")


# ---------- 取引先 ----------

class SupplierIn(BaseModel):
    name: str
    honorific: Optional[str] = "御中"
    email_to: Optional[str] = None
    email_cc: Optional[str] = None
    mail_subject: Optional[str] = None
    mail_greeting: Optional[str] = None
    mail_body: Optional[str] = None
    sort_order: Optional[int] = 0
    is_active: Optional[bool] = True


def _supplier_dict(s):
    return {
        "id": s.id, "name": s.name, "honorific": s.honorific,
        "email_to": s.email_to, "email_cc": s.email_cc,
        "mail_subject": s.mail_subject, "mail_greeting": s.mail_greeting,
        "mail_body": s.mail_body, "sort_order": s.sort_order,
        "is_active": s.is_active,
    }


@router.get("/suppliers")
def list_suppliers(db: Session = Depends(get_db)):
    rows = (db.query(WholesaleSupplier)
            .order_by(WholesaleSupplier.sort_order, WholesaleSupplier.id).all())
    return [_supplier_dict(s) for s in rows]


@router.post("/suppliers")
def create_supplier(data: SupplierIn, db: Session = Depends(get_db)):
    s = WholesaleSupplier(**data.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return _supplier_dict(s)


@router.put("/suppliers/{sid:int}")
def update_supplier(sid: int, data: SupplierIn, db: Session = Depends(get_db)):
    s = db.query(WholesaleSupplier).filter(WholesaleSupplier.id == sid).first()
    if not s:
        raise HTTPException(404, "取引先が見つかりません")
    for k, v in data.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return _supplier_dict(s)


@router.delete("/suppliers/{sid:int}")
def delete_supplier(sid: int, db: Session = Depends(get_db)):
    s = db.query(WholesaleSupplier).filter(WholesaleSupplier.id == sid).first()
    if not s:
        raise HTTPException(404, "取引先が見つかりません")
    n = db.query(WholesaleItem).filter(WholesaleItem.supplier_id == sid).count()
    if n:
        raise HTTPException(
            400, f"この取引先には商品が{n}件あります。先に商品を消してください")
    db.delete(s)
    db.commit()
    return {"deleted": sid}


# ---------- 卸商品 ----------

class ItemIn(BaseModel):
    supplier_id: int
    rakuten_product_id: Optional[int] = None
    item_code: Optional[str] = None
    jan_code: Optional[str] = None
    name: str
    unit_price: Optional[float] = 0
    note: Optional[str] = None
    deliver_zip: Optional[str] = None
    deliver_address: Optional[str] = None
    deliver_note: Optional[str] = None
    sort_order: Optional[int] = 0
    is_active: Optional[bool] = True


def _item_dict(i, stock=None):
    d = {
        "id": i.id, "supplier_id": i.supplier_id,
        "rakuten_product_id": i.rakuten_product_id,
        "item_code": i.item_code, "jan_code": i.jan_code, "name": i.name,
        "unit_price": i.unit_price, "note": i.note,
        "deliver_zip": i.deliver_zip, "deliver_address": i.deliver_address,
        "deliver_note": i.deliver_note,
        "sort_order": i.sort_order, "is_active": i.is_active,
    }
    if stock is not None:
        d.update(stock)
    return d


@router.get("/items")
def list_items(supplier_id: Optional[int] = None,
               active_only: bool = False,
               db: Session = Depends(get_db)):
    """卸商品。楽天マスタと結び付いていれば在庫も一緒に返す。

    発注数を決めるとき、在庫と発注済が見えないと判断できないため。
    """
    q = db.query(WholesaleItem)
    if supplier_id:
        q = q.filter(WholesaleItem.supplier_id == supplier_id)
    if active_only:
        q = q.filter(WholesaleItem.is_active == True)
    rows = q.order_by(WholesaleItem.sort_order, WholesaleItem.id).all()

    ids = [r.rakuten_product_id for r in rows if r.rakuten_product_id]
    stocks = {}
    if ids:
        for p in db.query(RakutenProduct).filter(RakutenProduct.id.in_(ids)).all():
            stocks[p.id] = {
                "sku": p.sku, "rakuten_name": p.name,
                "stock": p.stock or 0, "inbound": p.inbound or 0,
                "sales_90": p.sales_90 or 0,
            }
    return [_item_dict(r, stocks.get(r.rakuten_product_id)) for r in rows]


@router.post("/items")
def create_item(data: ItemIn, db: Session = Depends(get_db)):
    i = WholesaleItem(**data.model_dump())
    db.add(i)
    db.commit()
    db.refresh(i)
    return _item_dict(i)


@router.put("/items/{iid:int}")
def update_item(iid: int, data: ItemIn, db: Session = Depends(get_db)):
    i = db.query(WholesaleItem).filter(WholesaleItem.id == iid).first()
    if not i:
        raise HTTPException(404, "商品が見つかりません")
    for k, v in data.model_dump().items():
        setattr(i, k, v)
    db.commit()
    return _item_dict(i)


@router.delete("/items/{iid:int}")
def delete_item(iid: int, db: Session = Depends(get_db)):
    i = db.query(WholesaleItem).filter(WholesaleItem.id == iid).first()
    if not i:
        raise HTTPException(404, "商品が見つかりません")
    db.delete(i)
    db.commit()
    return {"deleted": iid}


# ---------- 発注 ----------

class OrderItemIn(BaseModel):
    item_id: Optional[int] = None
    item_code: Optional[str] = None
    jan_code: Optional[str] = None
    name: str
    unit_price: float = 0
    qty: int = 0
    note: Optional[str] = None


class OrderIn(BaseModel):
    supplier_id: int
    order_date: Optional[str] = None
    order_no: Optional[str] = None
    subject: Optional[str] = None
    delivery_date: Optional[str] = None
    deliver_zip: Optional[str] = None
    deliver_address: Optional[str] = None
    deliver_note: Optional[str] = None
    payment_terms: Optional[str] = None
    memo: Optional[str] = None
    items: List[OrderItemIn] = []


def _order_dict(o, items=None, supplier=None):
    d = {
        "id": o.id, "supplier_id": o.supplier_id,
        "supplier_name": supplier.name if supplier else None,
        "order_date": o.order_date, "order_no": o.order_no,
        "subject": o.subject, "delivery_date": o.delivery_date,
        "deliver_zip": o.deliver_zip, "deliver_address": o.deliver_address,
        "deliver_note": o.deliver_note, "payment_terms": o.payment_terms,
        "subtotal": o.subtotal, "tax": o.tax, "total": o.total,
        "status": o.status, "sent_at": o.sent_at.isoformat() if o.sent_at else None,
        "sent_to": o.sent_to, "sent_cc": o.sent_cc,
        "file_name": o.file_name, "error": o.error, "memo": o.memo,
    }
    if items is not None:
        d["items"] = [{
            "id": x.id, "item_id": x.item_id, "item_code": x.item_code,
            "jan_code": x.jan_code, "name": x.name, "unit_price": x.unit_price,
            "qty": x.qty, "amount": x.amount, "note": x.note,
        } for x in items]
    return d


def _load(db, oid):
    o = db.query(WholesaleOrder).filter(WholesaleOrder.id == oid).first()
    if not o:
        raise HTTPException(404, "発注が見つかりません")
    items = (db.query(WholesaleOrderItem)
             .filter(WholesaleOrderItem.order_id == oid)
             .order_by(WholesaleOrderItem.sort_order, WholesaleOrderItem.id).all())
    s = (db.query(WholesaleSupplier)
         .filter(WholesaleSupplier.id == o.supplier_id).first())
    return o, items, s


@router.get("/orders")
def list_orders(supplier_id: Optional[int] = None, limit: int = 100,
                db: Session = Depends(get_db)):
    q = db.query(WholesaleOrder)
    if supplier_id:
        q = q.filter(WholesaleOrder.supplier_id == supplier_id)
    rows = q.order_by(WholesaleOrder.id.desc()).limit(limit).all()
    sup = {s.id: s for s in db.query(WholesaleSupplier).all()}
    return [_order_dict(o, supplier=sup.get(o.supplier_id)) for o in rows]


@router.get("/orders/{oid:int}")
def get_order(oid: int, db: Session = Depends(get_db)):
    o, items, s = _load(db, oid)
    return _order_dict(o, items, s)


@router.post("/orders")
def create_order(data: OrderIn, db: Session = Depends(get_db)):
    """発注を作る。まだ送らない（status=draft）。"""
    s = (db.query(WholesaleSupplier)
         .filter(WholesaleSupplier.id == data.supplier_id).first())
    if not s:
        raise HTTPException(404, "取引先が見つかりません")

    rows = [i for i in data.items if (i.qty or 0) > 0]
    if not rows:
        raise HTTPException(400, "数量が入っている商品がありません")

    subtotal, tax, total = wx.calc_totals([i.model_dump() for i in rows])

    o = WholesaleOrder(
        supplier_id=data.supplier_id,
        order_date=data.order_date or date.today().isoformat(),
        order_no=data.order_no, subject=data.subject,
        delivery_date=data.delivery_date,
        deliver_zip=data.deliver_zip, deliver_address=data.deliver_address,
        deliver_note=data.deliver_note, payment_terms=data.payment_terms,
        subtotal=subtotal, tax=tax, total=total,
        status="draft", memo=data.memo,
        file_name=wx.file_name(s.name, data.order_date),
    )
    db.add(o)
    db.flush()

    for n, i in enumerate(rows):
        db.add(WholesaleOrderItem(
            order_id=o.id, item_id=i.item_id, item_code=i.item_code,
            jan_code=i.jan_code, name=i.name, unit_price=i.unit_price,
            qty=i.qty, amount=(i.unit_price or 0) * (i.qty or 0),
            note=i.note, sort_order=n))
    db.commit()

    o, items, s = _load(db, o.id)
    return _order_dict(o, items, s)


@router.put("/orders/{oid:int}")
def update_order(oid: int, data: OrderIn, db: Session = Depends(get_db)):
    o, _, _ = _load(db, oid)
    if o.status == "sent":
        raise HTTPException(400, "送信済みの発注は変更できません")

    rows = [i for i in data.items if (i.qty or 0) > 0]
    if not rows:
        raise HTTPException(400, "数量が入っている商品がありません")
    subtotal, tax, total = wx.calc_totals([i.model_dump() for i in rows])

    for k in ("order_date", "order_no", "subject", "delivery_date",
              "deliver_zip", "deliver_address", "deliver_note",
              "payment_terms", "memo"):
        setattr(o, k, getattr(data, k))
    o.subtotal, o.tax, o.total = subtotal, tax, total

    db.query(WholesaleOrderItem).filter(WholesaleOrderItem.order_id == oid).delete()
    for n, i in enumerate(rows):
        db.add(WholesaleOrderItem(
            order_id=oid, item_id=i.item_id, item_code=i.item_code,
            jan_code=i.jan_code, name=i.name, unit_price=i.unit_price,
            qty=i.qty, amount=(i.unit_price or 0) * (i.qty or 0),
            note=i.note, sort_order=n))
    db.commit()

    o, items, s = _load(db, oid)
    return _order_dict(o, items, s)


@router.delete("/orders/{oid:int}")
def delete_order(oid: int, db: Session = Depends(get_db)):
    o, _, _ = _load(db, oid)
    if o.status == "sent":
        raise HTTPException(400, "送信済みの発注は消せません")
    db.query(WholesaleOrderItem).filter(WholesaleOrderItem.order_id == oid).delete()
    db.delete(o)
    db.commit()
    return {"deleted": oid}


def _build_excel(o, items, s):
    return wx.build(
        {"name": s.name, "honorific": s.honorific},
        {"order_date": o.order_date, "order_no": o.order_no,
         "subject": o.subject, "delivery_date": o.delivery_date,
         "deliver_zip": o.deliver_zip, "deliver_address": o.deliver_address,
         "deliver_note": o.deliver_note, "payment_terms": o.payment_terms},
        [{"item_code": x.item_code, "jan_code": x.jan_code, "name": x.name,
          "unit_price": x.unit_price, "qty": x.qty, "note": x.note}
         for x in items])


DEFAULT_BODY = ("お世話になっております。\n\n発注書になります。\n\n"
                "お手配のほどよろしくお願いいたします。")

SIGNATURE = (
    "\n\n------------------------------\n"
    "株式会社美園工芸社\n"
    "〒339-0032\n"
    "埼玉県さいたま市見沼区片柳1092\n"
    "白井美沙 misa@misono-web.com\n"
    "090-8689-6636\n"
    "------------------------------"
)


def _mail_text(s):
    """メール本文。取引先ごとの定型文に署名を足す。"""
    greeting = (s.mail_greeting or "ご担当者様").strip()
    body = (s.mail_body or DEFAULT_BODY).strip()
    return f"{greeting}\n\n{body}{SIGNATURE}"


@router.get("/orders/{oid:int}/preview")
def preview(oid: int, db: Session = Depends(get_db)):
    """送る前の確認用。Excelとメールの中身をまとめて返す。

    ここで見た内容がそのまま送られる。送信前に必ず通す。
    """
    o, items, s = _load(db, oid)
    data = _build_excel(o, items, s)
    return {
        "order": _order_dict(o, items, s),
        "mail": {
            "to": s.email_to, "cc": s.email_cc,
            "subject": s.mail_subject or "発注書になります",
            "body": _mail_text(s),
        },
        "file": {
            "name": o.file_name,
            "size": len(data),
            "content_base64": base64.b64encode(data).decode(),
        },
        "mail_configured": mailer.is_configured(),
    }


class SendIn(BaseModel):
    """送信時に画面で直した内容を受ける。宛先の打ち間違いを直せるように。"""
    to: Optional[str] = None
    cc: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None


@router.post("/orders/{oid:int}/send")
def send_order(oid: int, data: SendIn, db: Session = Depends(get_db)):
    o, items, s = _load(db, oid)
    if o.status == "sent":
        raise HTTPException(400, "この発注はすでに送信済みです")

    to = (data.to or s.email_to or "").strip()
    if not to:
        raise HTTPException(400, "宛先がありません。取引先の設定を確認してください")
    cc = (data.cc if data.cc is not None else s.email_cc) or ""
    subject = (data.subject or s.mail_subject or "発注書になります").strip()
    body = data.body if data.body is not None else _mail_text(s)

    xlsx = _build_excel(o, items, s)
    try:
        mailer.send(to, subject, body, cc=cc,
                    attachments=[(o.file_name, xlsx, XLSX_MIME)])
    except mailer.MailNotConfigured as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        # 失敗も記録に残す。送れたのか送れなかったのかを後から追えるように
        o.status = "failed"
        o.error = f"{type(e).__name__}: {e}"
        db.commit()
        raise HTTPException(500, f"送信に失敗しました: {e}")

    o.status = "sent"
    o.sent_at = datetime.now(timezone.utc)
    o.sent_to, o.sent_cc = to, cc
    o.sent_subject, o.sent_body = subject, body
    o.error = None
    db.commit()

    o, items, s = _load(db, oid)
    return {"ok": True, "order": _order_dict(o, items, s)}


@router.get("/mail/status")
def mail_status():
    """送信設定が入っているか。画面で案内を出すため。"""
    c = mailer.config()
    return {
        "configured": mailer.is_configured(),
        "host": c["host"], "port": c["port"], "user": c["user"],
        "from_email": c["from_email"], "from_name": c["from_name"],
    }


@router.post("/mail/test")
def mail_test():
    """設定が正しいか、送らずにログインだけ試す。"""
    try:
        return {"ok": True, **mailer.test_connection()}
    except mailer.MailNotConfigured as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"接続できませんでした: {type(e).__name__}: {e}")
