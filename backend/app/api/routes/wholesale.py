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
from app.models.inventory_reflection_log import InventoryReflectionLog
from app.services import wholesale_excel as wx
from app.services import mailer

router = APIRouter(prefix="/wholesale", tags=["wholesale"])

XLSX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet")


# ---------- 取引先 ----------

class SupplierIn(BaseModel):
    name: str
    honorific: Optional[str] = "御中"
    order_method: Optional[str] = "excel_mail"
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
        "order_method": s.order_method or "excel_mail",
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
                # 発注済2。DBの互換のため standard_stock 列を使っている
                "standard_stock": p.standard_stock or 0,
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
        "message_text": o.message_text,
        "received_at": o.received_at.isoformat() if o.received_at else None,
        "received_mode": o.received_mode,
        "inbound_applied": bool(o.inbound_applied),
    }
    if items is not None:
        d["items"] = [{
            "id": x.id, "item_id": x.item_id, "item_code": x.item_code,
            "jan_code": x.jan_code, "name": x.name, "unit_price": x.unit_price,
            "qty": x.qty, "amount": x.amount, "note": x.note,
            "received_qty": x.received_qty or 0,
            "remaining_qty": max(0, (x.qty or 0) - (x.received_qty or 0)),
        } for x in items]
        # 分納があるので「まだ来ていない数」を持たせる。
        # 全部届いて初めて received_at が入る（＝入荷済み）。
        d["remaining_qty"] = sum(i["remaining_qty"] for i in d["items"])
        d["received_total"] = sum(i["received_qty"] for i in d["items"])
        if o.received_at:
            d["receive_status"] = "received"
        elif d["received_total"] > 0:
            d["receive_status"] = "partial"
        else:
            d["receive_status"] = "none"
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

    # 分納の途中かどうかを一覧でも出す。明細を全部返すと重いので、
    # 発注ごとの合計だけを1クエリでまとめて取る。
    from sqlalchemy import func as sqlfunc
    ids = [o.id for o in rows]
    totals = {}
    if ids:
        for oid_, ordered, received in (
            db.query(WholesaleOrderItem.order_id,
                     sqlfunc.sum(WholesaleOrderItem.qty),
                     sqlfunc.sum(WholesaleOrderItem.received_qty))
            .filter(WholesaleOrderItem.order_id.in_(ids))
            .group_by(WholesaleOrderItem.order_id).all()
        ):
            totals[oid_] = (int(ordered or 0), int(received or 0))

    out = []
    for o in rows:
        d = _order_dict(o, supplier=sup.get(o.supplier_id))
        ordered, received = totals.get(o.id, (0, 0))
        d["ordered_total"] = ordered
        d["received_total"] = received
        d["remaining_qty"] = max(0, ordered - received)
        d["receive_status"] = (
            "received" if o.received_at else ("partial" if received > 0 else "none")
        )
        out.append(d)
    return out


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
        order_date=data.order_date or wx.today_jst().isoformat(),
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
        result = mailer.send(to, subject, body, cc=cc,
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

    # 送信済みトレイに控えが残せたかどうかも記録に残す。
    # 残せなくても送信は成功しているので、失敗扱いにはしない
    copy = result.get("sent_copy") or {}
    if not copy.get("saved"):
        note = f"送信済みトレイへの保存はできませんでした（{copy.get('reason')}）"
        o.memo = ((o.memo or "") + "\n" + note).strip()

    # 発注済に足す。手で入れてあった場合は画面から取り消せる
    changed = _apply_inbound(db, o, items)
    db.commit()

    o, items, s = _load(db, oid)
    return {"ok": True, "order": _order_dict(o, items, s),
            "inbound_changed": changed, "sent_copy": copy}


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
    """設定が正しいか、送らずにログインだけ試す。

    送信済みトレイに控えを残せるかも一緒に見る。SMTPは送るだけで
    控えを残さないので、ここが繋がらないと手元に記録が残らない。
    """
    try:
        r = {"ok": True, **mailer.test_connection()}
    except mailer.MailNotConfigured as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"接続できませんでした: {type(e).__name__}: {e}")
    r["sent_folder"] = mailer.check_sent_folder()
    return r


# ---------- 発注済への反映と入荷 ----------

