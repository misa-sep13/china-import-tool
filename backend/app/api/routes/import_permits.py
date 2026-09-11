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
        "kind": p.kind or "permit",
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


def _dedupe(rows: list) -> list:
    """申告番号が同じものは1つにする。

    同じ許可書が2通のメール（送付と再送）で届くことがあり、そのまま貯めると
    税理士へ渡すZIPに同じPDFが2つ入る。古いほう（先に取り込んだもの）を残す。
    番号を読めなかったものは、別物として全部残す（消すより多いほうが安全）。
    """
    seen, out = set(), []
    for p in sorted(rows, key=lambda x: x.id):
        no = (p.permit_no or "").strip()
        key = ((p.kind or "permit"), no)
        if no and key in seen:
            continue
        if no:
            seen.add(key)
        out.append(p)
    return out


def _rows(db: Session):
    """一覧用。PDF本体は読まない。

    毎回すべてのPDFを引くと通信量がすぐ上限に当たる（Supabaseの無料枠で
    実際に超過したことがある）。本体は開くときだけ読む。
    """
    return db.query(ImportPermit).options(defer(ImportPermit.pdf)).all()


@router.get("/")
def list_permits(year: Optional[int] = None, month: Optional[int] = None,
                 kind: Optional[str] = None, db: Session = Depends(get_db)):
    rows = _rows(db)
    rows = [p for p in rows if _matches(p, year, month)
            and (not kind or (p.kind or "permit") == kind)]
    keep = {p.id for p in _dedupe(rows)}
    rows.sort(key=lambda p: (_sort_date(p) or "0000", p.id), reverse=True)
    return {
        "items": [dict(_brief(p), duplicate=p.id not in keep) for p in rows],
        # 合計は重複を除いた数字。二重に足すと税額が合わなくなる
        "total_tax": sum(int(p.total_tax or 0) for p in _dedupe(rows)
                         if (p.kind or "permit") == "permit"),
        "duplicates": len(rows) - len(keep),
        "counts": {"permit": sum(1 for p in rows if (p.kind or "permit") == "permit"),
                   "invoice": sum(1 for p in rows if p.kind == "invoice")},
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
    stats = {}
    try:
        found = permit_mail.scan(days=data.days, folder=data.folder, stats=stats)
    except permit_mail.PermitMailError as e:
        raise HTTPException(status_code=502, detail=str(e))

    known = {(p.mail_message_id, p.filename)
             for p in db.query(ImportPermit.mail_message_id,
                               ImportPermit.filename).all()}
    # 同じ許可書が別のメールで再送されることがある。添付が違っても
    # 申告番号が同じなら同じ書類なので入れない
    known_no = {(p.permit_no or "").strip()
                for p in db.query(ImportPermit.permit_no)
                .filter(ImportPermit.kind == "permit").all()
                if (p.permit_no or "").strip()}
    added, drive_errors = [], []
    for row in found:
        key = (row["mail_message_id"], row["filename"])
        no = (row.get("permit_no") or "").strip()
        if key in known or (no and no in known_no):
            continue
        known.add(key)
        if no:
            known_no.add(no)
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
        # 0件だったときに、どこで止まったかが分かるように
        "stats": stats,
    }


class TaotaroInvoiceIn(BaseModel):
    # 新しいほうから何便ぶん見るか。ふだんは20で足りる
    limit: int = 20


@router.post("/fetch-taotaro-invoices")
def fetch_taotaro_invoices(data: TaotaroInvoiceIn, db: Session = Depends(get_db)):
    """タオタロウの請求書PDFを取り込む。

    請求書のダウンロードURLは期限付きなので、その場で落として保管する
    （仕様書もそう勧めている）。同じ便を二度入れないよう配送依頼IDで見分ける
    ので、何度押しても増えない。
    """
    from app.services import taotaro
    if not taotaro.is_configured():
        raise HTTPException(status_code=502,
                            detail="タオタロウのトークンが未設定です")
    try:
        d = taotaro.list_send_orders(page=1, limit=max(1, min(data.limit, 100)))
    except taotaro.TaotaroError as e:
        raise HTTPException(status_code=502, detail=e.message)

    known = {p.mail_message_id for p in
             db.query(ImportPermit.mail_message_id)
             .filter(ImportPermit.kind == "invoice").all()}
    added, skipped, not_ready = [], 0, []
    for x in d.get("items") or []:
        sid = x.get("sid")
        key = f"taotaro:invoice:{sid}"
        if not sid or key in known:
            skipped += 1
            continue
        # 発行前の便は毎回ここに来る。出荷前は請求書が無いのが普通なので
        # 失敗扱いにせず、名前だけ返して次に進む
        if not x.get("have_invoice"):
            not_ready.append(x.get("sn") or str(sid))
            continue
        try:
            fname, raw = taotaro.invoice_file(sid)
        except taotaro.TaotaroError as e:
            not_ready.append(f"{x.get('sn') or sid}（{e.message}）")
            continue
        known.add(key)
        p = ImportPermit(
            kind="invoice",
            permit_no=str(x.get("sn") or sid),
            # 請求書に許可日は無いので、便の更新日を日付として使う
            permit_date=str(x.get("updated_at") or "")[:10],
            # 仕様書はPDFと書いているが、実際に落ちてくるのはExcelのことがある。
            # 拡張子を決め打ちすると、開けないファイルとして保管してしまう
            filename=f"{x.get('sn') or sid}{fname[fname.rfind('.'):]}",
            size_bytes=len(raw), pdf=raw, source="taotaro",
            mail_message_id=key,
            mail_subject=f"タオタロウ請求書 {x.get('sn') or sid}",
            mail_from="タオタロウ",
            mail_date=str(x.get("updated_at") or "")[:10],
            note=(f"費用合計 {x.get('total_send_fee')}元"
                  if x.get("total_send_fee") is not None else ""),
        )
        db.add(p)
        db.flush()
        added.append(p)
    db.commit()
    return {
        "added": len(added), "skipped": skipped,
        "not_ready": not_ready[:10],
        "items": [_brief(p) for p in added],
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
    """保存するときの名前。日付が頭に付いていないと年度ごとに探せない。

    許可書と請求書が同じ棚に入るので、種別も名前に入れる。
    """
    d = _sort_date(p) or "日付不明"
    label = "請求書" if p.kind == "invoice" else "輸入許可書"
    no = f"_{p.permit_no}" if p.permit_no else ""
    # 請求書はExcelで落ちてくることがある。拡張子は保管したものに合わせる
    name = (p.filename or "")
    ext = name[name.rfind("."):] if "." in name else ".pdf"
    return f"{d}_{label}{no}{ext}"


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
                 kind: Optional[str] = None, db: Session = Depends(get_db)):
    """まとめて書き出す。税理士へ渡すのはこれ1つで足りる。"""
    rows = _dedupe([p for p in _rows(db) if _matches(p, year, month)
                    and (not kind or (p.kind or "permit") == kind)])
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
                base = _drive_name(p)
                stem, dot, ext = base.rpartition(".")
                name = f"{stem}_{i}.{ext}" if dot else f"{base}_{i}"
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
