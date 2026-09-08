"""輸入許可書の保管。

通関業者から届く許可書をメールから拾ってツールへ入れ、
税理士へ渡すときにまとめて書き出せるようにする。

原本のPDFをそのまま持つ。読み取った金額は一覧で見分けるためのもので、
原価の按分は今までどおり仕入管理側で行う（数字を二重に持たない）。
"""
import io
import zipfile
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, defer

from app.core.database import get_db
from app.models.import_permit import ImportPermit
from app.services import google_drive, permit_mail

router = APIRouter(prefix="/import-permits", tags=["import_permits"])


def _brief(p: ImportPermit) -> dict:
    return {
        "id": p.id,
        "permit_no": p.permit_no,
        "permit_date": p.permit_date,
        "permit_cny": p.permit_cny,
        "exchange_rate": p.exchange_rate,
        "total_tax": p.total_tax,
        "customs_duty": p.customs_duty,
        "consumption_tax": p.consumption_tax,
        "local_consumption_tax": p.local_consumption_tax,
        "filename": p.filename,
        "size_bytes": p.size_bytes,
        "source": p.source,
        "mail_subject": p.mail_subject,
        "mail_from": p.mail_from,
        "mail_date": p.mail_date,
        "drive_url": p.drive_url,
        "note": p.note,
        "created_at": p.created_at,
    }


def _sort_date(p: ImportPermit) -> str:
    """並べ替えと絞り込みに使う日付。

    許可年月日が読めなかったPDFはメールの日付で代える。どちらも無ければ
    末尾に置く（消えてしまうより、日付なしとして見えているほうがよい）。
    """
    return p.permit_date or p.mail_date or ""


def _rows(db: Session):
    """一覧用。PDF本体は読まない。

    毎回すべてのPDFを引くと通信量がすぐ上限に当たる（Supabaseの無料枠で
    実際に超過したことがある）。本体は開くときだけ読む。
    """
    return db.query(ImportPermit).options(defer(ImportPermit.pdf)).all()


@router.get("/")
def list_permits(year: Optional[int] = None, month: Optional[int] = None,
                 db: Session = Depends(get_db)):
    rows = _rows(db)
    rows = [p for p in rows if _matches(p, year, month)]
    rows.sort(key=lambda p: (_sort_date(p) or "0000", p.id), reverse=True)
    return {
        "items": [_brief(p) for p in rows],
        "total_tax": sum(int(p.total_tax or 0) for p in rows),
        "drive_ready": google_drive.is_configured(),
    }


def _matches(p: ImportPermit, year, month) -> bool:
    d = _sort_date(p)
    if year and not d.startswith(f"{year:04d}"):
        return False
    if month and d[5:7] != f"{month:02d}":
        return False
    return True


@router.get("/folders")
def folders():
    """メールのフォルダ一覧。振り分けている場合に選んでもらう。"""
    try:
        return {"items": permit_mail.list_folders()}
    except permit_mail.PermitMailError as e:
        raise HTTPException(status_code=502, detail=str(e))


class FetchIn(BaseModel):
    days: int = 60
    to_drive: bool = False
    # 空なら受信トレイ、"*" ならごみ箱などを除く全フォルダ
    folder: str = ""


@router.post("/fetch-mail")
def fetch_mail(data: FetchIn, db: Session = Depends(get_db)):
    """卸発注のメールを見て、輸入許可書のPDFを取り込む。

    同じ添付を二度入れないよう、メールのMessage-IDと添付名で見分ける。
    何度押しても増えないので、迷ったら押してよい。
    """
    try:
        found = permit_mail.scan(days=data.days, folder=data.folder)
    except permit_mail.PermitMailError as e:
        raise HTTPException(status_code=502, detail=str(e))

    known = {(p.mail_message_id, p.filename)
             for p in db.query(ImportPermit.mail_message_id,
                               ImportPermit.filename).all()}
    added, drive_errors = [], []
    for row in found:
        key = (row["mail_message_id"], row["filename"])
        if key in known:
            continue
        known.add(key)
        p = ImportPermit(**row)
        db.add(p)
        db.flush()
        added.append(p)

    # 置き先が設定されていれば控えも送る。ここで失敗しても取り込みは残す
    if data.to_drive and added and google_drive.is_configured():
        for p in added:
            try:
                d = google_drive.upload_pdf(_drive_name(p), p.pdf)
                p.drive_file_id, p.drive_url = d["file_id"], d["url"]
            except google_drive.DriveError as e:
                drive_errors.append(f"{p.filename}: {e}")

    db.commit()
    return {
        "scanned": len(found),
        "added": len(added),
        "skipped": len(found) - len(added),
        "items": [_brief(p) for p in added],
        "drive_errors": drive_errors,
    }