def _linked_products(db, items):
    """明細から楽天マスタの商品を引く。紐付いていないものは飛ばす。"""
    ids = [x.item_id for x in items if x.item_id]
    if not ids:
        return {}
    link = {w.id: w.rakuten_product_id
            for w in db.query(WholesaleItem).filter(WholesaleItem.id.in_(ids)).all()
            if w.rakuten_product_id}
    if not link:
        return {}
    prods = {p.id: p for p in db.query(RakutenProduct)
             .filter(RakutenProduct.id.in_(link.values())).all()}
    return {x.item_id: prods[link[x.item_id]]
            for x in items if x.item_id in link and link[x.item_id] in prods}


def _apply_inbound(db, o, items):
    """発注済1に足す。送信したときに呼ぶ。

    二重に足さないよう inbound_applied で見張る。すでに手で入れて
    いた場合に困るので、画面から外せるようにしてある。
    """
    if o.inbound_applied:
        return []
    prods = _linked_products(db, items)
    changed = []
    for x in items:
        p = prods.get(x.item_id)
        if not p or not x.qty:
            continue
        before = p.inbound or 0
        p.inbound = before + x.qty
        changed.append({"sku": p.sku, "name": p.name,
                        "before": before, "after": p.inbound, "qty": x.qty})
    o.inbound_applied = True
    return changed


class ApplyInboundIn(BaseModel):
    apply: bool = True     # False で取り消し（手で入れていた場合）


@router.post("/orders/{oid:int}/apply-inbound")
def apply_inbound(oid: int, data: ApplyInboundIn, db: Session = Depends(get_db)):
    """発注済への反映を、あとから付けたり外したりする。

    送信時に自動で足しているが、すでに手で入れてあった場合は
    二重になる。そのときここで取り消す。
    """
    o, items, _ = _load(db, oid)
    if data.apply:
        changed = _apply_inbound(db, o, items)
    else:
        if not o.inbound_applied:
            raise HTTPException(400, "まだ発注済に反映していません")
        prods = _linked_products(db, items)
        changed = []
        for x in items:
            p = prods.get(x.item_id)
            if not p or not x.qty:
                continue
            before = p.inbound or 0
            p.inbound = max(0, before - x.qty)
            changed.append({"sku": p.sku, "name": p.name,
                            "before": before, "after": p.inbound, "qty": -x.qty})
        o.inbound_applied = False
    db.commit()
    return {"ok": True, "applied": o.inbound_applied, "changed": changed}


class ReceiveItemIn(BaseModel):
    item_id: int              # WholesaleOrderItem の id
    received_qty: int = 0


class ReceiveIn(BaseModel):
    """入荷。

    mode:
      add_stock  … 実在庫に足す（ふつうの入荷）
      clear_only … 発注済を消すだけ（先に在庫へ入れてあったとき）
    """
    mode: str = "add_stock"
    items: List[ReceiveItemIn] = []
    note: Optional[str] = None


