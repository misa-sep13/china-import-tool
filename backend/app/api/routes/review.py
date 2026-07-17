import csv
import io
import json
import re
import httpx
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.review import ReviewCampaign, ReviewEntry, ReviewTemplate
from app.models.rakuten_settings import RakutenSettings
from app.services.rakuten_rms import _auth_header, RMS_BASE

router = APIRouter(prefix="/review", tags=["review"])
JST = timezone(timedelta(hours=9))


# ── Schemas ──────────────────────────────────────────────
class CampaignIn(BaseModel):
    code: str
    name: str
    product_sku: str | None = None
    keywords: str | None = None
    is_active: bool = True

class EntrySingleIn(BaseModel):
    order_number: str
    zip1: str = ""
    zip2: str = ""
    prefecture: str = ""
    city: str = ""
    address: str = ""
    last_name: str = ""
    first_name: str = ""
    phone1: str = ""
    phone2: str = ""
    phone3: str = ""
    campaign_code: str = ""
    campaign_name: str = ""
    quantity: int = 1
    inquiry_message: str | None = None
    buyer_name: str | None = None
    buyer_differs: bool = False
    item_name: str | None = None

class EntryStatusIn(BaseModel):
    status: str

class InquiryCompleteIn(BaseModel):
    inquiry_numbers: list[str]

class TemplateIn(BaseModel):
    name: str
    body: str

class ReplyIn(BaseModel):
    inquiry_number: str
    message: str

class EntryNotesIn(BaseModel):
    notes: str | None = None


# ── Campaign CRUD ────────────────────────────────────────
@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    return db.query(ReviewCampaign).order_by(ReviewCampaign.code).all()

