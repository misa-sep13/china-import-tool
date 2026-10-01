"""画像作成の依頼一覧。

リサーチシートから指示書をチャットワークへ送ると1件できる。送ったあとは
「誰に何を頼んでいて、いまどうなっているか」を追える場所が無く、
チャットの履歴をさかのぼるしかなかった。

外注さんには合言葉つきのURLでこの一覧だけを見せる。進み具合は本人に
変えてもらう（毎回こちらへ連絡してもらわなくて済む）。合言葉で通るのは
このAPIだけで、他の画面には一切届かない。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func as sa_func
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.image_request import ImageRequest

router = APIRouter(prefix="/image-requests", tags=["image-requests"])

# 依頼を出してから手を離れるまで。done になったら作業中の一覧から消える
STATUSES = ["requested", "working", "review", "done"]
STATUS_LABEL = {
    "requested": "依頼済",
    "working": "作業中",
    "review": "確認待ち",
    "done": "完了",
}


def _out(r: ImageRequest) -> dict:
    return {
        "id": r.id,
        "source": r.source or "amazon",
        "research_id": r.research_id,
        "sku": r.sku or "",
        "name": r.name or "",
        "doc_name": r.doc_name or "",
        "detail": r.detail or "",
        "ref_url": r.ref_url or "",
        "main_url": r.main_url or "",
        "room_name": r.room_name or "",
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        "sort_order": r.sort_order if r.sort_order is not None else r.id,
        "status": r.status or "requested",
        "status_label": STATUS_LABEL.get(r.status or "requested", ""),
        "assignee": r.assignee or "",
        "due_date": r.due_date or "",
        "reply": r.reply or "",
        "deliverable_url": r.deliverable_url or "",
        "done_at": r.done_at.isoformat() if r.done_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _is_share(request: Request) -> bool:
    """合言葉つきで来ているか。外注さんの画面かどうかの判定に使う。"""
    from app.core.config import settings
    want = getattr(settings, "KEEP_SHARE_TOKEN", "") or ""
    got = (request.query_params.get("share")
           or request.headers.get("x-image-share") or "")
    if not (want and got):
        return False
    # 合言葉に + が入っていると、URLの?以降では空白として解釈される
    return got == want or got.replace(" ", "+") == want


@router.get("")
def list_requests(include_done: int = 0, db: Session = Depends(get_db)):
    """依頼の一覧。既定では完了を外す（作業中だけを見たいので）。"""
    q = db.query(ImageRequest).filter(ImageRequest.is_deleted == False)
    if not include_done:
        q = q.filter(ImageRequest.status != "done")
    # 新しく足したものが下に来るように、古い順。上下に動かした並びが
    # あればそちらを優先する（sort_order を入れていないものは作った順）
    rows = q.order_by(
        sa_func.coalesce(ImageRequest.sort_order, ImageRequest.id).asc(),
        ImageRequest.id.asc(),
    ).all()
    done = (db.query(ImageRequest)
            .filter(ImageRequest.is_deleted == False,
                    ImageRequest.status == "done").count())
    # 参考画像のidだけ添える。中身は <img> が別で読みに来る
    from app.models.image_request import ImageRequestPhoto as _Photo
    photos = {}
    ids = [r.id for r in rows]
    if ids:
        for pid, rid in (db.query(_Photo.id, _Photo.request_id)
                         .filter(_Photo.request_id.in_(ids))
                         .order_by(_Photo.sort_order, _Photo.id).all()):
            photos.setdefault(rid, []).append(pid)

    items = []
    for r in rows:
        d = _out(r)
        d["photos"] = photos.get(r.id, [])
        items.append(d)
    return {"items": items, "done_count": done,
            "statuses": [{"value": v, "label": STATUS_LABEL[v]} for v in STATUSES]}


class ImageRequestIn(BaseModel):
    source: str = "manual"
    research_id: Optional[str] = None
    sku: str = ""
    name: str = ""
    doc_name: str = ""
    detail: str = ""
    ref_url: str = ""
    main_url: str = ""
    room_id: Optional[str] = None
    room_name: str = ""
    assignee: str = ""
    due_date: str = ""
    # チャットワークへ送った直後に作る場合は True。送信時刻が入る
    sent: bool = False


@router.post("")
def create_request(data: ImageRequestIn, db: Session = Depends(get_db)):
    """1件足す。シートからの自動登録と、手で足す場合の両方で使う。"""
    if not (data.sku or "").strip() and not (data.name or "").strip():
        raise HTTPException(400, "SKUか商品名のどちらかは入れてください")
    row = ImageRequest(
        source=data.source or "manual",
        research_id=data.research_id,
        sku=(data.sku or "").strip(),
        name=(data.name or "").strip(),
        doc_name=(data.doc_name or "").strip(),
        detail=data.detail or "",
        ref_url=(data.ref_url or "").strip(),
        main_url=(data.main_url or "").strip(),
        room_id=data.room_id,
        room_name=(data.room_name or "").strip(),
        assignee=(data.assignee or "").strip(),
        due_date=(data.due_date or "").strip(),
        status="requested",
        sent_at=datetime.now(timezone.utc) if data.sent else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


class ImageRequestPatch(BaseModel):
    status: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    reply: Optional[str] = None
    deliverable_url: Optional[str] = None
    sku: Optional[str] = None
    name: Optional[str] = None
    detail: Optional[str] = None
    ref_url: Optional[str] = None
    main_url: Optional[str] = None
    # 依頼日。一覧を作る前に出した依頼を、実際に出した日に直せるように
    sent_at: Optional[str] = None


@router.patch("/{req_id:int}")
def update_request(req_id: int, data: ImageRequestPatch, request: Request,
                   db: Session = Depends(get_db)):
    """進み具合や連絡を書き換える。

    合言葉で入っている外注さんは、進み具合・納品先・連絡だけを触れる。
    依頼の中身（SKU・商品名・依頼内容）はこちらでしか変えられない。
    """
    row = db.query(ImageRequest).filter(ImageRequest.id == req_id).first()
    if not row:
        raise HTTPException(404, "見つかりません")

    guest = _is_share(request)
    allowed = {"status", "reply", "deliverable_url"} if guest else None

    for field, value in data.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if allowed is not None and field not in allowed:
            continue
        if field == "sent_at":
            # 画面からは YYYY-MM-DD で来る。日付だけ分かれば足りる
            try:
                row.sent_at = datetime.fromisoformat(str(value)[:10]).replace(
                    tzinfo=timezone.utc)
            except ValueError:
                raise HTTPException(400, "日付の形が違います（2026-09-11 の形で）")
            continue
        if field == "status":
            if value not in STATUSES:
                raise HTTPException(400, "その進み具合は選べません")
            # 完了にした時刻を残す。戻したら消す（やり直しがあるため）
            row.done_at = datetime.now(timezone.utc) if value == "done" else None
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.post("/{req_id:int}/move")
def move_request(req_id: int, direction: str, request: Request,
                 db: Session = Depends(get_db)):
    """並びをひとつ上／下へ動かす。

    順番は sort_order で持つ。入れていない行は作った順（id）を使うので、
    動かすときに関係する2行ぶんだけ値を確定させて入れ替える。
    """
    if _is_share(request):
        raise HTTPException(403, "この画面からは並べ替えられません")
    if direction not in ("up", "down"):
        raise HTTPException(400, "up か down を指定してください")

    rows = (db.query(ImageRequest)
            .filter(ImageRequest.is_deleted == False)
            .order_by(sa_func.coalesce(ImageRequest.sort_order,
                                       ImageRequest.id).asc(),
                      ImageRequest.id.asc())
            .all())
    idx = next((i for i, r in enumerate(rows) if r.id == req_id), None)
    if idx is None:
        raise HTTPException(404, "見つかりません")
    other = idx - 1 if direction == "up" else idx + 1
    if other < 0 or other >= len(rows):
        return {"ok": True, "moved": False}   # 端なので動かさない

    a, b = rows[idx], rows[other]
    a_key = a.sort_order if a.sort_order is not None else a.id
    b_key = b.sort_order if b.sort_order is not None else b.id
    a.sort_order, b.sort_order = b_key, a_key
    db.commit()
    return {"ok": True, "moved": True}


@router.delete("/{req_id:int}")
def delete_request(req_id: int, request: Request, db: Session = Depends(get_db)):
    """消す。外注さんの画面からは消せない。"""
    if _is_share(request):
        raise HTTPException(403, "この画面からは消せません")
    row = db.query(ImageRequest).filter(ImageRequest.id == req_id).first()
    if not row:
        raise HTTPException(404, "見つかりません")
    row.is_deleted = True
    db.commit()
    return {"ok": True}


# ============================================================
# 参考画像
# ============================================================
# 「この色で」を言葉で説明するより、現物を1枚見せたほうが早い。
# 外注さんは共有URLでこの一覧を見るので、そこから見えるところに置く。
#
# 画像は <img src="..."> で読まれる。ヘッダーを付けられないので、
# 合言葉はURLの ?share= に付ける（main.py の middleware がそれを見る）。

import io as _io

from fastapi import File, Response, UploadFile
from PIL import Image

from app.models.image_request import ImageRequestPhoto

_VIEW_MAX = 1400   # 開いて見るときの長辺
_THUMB_MAX = 240   # 一覧に並べるときの長辺
_MAX_UPLOAD = 20 * 1024 * 1024


def _shrink(raw: bytes, longest: int) -> bytes:
    """長辺を揃えてJPEGにする。元のままだと通信量がすぐ膨らむ。"""
    im = Image.open(_io.BytesIO(raw))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    if max(w, h) > longest:
        if w >= h:
            im = im.resize((longest, max(1, round(h * longest / w))))
        else:
            im = im.resize((max(1, round(w * longest / h)), longest))
    buf = _io.BytesIO()
    im.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


def _photo_out(p: ImageRequestPhoto) -> dict:
    return {"id": p.id, "name": p.name or "",
            "created_at": p.created_at.isoformat() if p.created_at else None}


@router.get("/{req_id:int}/photos")
def list_photos(req_id: int, db: Session = Depends(get_db)):
    """その依頼に付いている参考画像の一覧（中身は入れない）。"""
    rows = (db.query(ImageRequestPhoto)
            .filter(ImageRequestPhoto.request_id == req_id)
            .order_by(ImageRequestPhoto.sort_order, ImageRequestPhoto.id).all())
    return {"items": [_photo_out(p) for p in rows]}


@router.post("/{req_id:int}/photos")
async def add_photos(req_id: int, request: Request,
                     files: list[UploadFile] = File(...),
                     db: Session = Depends(get_db)):
    """参考画像を足す。外注さんの画面からは足せない。"""
    if _is_share(request):
        raise HTTPException(403, "この画面からは画像を足せません")
    req = db.query(ImageRequest).filter(ImageRequest.id == req_id).first()
    if not req:
        raise HTTPException(404, "依頼が見つかりません")

    last = (db.query(sa_func.max(ImageRequestPhoto.sort_order))
            .filter(ImageRequestPhoto.request_id == req_id).scalar() or 0)
    saved = []
    for f in files:
        raw = await f.read()
        if not raw:
            continue
        if len(raw) > _MAX_UPLOAD:
            raise HTTPException(400, f"{f.filename} が大きすぎます（20MBまで）")
        try:
            view = _shrink(raw, _VIEW_MAX)
            thumb = _shrink(raw, _THUMB_MAX)
        except Exception:
            raise HTTPException(400, f"{f.filename} は画像として読めませんでした")
        last += 1
        p = ImageRequestPhoto(request_id=req_id, name=(f.filename or "")[:200],
                              content_type="image/jpeg", data=view,
                              thumb=thumb, sort_order=last)
        db.add(p)
        db.flush()
        saved.append(_photo_out(p))
    db.commit()
    return {"items": saved}


@router.get("/photo/{photo_id:int}")
def get_photo(photo_id: int, thumb: int = 0, db: Session = Depends(get_db)):
    """画像そのもの。<img src> から読まれる。

    中身は入れ替わらないので、ブラウザに長く持たせて読み直しを減らす。
    """
    p = (db.query(ImageRequestPhoto)
         .filter(ImageRequestPhoto.id == photo_id).first())
    if not p:
        raise HTTPException(404, "画像が見つかりません")
    body = (p.thumb if thumb else p.data) or p.data
    if not body:
        raise HTTPException(404, "画像が空です")
    return Response(content=body, media_type=p.content_type or "image/jpeg",
                    headers={"Cache-Control": "public, max-age=604800"})


@router.delete("/photo/{photo_id:int}")
def delete_photo(photo_id: int, request: Request,
                 db: Session = Depends(get_db)):
    """参考画像を消す。外注さんの画面からは消せない。"""
    if _is_share(request):
        raise HTTPException(403, "この画面からは画像を消せません")
    p = (db.query(ImageRequestPhoto)
         .filter(ImageRequestPhoto.id == photo_id).first())
    if not p:
        raise HTTPException(404, "画像が見つかりません")
    db.delete(p)
    db.commit()
    return {"ok": True}