@router.post("/orders/{oid:int}/receive")
def receive_order(oid: int, data: ReceiveIn, db: Session = Depends(get_db)):
    """入荷処理。実在庫と発注済を動かす。

    在庫を先に入れてしまっていることがあるので、足すかどうかを
    選べるようにしている（clear_only）。どちらでも発注済からは
    減らす。数えた結果を残せるよう、届いた数は明細ごとに持つ。
    """
    o, items, _ = _load(db, oid)
    if o.received_at:
        raise HTTPException(400, "この発注はすでに入荷済みです")
    if data.mode not in ("add_stock", "clear_only"):
        raise HTTPException(400, "mode は add_stock か clear_only です")

    # 分納。1回の入荷で届いた数だけを受け取り、明細には積み上げていく。
    # 指定が無い明細は「残り全部が届いた」とみなす（今までの動きと同じ）。
    # 明細を1つでも指定してきたら、指定が無いものは0とする。
    # 「書いていない＝届いていない」が自然だし、一部だけ指定したつもりが
    # 残り全部を入荷してしまう事故を防ぐ（実際にテストで踏んだ）。
    # 明細をまったく渡さない場合だけ、残り全部が届いたとみなす。
    recv = {r.item_id: r.received_qty for r in data.items}
    specified = bool(data.items)
    arrived = {}
    for x in items:
        already = x.received_qty or 0
        remaining = max(0, (x.qty or 0) - already)
        q = recv.get(x.id, 0 if specified else remaining)
        q = max(0, int(q or 0))
        arrived[x.id] = q
        x.received_qty = already + q
    if not any(arrived.values()):
        raise HTTPException(400, "入荷する数量が入力されていません")

    prods = _linked_products(db, items)
    unlinked = [x.name for x in items if x.item_id not in prods]

    # セット商品の再計算に使うので、楽天の全商品を持ってくる
    from app.api.routes.rakuten import _recalc_dependent_set_stock
    all_products = db.query(RakutenProduct).filter(
        RakutenProduct.is_active == True).all()
    sku_stock = {p.sku: (p.stock or 0) for p in all_products}
    updated = set()
    changed = []
    touched = []          # 発注済2の繰り上げ判定に使う

    for x in items:
        p = prods.get(x.item_id)
        q = arrived.get(x.id, 0)   # 累計ではなく今回届いた分だけ動かす
        if not p or not q:
            continue
        before_stock, before_inbound = p.stock or 0, p.inbound or 0
        if data.mode == "add_stock":
            p.stock = before_stock + q
            sku_stock[p.sku] = p.stock
            updated.add(p.sku)
        # 発注済からは、どちらの場合も減らす
        p.inbound = max(0, before_inbound - q)
        changed.append({
            "sku": p.sku, "name": p.name, "qty": q,
            "stock_before": before_stock, "stock_after": p.stock or 0,
            "inbound_before": before_inbound, "inbound_after": p.inbound or 0,
        })
        _log_reflection(db, o, p, q, before_stock, before_inbound, data.mode)
        if p not in touched:
            touched.append(p)

    # 発注済1を消化しきった商品は発注済2を繰り上げる（入荷待ち一覧と同じ挙動）
    promoted = []
    for p_ in touched:
        if _promote_stage(p_):
            promoted.append({"sku": p_.sku, "name": p_.name, "inbound": p_.inbound})

    if updated:
        _recalc_dependent_set_stock(all_products, sku_stock, updated)

    # まだ残りがあるうちは入荷済みにしない（また入荷できるようにするため）
    fully_received = all((x.received_qty or 0) >= (x.qty or 0) for x in items)
    o.received_at = datetime.now(timezone.utc) if fully_received else None
    o.received_mode = data.mode
    if data.note:
        o.memo = ((o.memo or "") + "\n" + data.note).strip()
    db.commit()

    o, items, s = _load(db, oid)
    return {"ok": True, "order": _order_dict(o, items, s),
            "changed": changed, "unlinked": unlinked, "promoted": promoted}


def _promote_stage(p) -> bool:
    """発注済1が空になったら、発注済2を発注済1へ繰り上げる。

    配送依頼の入荷やメーカー入荷では以前からこうしている。卸発注だけ
    繰り上げていなかったため、発注済1を入荷しきると発注済2が取り残され、
    次のロットが入荷待ちに出てこなくなっていた。
    """
    if (p.inbound or 0) <= 0 and (p.standard_stock or 0) > 0:
        p.inbound = p.standard_stock
        p.standard_stock = 0
        return True
    return False


def _log_reflection(db, o, p, qty, before_stock, before_inbound, mode):
    """在庫反映履歴に残す。どこから動いた在庫かを後で辿れるように。

    o が None のときは、卸発注を通さず発注済へ手で入れていた分の入荷。
    どこから来た在庫か後で分かるよう、表示を分けておく。
    """
    label = "卸入荷" if mode == "add_stock" else "卸入荷(発注済のみ)"
    if o is None:
        label = "手動発注の入荷" if mode == "add_stock" else "手動発注の入荷(発注済のみ)"
    db.add(InventoryReflectionLog(
        source="wholesale_receive",
        source_label=label,
        source_id=o.id if o else None,
        source_ref="卸発注" if o else "手動発注",
        sku=p.sku,
        name=p.name,
        supplier=p.supplier,
        received_qty=qty,
        stock_before=before_stock,
        stock_after=p.stock or 0,
        inbound_before=before_inbound,
        inbound_after=p.inbound or 0,
        rms_push_items=0,
        note=(f"卸発注 {o.order_date} から反映" if o
              else "発注済へ手で入れていた分を入荷"),
    ))


# ---------- 入荷待ち一覧（分納をまとめて処理する） ----------
#
# 発注どおりに一度で届くことは少なく、何回かに分かれて届く。
# 発注を1件ずつ開いて入荷するのは分納が続くと手間なので、
# まだ届いていない明細を発注をまたいで1画面に並べ、届いた分だけ
# 入力してまとめて処理できるようにする。