@router.get("/scan-candidates")
def scan_candidates(days: int = 60, folder: str = ""):
    """PDFの添付を並べる（拾えなかったときの調査用）。"""
    try:
        return {"items": permit_mail.scan_candidates(days=days, folder=folder)}
    except permit_mail.PermitMailError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/upload")
async def upload_permit(file: UploadFile = File(...),
                        db: Session = Depends(get_db)):
    """手元のPDFを直接入れる。メールで届かなかったぶんの補い。"""
    content = await file.read()
    parsed = permit_mail.parse_permit_pdf(content)
    is_permit = parsed.pop("is_permit")
    p = ImportPermit(**parsed, filename=file.filename or "permit.pdf",
                     size_bytes=len(content), pdf=content, source="upload",
                     mail_message_id=f"upload:{datetime.now().isoformat()}")
    db.add(p)
    db.commit()
    db.refresh(p)
    # 許可書に見えなくても入れる。体裁が変わっただけのこともあるので、
    # 弾くより「読めなかった」と伝えて人に判断してもらう
    return {**_brief(p), "looks_like_permit": is_permit}


def _drive_name(p: ImportPermit) -> str:
    """ドライブでの名前。日付が頭に付いていないと年度ごとに探せない。"""
    d = _sort_date(p) or "日付不明"
    no = f"_{p.permit_no}" if p.permit_no else ""
    return f"{d}_輸入許可書{no}.pdf"


@router.post("/{permit_id}/to-drive")
def to_drive(permit_id: int, db: Session = Depends(get_db)):
    p = db.query(ImportPermit).filter(ImportPermit.id == permit_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="見つかりません")
    try:
        d = google_drive.upload_pdf(_drive_name(p), p.pdf)
    except google_drive.DriveError as e:
        raise HTTPException(status_code=502, detail=str(e))
    p.drive_file_id, p.drive_url = d["file_id"], d["url"]
    db.commit()
    return {"drive_url": p.drive_url}


@router.get("/{permit_id}/pdf")
def download_pdf(permit_id: int, db: Session = Depends(get_db)):
    p = db.query(ImportPermit).filter(ImportPermit.id == permit_id).first()
    if not p or not p.pdf:
        raise HTTPException(status_code=404, detail="見つかりません")
    return StreamingResponse(io.BytesIO(p.pdf), media_type="application/pdf")


@router.get("/zip")
def download_zip(year: Optional[int] = None, month: Optional[int] = None,
                 db: Session = Depends(get_db)):
    """まとめて書き出す。税理士へ渡すのはこれ1つで足りる。"""
    rows = [p for p in _rows(db) if _matches(p, year, month)]
    if not rows:
        raise HTTPException(status_code=404, detail="対象の許可書がありません")
    rows.sort(key=_sort_date)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        used = set()
        for p in rows:
            name = _drive_name(p)
            # 同じ日に2便あると名前がぶつかる。上書きすると片方が消える
            i = 2
            while name in used:
                name = f"{_drive_name(p)[:-4]}_{i}.pdf"
                i += 1
            used.add(name)
            z.writestr(name, p.pdf or b"")
    buf.seek(0)

    span = f"{year}" if year else "全期間"
    if year and month:
        span = f"{year}-{month:02d}"
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="import-permits-{span}.zip"'})


class NoteIn(BaseModel):
    note: str = ""


@router.patch("/{permit_id}")
def update_note(permit_id: int, data: NoteIn, db: Session = Depends(get_db)):
    p = db.query(ImportPermit).filter(ImportPermit.id == permit_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="見つかりません")
    p.note = data.note
    db.commit()
    return _brief(p)


@router.delete("/{permit_id}")
def delete_permit(permit_id: int, db: Session = Depends(get_db)):
    p = db.query(ImportPermit).filter(ImportPermit.id == permit_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="見つかりません")
    db.delete(p)
    db.commit()
    return {"ok": True}