@router.post("/campaigns")
def create_campaign(data: CampaignIn, db: Session = Depends(get_db)):
    existing = db.query(ReviewCampaign).filter(ReviewCampaign.code == data.code).first()
    if existing:
        raise HTTPException(400, f"コード '{data.code}' は既に存在します")
    c = ReviewCampaign(**data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c

@router.put("/campaigns/{campaign_id}")
def update_campaign(campaign_id: int, data: CampaignIn, db: Session = Depends(get_db)):
    c = db.query(ReviewCampaign).filter(ReviewCampaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c

@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = db.query(ReviewCampaign).filter(ReviewCampaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404)
    db.delete(c)
    db.commit()
    return {"ok": True}


# ── 返信テンプレート CRUD ────────────────────────────────
@router.get("/templates")
def list_templates(db: Session = Depends(get_db)):
    return db.query(ReviewTemplate).order_by(ReviewTemplate.name).all()

@router.post("/templates")
def create_template(data: TemplateIn, db: Session = Depends(get_db)):
    t = ReviewTemplate(**data.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    return t

@router.put("/templates/{template_id}")
def update_template(template_id: int, data: TemplateIn, db: Session = Depends(get_db)):
    t = db.query(ReviewTemplate).filter(ReviewTemplate.id == template_id).first()
    if not t:
        raise HTTPException(404)
    t.name = data.name
    t.body = data.body
    db.commit()
    db.refresh(t)
    return t

@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(ReviewTemplate).filter(ReviewTemplate.id == template_id).first()
    if not t:
        raise HTTPException(404)
    db.delete(t)
    db.commit()
    return {"ok": True}


# ── CSV Import ───────────────────────────────────────────
@router.post("/entries/import")
async def import_entries(file: UploadFile = File(...), db: Session = Depends(get_db)):
    raw = await file.read()
    for enc in ("utf-8-sig", "utf-8", "shift_jis", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        raise HTTPException(400, "ファイルのエンコーディングを認識できません")

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise HTTPException(400, "CSVが空です")

    header = rows[0]
    data_rows = rows[1:]
    batch = date.today().isoformat()
    created = 0
    skipped = 0

    for row in data_rows:
        if len(row) < 15:
            continue
        order_number = row[0].strip().strip('"')
        if not order_number:
            continue

        existing = db.query(ReviewEntry).filter(
            ReviewEntry.order_number == order_number,
            ReviewEntry.campaign_code == row[9].strip().strip('"'),
        ).first()
        if existing:
            skipped += 1
            continue

        entry = ReviewEntry(
            order_number=order_number,
            zip1=row[1].strip().strip('"'),
            zip2=row[2].strip().strip('"'),
            prefecture=row[3].strip().strip('"'),
            city=row[4].strip().strip('"'),
            address=row[5].strip().strip('"'),
            last_name=row[6].strip().strip('"'),
            first_name=row[7].strip().strip('"'),
            campaign_code=row[9].strip().strip('"'),
            campaign_name=row[8].strip().strip('"'),
            quantity=int(row[11].strip().strip('"') or 1),
            phone1=row[12].strip().strip('"'),
            phone2=row[13].strip().strip('"'),
            phone3=row[14].strip().strip('"') if len(row) > 14 else "",
            status="pending",
            batch_date=batch,
        )
        db.add(entry)
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped, "batch_date": batch}


# ── Single entry from inquiry ────────────────────────────
@router.post("/entries/import-single")
def import_single_entry(data: EntrySingleIn, db: Session = Depends(get_db)):
    existing = db.query(ReviewEntry).filter(
        ReviewEntry.order_number == data.order_number,
        ReviewEntry.campaign_code == data.campaign_code,
    ).first()
    if existing:
        return {"ok": True, "skipped": True, "id": existing.id}

    campaigns = {c.code: c for c in db.query(ReviewCampaign).all()}
    camp = campaigns.get(data.campaign_code)

    entry = ReviewEntry(
        order_number=data.order_number,
        zip1=data.zip1, zip2=data.zip2,
        prefecture=data.prefecture, city=data.city, address=data.address,
        last_name=data.last_name, first_name=data.first_name,
        phone1=data.phone1, phone2=data.phone2, phone3=data.phone3,
        campaign_code=data.campaign_code,
        campaign_name=camp.name if camp else data.campaign_name,
        quantity=data.quantity,
        inquiry_message=data.inquiry_message,
        buyer_name=data.buyer_name,
        buyer_differs=data.buyer_differs,
        item_name=data.item_name,
        status="pending",
        batch_date=date.today().isoformat(),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"ok": True, "skipped": False, "id": entry.id}


# ── Entry List ───────────────────────────────────────────
@router.get("/entries")
def list_entries(
    status: str | None = None,
    campaign_code: str | None = None,
    batch_date: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(ReviewEntry).order_by(ReviewEntry.created_at.desc())
    if status:
        q = q.filter(ReviewEntry.status == status)
    if campaign_code:
        q = q.filter(ReviewEntry.campaign_code == campaign_code)
    if batch_date:
        q = q.filter(ReviewEntry.batch_date == batch_date)
    entries = q.all()

    campaigns = {c.code: c for c in db.query(ReviewCampaign).all()}
    result = []
    for e in entries:
        d = {col.name: getattr(e, col.name) for col in e.__table__.columns}
        camp = campaigns.get(e.campaign_code)
        d["product_name"] = camp.name if camp else None
        d["product_sku"] = camp.product_sku if camp else None
        result.append(d)
    return result


@router.patch("/entries/{entry_id}/status")
def update_entry_status(entry_id: int, data: EntryStatusIn, db: Session = Depends(get_db)):
    e = db.query(ReviewEntry).filter(ReviewEntry.id == entry_id).first()
    if not e:
        raise HTTPException(404)
    e.status = data.status
    db.commit()
    db.refresh(e)
    return e

@router.patch("/entries/{entry_id}/notes")
def update_entry_notes(entry_id: int, data: EntryNotesIn, db: Session = Depends(get_db)):
    e = db.query(ReviewEntry).filter(ReviewEntry.id == entry_id).first()
    if not e:
        raise HTTPException(404)
    e.notes = data.notes
    db.commit()
    db.refresh(e)
    return e

@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    e = db.query(ReviewEntry).filter(ReviewEntry.id == entry_id).first()
    if not e:
        raise HTTPException(404)
    db.delete(e)
    db.commit()
    return {"ok": True}


# ── CSV Export (Shift-JIS for shipping) ──────────────────
@router.get("/entries/export")
def export_entries(
    status: str = "confirmed",
    batch_date: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(ReviewEntry).filter(ReviewEntry.status == status)
    if batch_date:
        q = q.filter(ReviewEntry.batch_date == batch_date)
    entries = q.order_by(ReviewEntry.campaign_code, ReviewEntry.id).all()

    campaigns = {c.code: c for c in db.query(ReviewCampaign).all()}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "受注番号", "送付先郵便番号1", "送付先郵便番号2",
        "送付先住所都道府県", "送付先住所郡市区", "送付先住所それ以降の住所",
        "送付先姓", "送付先名",
        "商品名", "キャンペーンコード", "商品名2",
        "個数", "送付先電話番号1", "送付先電話番号2", "送付先電話番号3",
    ])
    for e in entries:
        camp = campaigns.get(e.campaign_code)
        product = camp.name if camp else e.campaign_name
        writer.writerow([
            e.order_number, e.zip1, e.zip2,
            e.prefecture, e.city, e.address,
            e.last_name, e.first_name,
            e.campaign_name, e.campaign_code, e.campaign_name,
            e.quantity, e.phone1, e.phone2, e.phone3,
        ])

    content = buf.getvalue().encode("cp932", errors="replace")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=shift_jis",
        headers={"Content-Disposition": f"attachment; filename=review_export_{date.today().isoformat()}.csv"},
    )


# ── Batch status update ─────────────────────────────────
@router.post("/entries/bulk-status")
def bulk_status(ids: str = Query(...), status: str = Query(...), db: Session = Depends(get_db)):
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    updated = 0
    for entry_id in id_list:
        e = db.query(ReviewEntry).filter(ReviewEntry.id == entry_id).first()
        if e:
            e.status = status
            updated += 1
    db.commit()
    return {"updated": updated}


# ── RMS 問い合わせ取得 ───────────────────────────────────

def _detect_campaign(message: str, item_name: str, campaigns: list) -> str | None:
    text = (message or "") + " " + (item_name or "")
    text_lower = text.lower()
    # (keyword, code) のリストを長いキーワード優先で並べる
    kw_code: list[tuple[str, str]] = []
    for c in campaigns:
        if not c.is_active or not c.keywords:
            continue
        for kw in [k.strip() for k in c.keywords.split(",") if k.strip()]:
            kw_code.append((kw, c.code))
    kw_code.sort(key=lambda x: len(x[0]), reverse=True)
    for kw, code in kw_code:
        if kw.lower() in text_lower:
            return code
    return None


@router.get("/inquiries")
async def fetch_inquiries(
    from_date: str = Query(None),
    to_date: str = Query(None),
    review_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    settings = db.query(RakutenSettings).first()
    if not settings or not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません")

    now = datetime.now(JST)
    if not from_date:
        from_date = (now - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00")
    if not to_date:
        to_date = now.strftime("%Y-%m-%dT%H:%M:%S")

    headers = {
        **_auth_header(settings.rms_service_secret, settings.rms_license_key),
        "Content-Type": "application/json; charset=utf-8",
    }

    all_inquiries = []
    page = 1
    while True:
        url = (
            f"{RMS_BASE}/1.0/inquirymng-api/inquiries"
            f"?fromDate={from_date}&toDate={to_date}&limit=100&page={page}"
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.get(url, headers=headers)
                if not res.is_success:
                    break
                data = res.json()
        except Exception as e:
            raise HTTPException(500, f"RMS問い合わせ取得失敗: {e}")

        inquiries = data.get("list") or []
        if not inquiries:
            break
        all_inquiries.extend(inquiries)
        total_pages = data.get("totalPageCount", 1)
        if page >= total_pages:
            break
        page += 1

    campaigns_list = db.query(ReviewCampaign).order_by(ReviewCampaign.code).all()
    campaigns = {c.code: c for c in campaigns_list}
    existing_orders = {
        e.order_number
        for e in db.query(ReviewEntry.order_number).all()
    }

    results = []
    for inq in all_inquiries:
        # R-Messeで完了済みのものだけ表示しない（未返信・返信済は表示する）
        if inq.get("isCompleted", False):
            continue

        message = inq.get("message") or ""
        item_name = inq.get("itemName") or ""
        order_number = inq.get("orderNumber") or ""
        detected = _detect_campaign(message, item_name, campaigns_list)

        # review_only指定時のみレビュー関連（キーワードorキャンペーン判定あり）に絞る
        if review_only:
            has_review_keyword = any(
                kw in message for kw in ["レビュー", "れびゅー", "review", "プレゼント"]
            )
            if not has_review_keyword and not detected:
                continue

        results.append({
            "inquiry_number": inq.get("inquiryNumber"),
            "order_number": order_number,
            "user_name": inq.get("userName"),
            "message": message,
            "item_name": item_name,
            "item_number": inq.get("itemNumber"),
            "category": inq.get("category"),
            "reg_date": inq.get("regDate"),
            "is_completed": inq.get("isCompleted", False),
            "detected_campaign": detected,
            "detected_campaign_name": campaigns[detected].name if detected and detected in campaigns else None,
            "already_registered": order_number in existing_orders if order_number else False,
        })

    return {"inquiries": results, "total": len(results)}


# ── 問い合わせ詳細（やり取り全体） ───────────────────────
async def _fetch_inquiry_detail(inquiry_number: str, headers: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.get(
                f"{RMS_BASE}/1.0/inquirymng-api/inquiry/{inquiry_number}",
                headers=headers,
            )
        if res.status_code == 404:
            raise HTTPException(404, "問い合わせが見つかりません")
        if not res.is_success:
            raise HTTPException(502, f"RMS APIエラー: {res.status_code}")
        return (res.json() or {}).get("result") or {}
    except httpx.HTTPError as e:
        raise HTTPException(502, f"RMS API 通信エラー: {e}")


@router.get("/inquiry/{inquiry_number}")
async def get_inquiry_detail(inquiry_number: str, db: Session = Depends(get_db)):
    settings = db.query(RakutenSettings).first()
    if not settings or not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません")

    headers = {
        **_auth_header(settings.rms_service_secret, settings.rms_license_key),
        "Content-Type": "application/json; charset=utf-8",
    }
    result = await _fetch_inquiry_detail(inquiry_number, headers)

    # 最初の問い合わせ＋返信を時系列スレッドにまとめる
    thread = [{
        "from": "user",
        "message": result.get("message") or "",
        "date": result.get("regDate"),
        "deleted": result.get("isMessageDeleted", False),
    }]
    for r in result.get("replies") or []:
        thread.append({
            "from": r.get("replyFrom"),  # merchant / user
            "message": r.get("message") or "",
            "date": r.get("regDate"),
            "deleted": r.get("isMessageDeleted", False),
        })

    return {
        "inquiry_number": result.get("inquiryNumber"),
        "user_name": result.get("userName"),
        "item_name": result.get("itemName"),
        "order_number": result.get("orderNumber"),
        "is_completed": result.get("isCompleted", False),
        "category": result.get("category"),
        "type": result.get("type"),
        "thread": thread,
    }


# ── 返信送信（R-Messe連動） ──────────────────────────────
@router.post("/inquiry/reply")
async def post_inquiry_reply(data: ReplyIn, db: Session = Depends(get_db)):
    settings = db.query(RakutenSettings).first()
    if not settings or not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません")

    message = (data.message or "").strip()
    if not message:
        raise HTTPException(400, "メッセージが空です")
    if len(message) > 2000:
        raise HTTPException(400, "メッセージは2000文字以内にしてください")
    for line in message.split("\n"):
        if len(line) > 300:
            raise HTTPException(400, "1行は300文字以内にしてください")

    headers = {
        **_auth_header(settings.rms_service_secret, settings.rms_license_key),
        "Content-Type": "application/json; charset=utf-8",
    }

    # reply.postに必要なshopIdを問い合わせ詳細から取得
    detail = await _fetch_inquiry_detail(data.inquiry_number, headers)
    shop_id = detail.get("shopId")
    if shop_id is None:
        raise HTTPException(502, "shopIdが取得できませんでした")

    body = {
        "inquiryNumber": data.inquiry_number,
        "shopId": str(shop_id),
        "message": message,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"{RMS_BASE}/1.0/inquirymng-api/inquiry/reply",
                headers=headers,
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            )
        if res.status_code not in (200, 201):
            try:
                err = res.json()
            except Exception:
                err = res.text
            raise HTTPException(502, f"返信登録に失敗しました: {err}")
        result = (res.json() or {}).get("result") or {}
    except httpx.HTTPError as e:
        raise HTTPException(502, f"RMS API 通信エラー: {e}")

    return {
        "ok": True,
        "message": result.get("message"),
        "reg_date": result.get("regDate"),
    }


# ── 問い合わせを完了にする（R-Messe連動） ────────────────
@router.post("/inquiries/complete")
async def complete_inquiries(data: InquiryCompleteIn, db: Session = Depends(get_db)):
    settings = db.query(RakutenSettings).first()
    if not settings or not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません")

    nums = [n.strip() for n in data.inquiry_numbers if n and n.strip()]
    if not nums:
        raise HTTPException(400, "問い合わせ番号が指定されていません")

    headers = {
        **_auth_header(settings.rms_service_secret, settings.rms_license_key),
        "Content-Type": "application/json; charset=utf-8",
    }

    ok: list[str] = []
    errors: list[dict] = []
    # RMS仕様: 1リクエスト最大20件、1秒1リクエスト
    import asyncio
    for i in range(0, len(nums), 20):
        batch = nums[i:i + 20]
        if i > 0:
            await asyncio.sleep(1.1)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.patch(
                    f"{RMS_BASE}/1.0/inquirymng-api/inquiries/complete",
                    headers=headers,
                    content=json.dumps({"inquiryNumbers": batch}).encode("utf-8"),
                )
            if res.is_success:
                result = (res.json() or {}).get("result") or {}
                ok.extend(result.get("ok") or [])
                for err in result.get("error") or []:
                    errors.append({
                        "inquiry_number": err.get("inquiryNumber"),
                        "message": err.get("errorMessage"),
                    })
            else:
                for n in batch:
                    errors.append({"inquiry_number": n, "message": f"RMS APIエラー: {res.status_code}"})
        except httpx.HTTPError as e:
            for n in batch:
                errors.append({"inquiry_number": n, "message": f"通信エラー: {e}"})

    return {"ok": ok, "errors": errors}


# ── 受注番号から送付先住所を取得 ─────────────────────────
@router.get("/order-address/{order_number}")
async def get_order_address(order_number: str, db: Session = Depends(get_db)):
    settings = db.query(RakutenSettings).first()
    if not settings or not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません")

    headers = {
        **_auth_header(settings.rms_service_secret, settings.rms_license_key),
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"{RMS_BASE}/2.0/order/getOrder",
                headers=headers,
                content=json.dumps(
                    {"orderNumberList": [order_number], "version": 10},
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            if not res.is_success:
                raise HTTPException(502, f"RMS API エラー: {res.status_code}")
            data = res.json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"RMS API 通信エラー: {e}")

    orders = data.get("OrderModelList") or []
    if not orders:
        raise HTTPException(404, "受注が見つかりません")

    order = orders[0]
    packages = order.get("PackageModelList") or []

    items = []
    for pkg in packages:
        for item in pkg.get("ItemModelList") or []:
            items.append({
                "item_name": item.get("itemName"),
                "item_number": item.get("itemNumber"),
                "units": item.get("units", 1),
            })

    # 送付先住所（PackageModelの送付先）
    ship = {}
    if packages:
        sender = packages[0].get("SenderModel") or {}
        ship = {
            "zip1": sender.get("zipCode1", ""),
            "zip2": sender.get("zipCode2", ""),
            "prefecture": sender.get("prefecture", ""),
            "city": sender.get("city", ""),
            "address": sender.get("subAddress", ""),
            "last_name": sender.get("familyName", ""),
            "first_name": sender.get("firstName", ""),
            "phone1": sender.get("phoneNumber1", ""),
            "phone2": sender.get("phoneNumber2", ""),
            "phone3": sender.get("phoneNumber3", ""),
        }

    # 注文者情報
    orderer = order.get("OrdererModel") or {}
    buyer = {
        "name": f"{orderer.get('familyName', '')} {orderer.get('firstName', '')}".strip(),
        "prefecture": orderer.get("prefecture", ""),
    }

    return {
        "order_number": order_number,
        "shipping": ship,
        "buyer": buyer,
        "items": items,
        "buyer_differs": ship.get("last_name", "") != orderer.get("familyName", ""),
    }