@router.get("/pending-items")
def list_pending_items(supplier_id: Optional[int] = None, db: Session = Depends(get_db)):
    """まだ届いていない明細を、発注をまたいで返す。"""
    q = (db.query(WholesaleOrderItem, WholesaleOrder)
         .join(WholesaleOrder, WholesaleOrderItem.order_id == WholesaleOrder.id)
         .filter(WholesaleOrder.received_at.is_(None)))
    if supplier_id:
        q = q.filter(WholesaleOrder.supplier_id == supplier_id)
    rows = q.order_by(WholesaleOrder.order_date.asc(), WholesaleOrder.id.asc(),
                      WholesaleOrderItem.sort_order, WholesaleOrderItem.id).all()

    sup = {x.id: x.name for x in db.query(WholesaleSupplier).all()}
    out = []
    pending_by_product = {}   # 卸発注として残っている数（商品ごと）
    for x, o in rows:
        remaining = max(0, (x.qty or 0) - (x.received_qty or 0))
        if remaining <= 0:
            continue
        out.append({
            "source": "order",
            "row_id": x.id, "order_id": o.id, "order_date": o.order_date,
            "supplier_id": o.supplier_id, "supplier_name": sup.get(o.supplier_id),
            "item_id": x.item_id, "name": x.name, "item_code": x.item_code,
            "unit_price": x.unit_price,
            "qty": x.qty or 0, "received_qty": x.received_qty or 0,
            "remaining_qty": remaining,
        })
        if x.item_id:
            pending_by_product[x.item_id] = pending_by_product.get(x.item_id, 0) + remaining

    # 卸発注を通さず、発注済へ手で入れた分も入荷できるようにする。
    # 商品の発注済(inbound)から、卸発注として残っている数を引いた残りが
    # 「手動で入れた分」。ここを出さないと、手動発注の入荷だけ画面から
    # できず在庫・損益ページで手作業になってしまう。
    wq = db.query(WholesaleItem).filter(WholesaleItem.rakuten_product_id.isnot(None))
    if supplier_id:
        wq = wq.filter(WholesaleItem.supplier_id == supplier_id)
    witems = wq.all()
    pids = {w.rakuten_product_id for w in witems}
    prods = {p_.id: p_ for p_ in db.query(RakutenProduct)
             .filter(RakutenProduct.id.in_(pids)).all()} if pids else {}
    for w in witems:
        p_ = prods.get(w.rakuten_product_id)
        if not p_:
            continue
        manual = (p_.inbound or 0) - pending_by_product.get(w.id, 0)
        if manual <= 0:
            continue
        out.append({
            "source": "manual",
            "row_id": None, "order_id": None, "order_date": None,
            "product_id": p_.id, "sku": p_.sku,
            "supplier_id": w.supplier_id, "supplier_name": sup.get(w.supplier_id),
            "item_id": w.id, "name": p_.name or w.name, "item_code": None,
            "unit_price": None,
            "qty": manual, "received_qty": 0, "remaining_qty": manual,
        })
    return out


class ReceiveRowIn(BaseModel):
    # 卸発注の明細を入荷するときは row_id、
    # 発注済へ手で入れていた分を入荷するときは product_id を渡す
    row_id: Optional[int] = None
    product_id: Optional[int] = None
    received_qty: int = 0


class ReceiveItemsIn(BaseModel):
    mode: str = "add_stock"
    items: List[ReceiveRowIn] = []
    note: Optional[str] = None


