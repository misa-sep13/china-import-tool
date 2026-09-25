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
    return {"items": [_out(r) for r in rows], "done_count": done,
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
