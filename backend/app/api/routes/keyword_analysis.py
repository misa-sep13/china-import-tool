import csv
import io
import json
import re
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.keyword_analysis import KeywordUpload, KeywordData, TitleOptimization
from app.models.rakuten_settings import RakutenSettings
from app.services.rakuten_rms import _auth_header, RMS_BASE
import httpx

router = APIRouter(prefix="/keyword-analysis", tags=["keyword-analysis"])
JST = timezone(timedelta(hours=9))


# ── Schemas ──────────────────────────────────────────────
class TitleUpdateIn(BaseModel):
    suggested_title: str

class TitleStatusIn(BaseModel):
    status: str  # approved / skipped

class PushIn(BaseModel):
    manage_number: str


# ── CSV Upload ───────────────────────────────────────────
@router.post("/upload")
async def upload_keyword_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    raw = await file.read()
    text = None
    for enc in ("shift_jis", "cp932", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise HTTPException(400, "ファイルのエンコーディングを認識できません")

    lines = text.splitlines()
    if len(lines) < 3:
        raise HTTPException(400, "CSVの行数が不足しています")

    period_from = ""
    period_to = ""
    period_row = list(csv.reader([lines[1]]))[0]
    if len(period_row) >= 2:
        m = re.search(r"(\d{4}/\d{2}/\d{2})\s*〜\s*(\d{4}/\d{2}/\d{2})", period_row[1])
        if m:
            period_from = m.group(1)
            period_to = m.group(2)

    reader = csv.reader(lines[3:])
    rows = list(reader)

    upload = KeywordUpload(
        period_from=period_from,
        period_to=period_to,
    )
    db.add(upload)
    db.flush()

    product_nos = set()
    kw_count = 0
    current_name = ""
    current_total = 0

    for row in rows:
        if len(row) < 7:
            continue
        no_str = row[0].strip()
        if not no_str.isdigit():
            continue
        no = int(no_str)
        product_nos.add(no)

        if row[1].strip():
            current_name = row[1].strip()
        if row[2].strip():
            current_total = int(row[2].strip())

        keyword = row[3].strip()
        if not keyword:
            continue

        access = int(row[4].strip()) if row[4].strip() else 0
        cvr = float(row[5].strip()) if row[5].strip() else 0.0
        rank = row[6].strip()

        action_access = len(row) > 7 and "アクセス" in (row[7] or "")
        action_cvr = len(row) > 8 and "転換率" in (row[8] or "")
        action_good = len(row) > 9 and "Good" in (row[9] or "")

        kd = KeywordData(
            upload_id=upload.id,
            product_no=no,
            product_name=current_name,
            total_access=current_total,
            keyword=keyword,
            access=access,
            cvr=cvr,
            rank=rank,
            action_access=action_access,
            action_cvr=action_cvr,
            action_good=action_good,
        )
        db.add(kd)
        kw_count += 1

    upload.product_count = len(product_nos)
    upload.keyword_count = kw_count
    db.commit()

    return {
        "upload_id": upload.id,
        "period": f"{period_from} 〜 {period_to}",
        "products": len(product_nos),
        "keywords": kw_count,
    }


# ── アップロード一覧 ─────────────────────────────────────
@router.get("/uploads")
def list_uploads(db: Session = Depends(get_db)):
    uploads = db.query(KeywordUpload).order_by(KeywordUpload.id.desc()).all()
    return [{
        "id": u.id,
        "uploaded_at": u.uploaded_at.isoformat() if u.uploaded_at else None,
        "period_from": u.period_from,
        "period_to": u.period_to,
        "product_count": u.product_count,
        "keyword_count": u.keyword_count,
    } for u in uploads]


# ── 指定アップロードの商品別キーワード ─────────────────────
@router.get("/data/{upload_id}")
def get_keyword_data(upload_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(KeywordData)
        .filter(KeywordData.upload_id == upload_id)
        .order_by(KeywordData.product_no, KeywordData.access.desc())
        .all()
    )
    products = {}
    for r in rows:
        if r.product_no not in products:
            products[r.product_no] = {
                "no": r.product_no,
                "name": r.product_name,
                "total_access": r.total_access,
                "keywords": [],
            }
        products[r.product_no]["keywords"].append({
            "keyword": r.keyword,
            "access": r.access,
            "cvr": r.cvr,
            "rank": r.rank,
            "action_access": r.action_access,
            "action_cvr": r.action_cvr,
            "action_good": r.action_good,
        })

    opts = (
        db.query(TitleOptimization)
        .filter(TitleOptimization.upload_id == upload_id)
        .all()
    )
    opt_map = {o.product_no: {
        "id": o.id,
        "current_title": o.current_title,
        "suggested_title": o.suggested_title,
        "reasoning": o.reasoning,
        "status": o.status,
        "pushed_at": o.pushed_at.isoformat() if o.pushed_at else None,
    } for o in opts}

    result = []
    for no in sorted(products.keys()):
        p = products[no]
        p["optimization"] = opt_map.get(no)
        result.append(p)
    return result


# ── AI タイトル改善提案 ──────────────────────────────────
@router.post("/suggest/{upload_id}")
def suggest_titles(upload_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(KeywordData)
        .filter(KeywordData.upload_id == upload_id)
        .order_by(KeywordData.product_no, KeywordData.access.desc())
        .all()
    )
    if not rows:
        raise HTTPException(404, "データが見つかりません")

    products = {}
    for r in rows:
        if r.product_no not in products:
            products[r.product_no] = {
                "name": r.product_name,
                "total_access": r.total_access,
                "keywords": [],
            }
        products[r.product_no]["keywords"].append({
            "keyword": r.keyword,
            "access": r.access,
            "cvr": r.cvr,
            "rank": r.rank,
            "action_access": r.action_access,
            "action_cvr": r.action_cvr,
            "action_good": r.action_good,
        })

    db.query(TitleOptimization).filter(TitleOptimization.upload_id == upload_id).delete()

    results = []
    for no in sorted(products.keys()):
        p = products[no]
        title = p["name"]
        suggested, reasoning = _optimize_title(title, p["keywords"])

        opt = TitleOptimization(
            upload_id=upload_id,
            product_no=no,
            product_name=p["name"],
            current_title=title,
            suggested_title=suggested,
            reasoning=reasoning,
            status="pending",
        )
        db.add(opt)
        db.flush()
        results.append({
            "id": opt.id,
            "product_no": no,
            "current_title": title,
            "suggested_title": suggested,
            "reasoning": reasoning,
        })

    db.commit()
    return results


def _optimize_title(title: str, keywords: list) -> tuple[str, str]:
    """CVRとアクセス数を考慮してタイトルを最適化する。
    スコア = access * (cvr / 100) でキーワードをランク付けし、
    タイトルに未使用のキーワード単語を左側に挿入する。
    楽天商品名は全角127文字以内。"""
    MAX_LEN = 127

    title_flat = title.replace(" ", "").replace("　", "").lower()

    scored = []
    for kw in keywords:
        parts = re.split(r"[\s　]+", kw["keyword"])
        missing_parts = [p for p in parts if p.lower() not in title_flat]
        if not missing_parts:
            continue
        score = kw["access"] * (kw["cvr"] / 100) if kw["cvr"] > 0 else kw["access"] * 0.01
        scored.append({
            "keyword": kw["keyword"],
            "missing_parts": missing_parts,
            "access": kw["access"],
            "cvr": kw["cvr"],
            "score": score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    added = []
    new_title = title
    reasons = []

    for s in scored:
        for part in s["missing_parts"]:
            if part.lower() in new_title.replace(" ", "").replace("　", "").lower():
                continue
            candidate = part + " " + new_title
            if len(candidate) <= MAX_LEN:
                new_title = candidate
                added.append(part)
                reasons.append(
                    f"「{s['keyword']}」(アクセス{s['access']}, CVR{s['cvr']}%) → 「{part}」追加"
                )

    if not added:
        return title, "変更不要: すべてのキーワードがタイトルに含まれています"

    reasoning = "; ".join(reasons)
    return new_title, reasoning


# ── 改善案を手動修正 ─────────────────────────────────────
@router.put("/optimization/{opt_id}")
def update_optimization(opt_id: int, data: TitleUpdateIn, db: Session = Depends(get_db)):
    opt = db.query(TitleOptimization).filter(TitleOptimization.id == opt_id).first()
    if not opt:
        raise HTTPException(404)
    opt.suggested_title = data.suggested_title
    db.commit()
    db.refresh(opt)
    return {"ok": True, "suggested_title": opt.suggested_title}


# ── ステータス変更（承認/スキップ）─────────────────────────
@router.patch("/optimization/{opt_id}/status")
def update_optimization_status(opt_id: int, data: TitleStatusIn, db: Session = Depends(get_db)):
    opt = db.query(TitleOptimization).filter(TitleOptimization.id == opt_id).first()
    if not opt:
        raise HTTPException(404)
    opt.status = data.status
    db.commit()
    return {"ok": True, "status": opt.status}


# ── RMS Push（承認済み → 楽天に反映） ────────────────────
@router.post("/push/{opt_id}")
async def push_title_to_rms(opt_id: int, data: PushIn, db: Session = Depends(get_db)):
    opt = db.query(TitleOptimization).filter(TitleOptimization.id == opt_id).first()
    if not opt:
        raise HTTPException(404)
    if opt.status != "approved":
        raise HTTPException(400, "承認済みの提案のみPush可能です")

    settings_row = db.query(RakutenSettings).first()
    if not settings_row or not settings_row.rms_service_secret or not settings_row.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません")

    headers = {
        **_auth_header(settings_row.rms_service_secret, settings_row.rms_license_key),
        "Content-Type": "application/json; charset=utf-8",
    }

    body = {
        "items": [{
            "manageNumber": data.manage_number,
            "item": {
                "title": opt.suggested_title
            }
        }]
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.patch(
                f"{RMS_BASE}/2.0/items",
                headers=headers,
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            )
        if res.status_code not in (200, 204):
            try:
                err = res.json()
            except Exception:
                err = res.text
            raise HTTPException(502, f"RMS API エラー: {err}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"RMS API 通信エラー: {e}")

    opt.status = "pushed"
    opt.pushed_at = datetime.now(JST)
    db.commit()

    return {"ok": True, "manage_number": data.manage_number, "new_title": opt.suggested_title}