@router.post("/receive-items")
def receive_items(data: ReceiveItemsIn, db: Session = Depends(get_db)):
    """入荷待ち一覧から、発注をまたいでまとめて入荷する。"""
    if data.mode not in ("add_stock", "clear_only"):
        raise HTTPException(400, "mode は add_stock か clear_only です")
    want = {r.row_id: max(0, int(r.received_qty or 0))
            for r in data.items if r.row_id and (r.received_qty or 0) > 0}
    manual = {}
    for r in data.items:
        if r.row_id or not r.product_id or (r.received_qty or 0) <= 0:
            continue
        manual[r.product_id] = manual.get(r.product_id, 0) + max(0, int(r.received_qty))
    if not want and not manual:
        raise HTTPException(400, "入荷する数量が入力されていません")

    rows = (db.query(WholesaleOrderItem)
            .filter(WholesaleOrderItem.id.in_(list(want.keys()))).all()) if want else []
    if not rows and not manual:
        raise HTTPException(404, "対象の明細が見つかりません")

    orders = {o.id: o for o in db.query(WholesaleOrder)
              .filter(WholesaleOrder.id.in_({r.order_id for r in rows})).all()}

    from app.api.routes.rakuten import _recalc_dependent_set_stock
    all_products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
    by_item = {}
    links = {w.id: w.rakuten_product_id for w in db.query(WholesaleItem)
             .filter(WholesaleItem.id.in_({r.item_id for r in rows if r.item_id})).all()
             if w.rakuten_product_id}
    prod_by_id = {p.id: p for p in all_products}
    for r in rows:
        pid = links.get(r.item_id)
        if pid and pid in prod_by_id:
            by_item[r.id] = prod_by_id[pid]

    sku_stock = {p.sku: (p.stock or 0) for p in all_products}
    updated, changed, unlinked = set(), [], []
    touched = []          # 発注済2の繰り上げ判定に使う（重複しないよう後で一意化）

    for r in rows:
        already = r.received_qty or 0
        remaining = max(0, (r.qty or 0) - already)
        q = min(want[r.id], remaining) if remaining > 0 else 0
        if q <= 0:
            continue
        r.received_qty = already + q
        p = by_item.get(r.id)
        if not p:
            unlinked.append(r.name)
            continue
        before_stock, before_inbound = p.stock or 0, p.inbound or 0
        if data.mode == "add_stock":
            p.stock = before_stock + q
            sku_stock[p.sku] = p.stock
            updated.add(p.sku)
        p.inbound = max(0, before_inbound - q)
        changed.append({
            "sku": p.sku, "name": p.name, "qty": q,
            "order_id": r.order_id,
            "stock_before": before_stock, "stock_after": p.stock or 0,
            "inbound_before": before_inbound, "inbound_after": p.inbound or 0,
        })
        _log_reflection(db, orders[r.order_id], p, q, before_stock, before_inbound, data.mode)
        if p not in touched:
            touched.append(p)

    # 卸発注を通さず発注済へ手で入れていた分。発注明細が無いので
    # 商品の発注済を直接減らし、届いた分を在庫へ入れる。
    for pid, q in manual.items():
        p = prod_by_id.get(pid)
        if not p or q <= 0:
            continue
        q = min(q, p.inbound or 0)   # 発注済を超えて入荷はできない
        if q <= 0:
            continue
        before_stock, before_inbound = p.stock or 0, p.inbound or 0
        if data.mode == "add_stock":
            p.stock = before_stock + q
            sku_stock[p.sku] = p.stock
            updated.add(p.sku)
        p.inbound = max(0, before_inbound - q)
        changed.append({
            "sku": p.sku, "name": p.name, "qty": q, "order_id": None,
            "stock_before": before_stock, "stock_after": p.stock or 0,
            "inbound_before": before_inbound, "inbound_after": p.inbound or 0,
        })
        _log_reflection(db, None, p, q, before_stock, before_inbound, data.mode)
        if p not in touched:
            touched.append(p)

    # 発注済1を消化しきった商品は、発注済2を繰り上げる。
    # 行ごとに繰り上げると、同じ商品の次の行が繰り上げ後の数から
    # 引かれてしまうので、全部処理し終えてからまとめて行う。
    promoted = []
    for p_ in touched:
        if _promote_stage(p_):
            promoted.append({"sku": p_.sku, "name": p_.name, "inbound": p_.inbound})

    if updated:
        _recalc_dependent_set_stock(all_products, sku_stock, updated)

    # 発注ごとに、全部届いたかを見て入荷済みにする
    completed = []
    for oid_, o in orders.items():
        its = db.query(WholesaleOrderItem).filter(WholesaleOrderItem.order_id == oid_).all()
        if its and all((x.received_qty or 0) >= (x.qty or 0) for x in its):
            o.received_at = datetime.now(timezone.utc)
            o.received_mode = data.mode
            completed.append(oid_)
        if data.note:
            o.memo = (chr(10).join(x for x in [(o.memo or ''), data.note] if x)).strip()

    db.commit()
    return {"ok": True, "changed": changed, "unlinked": unlinked,
            "completed_orders": completed, "promoted": promoted}


@router.post("/orders/{oid:int}/undo-receive")
def undo_receive(oid: int, db: Session = Depends(get_db)):
    """入荷を取り消す。押し間違えたときのため。

    分納で複数回入荷していても、これまでに受け取った分をまとめて戻す。
    received_qty も0に戻さないと、次に入荷したとき二重に積み上がる。
    """
    o, items, _ = _load(db, oid)
    received_total = sum(x.received_qty or 0 for x in items)
    if not o.received_at and received_total <= 0:
        raise HTTPException(400, "まだ入荷していません")

    prods = _linked_products(db, items)
    for x in items:
        p = prods.get(x.item_id)
        q = x.received_qty or 0
        if not p or not q:
            x.received_qty = 0
            continue
        if o.received_mode == "add_stock":
            p.stock = max(0, (p.stock or 0) - q)
        p.inbound = (p.inbound or 0) + q
        x.received_qty = 0

    o.received_at = None
    o.received_mode = None
    db.commit()
    o, items, s = _load(db, oid)
    return {"ok": True, "order": _order_dict(o, items, s)}


