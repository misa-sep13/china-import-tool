"""状況確認シート。商品ごとに「いま誰の番か」と質問のやり取りを持つ。

チャットワークだけでやり取りしていると話が流れてしまい、
「これは誰の番なのか」「この質問は答えたのか」が分からなくなる。
外注さんから一覧で見たいという声が出たので作った。

1行＝商品（SKU）1つ。Amazonも楽天も同じ並びに出す。
チャットワークは事務連絡と詳しい相談に使い、こちらは
「誰待ちか」と「答えの出ていない質問」を残す場所にする。

外注さんには合言葉つきのURLでこの一覧だけを見せる。合言葉で通るのは
このAPIだけで、他の画面には一切届かない。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func as sa_func
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.work_status import WorkStatus, WorkNote

router = APIRouter(prefix="/work-status", tags=["work-status"])

# 工程。3つ終わったら完了。プルダウンで1つ選ぶ形だと、
# 「発注は済んだが画像はまだ」という途中の状態を表せなかった
STEPS = [
    {"key": "step_order",   "label": "発注"},
    {"key": "step_image",   "label": "画像依頼"},
    {"key": "step_listing", "label": "商品登録"},
]
STEP_KEYS = [s["key"] for s in STEPS]

# stage は3つのチェックから決まる。完了を一覧から外す絞り込みに使う
STAGES = ["adopted", "ordered", "imaged", "listed", "selling", "done"]
STAGE_LABEL = {
    "adopted": "採用",
    "ordered": "発注済み",
    "imaged": "画像依頼済み",
    "listed": "商品登録済み",
    "selling": "販売中",
    "done": "完了",
}


def _sync_stage(row) -> None:
    """3つのチェックから stage と完了時刻を決める。

    全部そろったら完了。外したら完了を取り消す（やり直しがあるため）。
    """
    done = all(bool(getattr(row, k)) for k in STEP_KEYS)
    if done:
        row.stage = "done"
        if not row.done_at:
            row.done_at = datetime.now(timezone.utc)
        return
    row.done_at = None
    if row.step_listing:
        row.stage = "listed"
    elif row.step_image:
        row.stage = "imaged"
    elif row.step_order:
        row.stage = "ordered"
    else:
        row.stage = "adopted"

# 誰の番か。これが一覧の主役なので、迷わないよう3つだけにしてある。
# 名前ではなく役割で持つ。外注さんが交代しても
# 保存済みのデータを直さなくて済むようにするため。
BALLS = ["owner", "staff", "none"]
BALL_LABEL = {"owner": "ゆな確認待ち", "staff": "外注さん対応中",
              "none": "待ちなし"}


def _note_out(n: WorkNote) -> dict:
    return {
        "id": n.id,
        "who": n.who or "",
        "body": n.body or "",
        "answer": n.answer or "",
        "answered_at": n.answered_at.isoformat() if n.answered_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def _out(r: WorkStatus) -> dict:
    notes = sorted(r.notes or [], key=lambda n: n.id)
    return {
        "id": r.id,
        "channel": r.channel or "amazon",
        "research_id": r.research_id,
        "sku": r.sku or "",
        "name": r.name or "",
        "memo": r.memo or "",
        "stage": r.stage or "adopted",
        "stage_label": STAGE_LABEL.get(r.stage or "adopted", r.stage or ""),
        "step_order": bool(r.step_order),
        "step_image": bool(r.step_image),
        "step_listing": bool(r.step_listing),
        "done": (r.stage or "") == "done",
        "ball": r.ball or "staff",
        "ball_label": BALL_LABEL.get(r.ball or "staff", ""),
        "notes": [_note_out(n) for n in notes],
        # 答えの出ていない質問の数。一覧で赤く出して抜けを防ぐ
        "open_count": len([n for n in notes if not (n.answer or "").strip()]),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _is_share(request: Request) -> bool:
    """合言葉つきで来ているか。外注さんの画面かどうかの判定に使う。"""
    from app.core.config import settings
    want = getattr(settings, "KEEP_SHARE_TOKEN", "") or ""
    got = (request.query_params.get("share")
           or request.headers.get("x-work-share") or "")
    if not (want and got):
        return False
    # 合言葉に + が入っていると、URLの?以降では空白として解釈される
    return got == want or got.replace(" ", "+") == want


@router.get("")
def list_rows(include_done: int = 0, only_done: int = 0,
              db: Session = Depends(get_db)):
    """一覧。既定では完了を外す（いま動いているものだけ見たいので）。

    only_done を付けると、完了したものだけを出す。
    """
    q = db.query(WorkStatus).filter(WorkStatus.is_deleted == False)
    if only_done:
        q = q.filter(WorkStatus.stage == "done")
    elif not include_done:
        q = q.filter(WorkStatus.stage != "done")
    rows = q.order_by(
        sa_func.coalesce(WorkStatus.sort_order, WorkStatus.id).asc(),
        WorkStatus.id.asc()).all()
    return {"items": [_out(r) for r in rows],
            "stages": [{"key": k, "label": STAGE_LABEL[k]} for k in STAGES],
            "steps": STEPS,
            "balls": [{"key": k, "label": BALL_LABEL[k]} for k in BALLS]}


class WorkIn(BaseModel):
    channel: Optional[str] = "amazon"
    research_id: Optional[str] = None
    sku: Optional[str] = ""
    name: Optional[str] = ""
    memo: Optional[str] = ""
    stage: Optional[str] = "adopted"
    ball: Optional[str] = "staff"


@router.post("")
def create_row(data: WorkIn, request: Request, db: Session = Depends(get_db)):
    """1件足す。外注さんからは足せない（こちらで管理する）。"""
    if _is_share(request):
        raise HTTPException(403, "この画面からは追加できません")
    row = WorkStatus(**data.model_dump(exclude_unset=True))
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.post("/sync")
def sync_from_research(data: WorkIn, db: Session = Depends(get_db)):
    """リサーチシートから呼ばれる。同じ枠から二重に作らない。

    採用にした時点で1行できる。すでにあれば商品名だけ今のものに直す
    （リサーチ中に名前が変わることがあるため）。状態は触らない。
    """
    rid = (data.research_id or "").strip()
    row = None
    if rid:
        row = (db.query(WorkStatus)
               .filter(WorkStatus.research_id == rid,
                       WorkStatus.is_deleted == False).first())
    if row:
        if data.sku:
            row.sku = data.sku
        if data.name:
            row.name = data.name
        db.commit()
        db.refresh(row)
        return _out(row)
    row = WorkStatus(**data.model_dump(exclude_unset=True))
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


class WorkPatch(BaseModel):
    sku: Optional[str] = None
    name: Optional[str] = None
    memo: Optional[str] = None
    stage: Optional[str] = None
    ball: Optional[str] = None
    step_order: Optional[bool] = None
    step_image: Optional[bool] = None
    step_listing: Optional[bool] = None


@router.patch("/{row_id:int}")
def update_row(row_id: int, data: WorkPatch, request: Request,
               db: Session = Depends(get_db)):
    """状態を書き換える。

    外注さんは工程・誰待ち・メモだけ触れる。SKUと商品名は
    こちらでしか変えられない（取り違えると別の商品の話になる）。
    """
    row = db.query(WorkStatus).filter(WorkStatus.id == row_id).first()
    if not row:
        raise HTTPException(404, "見つかりません")

    guest = _is_share(request)
    allowed = ({"stage", "ball", "memo"} | set(STEP_KEYS)) if guest else None

    touched_steps = False
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if allowed is not None and field not in allowed:
            continue
        if field in STEP_KEYS:
            touched_steps = True
        if field == "stage":
            if value not in STAGES:
                raise HTTPException(400, "その工程は選べません")
            row.done_at = datetime.now(timezone.utc) if value == "done" else None
        if field == "ball" and value not in BALLS:
            raise HTTPException(400, "その担当は選べません")
        setattr(row, field, value)
    # チェックを触ったときは、そこから工程を決め直す
    if touched_steps:
        _sync_stage(row)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/{row_id:int}/notes/{note_id:int}")
def delete_note(row_id: int, note_id: int, request: Request,
                db: Session = Depends(get_db)):
    """やり取りを1件消す。

    テストで書いたものや、書き間違えたものが残り続けると、
    本当に答えの要る質問が埋もれる。外注さんの画面からは消せない
    （相手の書いたものまで消えてしまうため）。
    """
    if _is_share(request):
        raise HTTPException(403, "この画面からは削除できません")
    note = (db.query(WorkNote)
            .filter(WorkNote.id == note_id, WorkNote.work_id == row_id)
            .first())
    if not note:
        raise HTTPException(404, "見つかりません")
    db.delete(note)
    db.commit()
    row = db.query(WorkStatus).filter(WorkStatus.id == row_id).first()
    if not row:
        raise HTTPException(404, "見つかりません")
    db.refresh(row)
    return _out(row)


@router.delete("/{row_id:int}")
def delete_row(row_id: int, request: Request, db: Session = Depends(get_db)):
    """消す。実際には印を付けるだけ（間違えても戻せるように）。"""
    if _is_share(request):
        raise HTTPException(403, "この画面からは削除できません")
    row = db.query(WorkStatus).filter(WorkStatus.id == row_id).first()
    if not row:
        raise HTTPException(404, "見つかりません")
    row.is_deleted = True
    db.commit()
    return {"ok": True}


class NoteIn(BaseModel):
    who: Optional[str] = ""
    body: str


@router.post("/{row_id:int}/notes")
def add_note(row_id: int, data: NoteIn, db: Session = Depends(get_db)):
    """質問・連絡を足す。外注さんからも足せる（聞くのが仕事なので）。

    足すと相手の番になる。外注さんが聞いたなら、ゆなの確認待ち。
    ここを手で変えなくて済むようにしておかないと、
    「聞いたのに気づかれない」が起きる。
    """
    row = db.query(WorkStatus).filter(WorkStatus.id == row_id).first()
    if not row:
        raise HTTPException(404, "見つかりません")
    body = (data.body or "").strip()
    if not body:
        raise HTTPException(400, "中身が空です")
    who = (data.who or "").strip() or "staff"
    n = WorkNote(work_id=row.id, who=who, body=body)
    db.add(n)
    row.ball = "owner" if who == "staff" else "staff"
    db.commit()
    db.refresh(row)
    return _out(row)


class AnswerIn(BaseModel):
    answer: str


@router.patch("/{row_id:int}/notes/{note_id:int}")
def answer_note(row_id: int, note_id: int, data: AnswerIn,
                db: Session = Depends(get_db)):
    """質問に答える。答えた時点で相手の番に戻す。"""
    n = (db.query(WorkNote)
         .filter(WorkNote.id == note_id, WorkNote.work_id == row_id).first())
    if not n:
        raise HTTPException(404, "見つかりません")
    n.answer = (data.answer or "").strip()
    n.answered_at = datetime.now(timezone.utc) if n.answer else None
    row = db.query(WorkStatus).filter(WorkStatus.id == row_id).first()
    if row and n.answer:
        # 聞いた人の番に戻す（ゆなが答えたなら、外注さんが動く番）
        row.ball = "staff" if (n.who or "") == "staff" else "owner"
    db.commit()
    db.refresh(row)
    return _out(row)