# ---------- LINEで送る発注 ----------

def build_message(db, o, items):
    """LINEに貼る発注の文面を作る。

    すでに発注済がある商品は「追加300（計900）」と書く。相手が
    前回からの積み上げを把握できるようにするため、今までそう
    書いて送っていた形に合わせている。

    発注済が0の商品は数量だけ書く。
    """
    prods = _linked_products(db, items)
    lines = ["発注お願いします！", ""]
    for x in items:
        if not x.qty:
            continue
        p = prods.get(x.item_id)
        already = (p.inbound or 0) if p else 0
        if already > 0:
            lines.append(f"・{x.name}追加{x.qty}（計{already + x.qty}）")
        else:
            lines.append(f"・{x.name}{x.qty}")
    return "\n".join(lines)


@router.get("/orders/{oid:int}/message")
def get_message(oid: int, db: Session = Depends(get_db)):
    """LINEに貼る文面。送信前はその場で組み立て、送信後は送った文面を返す。

    送ったあとに発注済が変わっても、送った内容は変わってはいけない。
    """
    o, items, s = _load(db, oid)
    text = o.message_text or build_message(db, o, items)
    return {"order": _order_dict(o, items, s), "text": text}


class ConfirmIn(BaseModel):
    """LINEで送ったことを記録する。文面は画面で直せるので受け取る。"""
    text: Optional[str] = None


@router.post("/orders/{oid:int}/confirm")
def confirm_order(oid: int, data: ConfirmIn, db: Session = Depends(get_db)):
    """LINEで送ったあとに押す。発注済へ反映し、送信済みにする。

    メールと違い実際に送るのは人なので、送ったかどうかはここで
    教えてもらう。押した時点で発注済に足す。
    """
    o, items, s = _load(db, oid)
    if o.status == "sent":
        raise HTTPException(400, "この発注はすでに送信済みです")

    # 文面は発注済を足す前に確定させる。先に足すと「計」がずれる
    o.message_text = data.text or build_message(db, o, items)
    changed = _apply_inbound(db, o, items)

    o.status = "sent"
    o.sent_at = datetime.now(timezone.utc)
    o.sent_to = "LINE"
    db.commit()

    o, items, s = _load(db, oid)
    return {"ok": True, "order": _order_dict(o, items, s),
            "inbound_changed": changed}



class ImportFromRakutenIn(BaseModel):
    supplier_id: int
    rakuten_supplier: str            # 楽天マスタの仕入先名
    skip_sets: bool = True           # セット商品を除くか


@router.post("/items/import-from-rakuten")
def import_from_rakuten(data: ImportFromRakutenIn, db: Session = Depends(get_db)):
    """楽天マスタから、その仕入先の商品を卸商品として取り込む。

    セット商品は既定で除く。発注するのは単品で、セットはそこから
    組むものなので、発注画面に出ると邪魔になる。
    """
    sup = (db.query(WholesaleSupplier)
           .filter(WholesaleSupplier.id == data.supplier_id).first())
    if not sup:
        raise HTTPException(404, "取引先が見つかりません")

    q = db.query(RakutenProduct).filter(
        RakutenProduct.supplier == data.rakuten_supplier,
        RakutenProduct.is_active == True)
    prods = q.all()

    have = {i.rakuten_product_id for i in
            db.query(WholesaleItem)
            .filter(WholesaleItem.supplier_id == data.supplier_id).all()
            if i.rakuten_product_id}

    added = skipped_set = 0
    for n, p in enumerate(sorted(prods, key=lambda x: str(x.sku))):
        if data.skip_sets and p.set_components and p.set_components not in ("[]", "null"):
            skipped_set += 1
            continue
        if p.id in have:
            continue
        db.add(WholesaleItem(
            supplier_id=data.supplier_id, rakuten_product_id=p.id,
            name=p.name, unit_price=0, sort_order=n, is_active=True))
        added += 1
    db.commit()
    return {"added": added, "skipped_sets": skipped_set,
            "total": db.query(WholesaleItem)
                     .filter(WholesaleItem.supplier_id == data.supplier_id).count()}
