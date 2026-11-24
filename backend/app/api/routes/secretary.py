"""秘書の窓口。

「今日やること」を出すのが主な仕事。くり返しの決まりはここから足せる。
決まりを更新するときは、送られてきた項目だけを書き換える（丸ごと置き換えない）。
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.secretary import (AREA_LABELS, CADENCES, DUE_RULES, STATUSES,
                                  SecretaryRun, SecretarySender, SecretaryTask)
from app.services import secretary as svc
from app.services import secretary_mail
from app.services import secretary_line

router = APIRouter(prefix="/secretary", tags=["secretary"])


# ----------------------------------------------------------------- 受け取る形
class TaskIn(BaseModel):
    title: str
    area: str = "construction"
    cadence: str = "monthly"
    day_of_month: Optional[int] = None
    month: Optional[int] = None
    lead_days: int = 3
    target_month_offset: int = 0
    checklist: Optional[str] = None
    link_url: Optional[str] = None
    note: Optional[str] = None
    active: bool = True
    sort_order: int = 100


class TaskPatch(BaseModel):
    """送られてきた項目だけを書き換える。省いた項目は今の値のまま。"""
    title: Optional[str] = None
    area: Optional[str] = None
    cadence: Optional[str] = None
    day_of_month: Optional[int] = None
    month: Optional[int] = None
    lead_days: Optional[int] = None
    target_month_offset: Optional[int] = None
    checklist: Optional[str] = None
    link_url: Optional[str] = None
    note: Optional[str] = None
    active: Optional[bool] = None
    sort_order: Optional[int] = None


class RunIn(BaseModel):
    """都度の仕事。くり返しの決まりを作らずに1件だけ立てる。"""
    title: str
    area: str = "construction"
    due_date: date
    lead_days: int = 0
    amount: Optional[float] = None
    checklist: Optional[str] = None
    ref_url: Optional[str] = None


class RunPatch(BaseModel):
    status: Optional[str] = None
    done_note: Optional[str] = None
    due_date: Optional[date] = None
    amount: Optional[float] = None
    title: Optional[str] = None
    checklist: Optional[str] = None
    ref_url: Optional[str] = None


# ----------------------------------------------------------------- 返す形
def _task_out(t: SecretaryTask) -> dict:
    return {
        "id": t.id, "title": t.title, "area": t.area,
        "area_label": AREA_LABELS.get(t.area, t.area),
        "cadence": t.cadence, "day_of_month": t.day_of_month, "month": t.month,
        "lead_days": t.lead_days, "target_month_offset": t.target_month_offset,
        "checklist": t.checklist, "link_url": t.link_url, "note": t.note,
        "active": bool(t.active), "sort_order": t.sort_order,
    }


def _run_out(r: SecretaryRun, today: date) -> dict:
    left = (r.due_date - today).days
    return {
        "id": r.id, "task_id": r.task_id, "title": r.title, "area": r.area,
        "area_label": AREA_LABELS.get(r.area, r.area),
        "period": r.period, "target_period": r.target_period,
        "due_date": r.due_date.isoformat(),
        "days_left": left,
        "overdue": r.status == "open" and left < 0,
        "status": r.status,
        "done_at": r.done_at.isoformat() if r.done_at else None,
        "done_note": r.done_note,
        "amount": r.amount, "source": r.source, "ref_url": r.ref_url,
        "checklist": r.checklist, "permit_id": r.permit_id,
    }


def _sender_out(s) -> dict:
    return {
        "id": s.id, "name": s.name, "match_from": s.match_from,
        "area": s.area, "area_label": AREA_LABELS.get(s.area, s.area),
        "doc_kind": s.doc_kind, "due_rule": s.due_rule, "due_day": s.due_day,
        "lead_days": s.lead_days, "task_id": s.task_id, "note": s.note,
        "active": bool(s.active),
        "last_found_at": s.last_found_at.isoformat() if s.last_found_at else None,
    }


# ----------------------------------------------------------------- やること
@router.get("/today")
def today_list(
    days: int = Query(0, ge=0, le=60, description="何日先まで含めるか"),
    db: Session = Depends(get_db),
):
    """今やるべきものを期限の早い順で返す。

    出すのは「期限 − 何日前から出すか」を過ぎた未完了のもの。
    期限を過ぎたものほど上に来る。
    """
    today = svc.today_jst()
    svc.seed_if_empty(db)
    svc.ensure_runs(db, today)

    limit = today + timedelta(days=days)
    rows = (
        db.query(SecretaryRun)
        .filter(SecretaryRun.status == "open")
        .order_by(SecretaryRun.due_date.asc(), SecretaryRun.id.asc())
        .all()
    )
    out = [_run_out(r, today) for r in rows if svc.visible_from(r) <= limit]

    return {
        "today": today.isoformat(),
        "runs": out,
        "overdue_count": sum(1 for x in out if x["overdue"]),
    }


@router.get("/runs")
def list_runs(
    period: Optional[str] = Query(None, description="2026-11 の形。省くと今月"),
    status: Optional[str] = None,
    area: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """月ごとの一覧。履歴もここで見る。"""
    today = svc.today_jst()
    svc.seed_if_empty(db)
    svc.ensure_runs(db, today)

    period = period or svc.period_str(today.year, today.month)
    q = db.query(SecretaryRun).filter(SecretaryRun.period == period)
    if status:
        q = q.filter(SecretaryRun.status == status)
    if area:
        q = q.filter(SecretaryRun.area == area)
    rows = q.order_by(SecretaryRun.due_date.asc(), SecretaryRun.id.asc()).all()
    return {"period": period, "today": today.isoformat(),
            "runs": [_run_out(r, today) for r in rows]}


@router.post("/runs")
def add_run(payload: RunIn, db: Session = Depends(get_db)):
    """都度の仕事を1件立てる。"""
    if payload.area not in AREA_LABELS:
        raise HTTPException(400, "区分が違います: " + str(payload.area))
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(400, "題が空です")
    due = payload.due_date
    row = SecretaryRun(
        title=title, area=payload.area,
        period=svc.period_str(due.year, due.month),
        due_date=due, lead_days=max(0, payload.lead_days),
        status="open", source="manual",
        amount=payload.amount, checklist=payload.checklist,
        ref_url=payload.ref_url,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _run_out(row, svc.today_jst())


@router.patch("/runs/{run_id}")
def update_run(run_id: int, payload: RunPatch, db: Session = Depends(get_db)):
    """送られてきた項目だけを書き換える。"""
    row = db.query(SecretaryRun).filter(SecretaryRun.id == run_id).first()
    if not row:
        raise HTTPException(404, "見つかりません")

    data = payload.model_dump(exclude_unset=True)
    if "status" in data:
        if data["status"] not in STATUSES:
            raise HTTPException(400, "状態が違います: " + str(data["status"]))
        row.done_at = None if data["status"] == "open" else svc.now_jst()
    for key, value in data.items():
        setattr(row, key, value)
    if "due_date" in data and row.due_date:
        row.period = svc.period_str(row.due_date.year, row.due_date.month)

    db.commit()
    db.refresh(row)
    return _run_out(row, svc.today_jst())


# ----------------------------------------------------------------- 決まり
@router.get("/tasks")
def list_tasks(db: Session = Depends(get_db)):
    svc.seed_if_empty(db)
    rows = (db.query(SecretaryTask)
            .order_by(SecretaryTask.sort_order.asc(), SecretaryTask.id.asc())
            .all())
    return {"tasks": [_task_out(t) for t in rows],
            "areas": [{"key": k, "label": v} for k, v in AREA_LABELS.items()]}


@router.post("/tasks")
def add_task(payload: TaskIn, db: Session = Depends(get_db)):
    if payload.area not in AREA_LABELS:
        raise HTTPException(400, "区分が違います: " + str(payload.area))
    if payload.cadence not in CADENCES:
        raise HTTPException(400, "くり返しの型が違います: " + str(payload.cadence))
    if not (payload.title or "").strip():
        raise HTTPException(400, "題が空です")
    row = SecretaryTask(**payload.model_dump())
    row.title = row.title.strip()
    db.add(row)
    db.commit()
    db.refresh(row)
    svc.ensure_runs(db)
    return _task_out(row)


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, payload: TaskPatch, db: Session = Depends(get_db)):
    """送られてきた項目だけを書き換える。省いた項目は今の値のまま残す。"""
    row = db.query(SecretaryTask).filter(SecretaryTask.id == task_id).first()
    if not row:
        raise HTTPException(404, "見つかりません")

    data = payload.model_dump(exclude_unset=True)
    if "area" in data and data["area"] not in AREA_LABELS:
        raise HTTPException(400, "区分が違います: " + str(data["area"]))
    if "cadence" in data and data["cadence"] not in CADENCES:
        raise HTTPException(400, "くり返しの型が違います: " + str(data["cadence"]))
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)

    # 日付や題を変えたら、まだ終わっていない分も合わせる。
    # 済んだものは履歴なので動かさない
    pending = (db.query(SecretaryRun)
               .filter(SecretaryRun.task_id == row.id,
                       SecretaryRun.status == "open")
               .all())
    for r in pending:
        year, month = int(r.period[:4]), int(r.period[5:7])
        due = svc.due_date_for(row, year, month)
        if due is None:
            continue
        r.title, r.area = row.title, row.area
        r.due_date = due
        r.lead_days = row.lead_days or 0
        r.checklist = row.checklist
        r.ref_url = row.link_url
        ty, tm = svc.shift_month(year, month, row.target_month_offset or 0)
        r.target_period = svc.period_str(ty, tm) if row.target_month_offset else None
    db.commit()
    return _task_out(row)


# ----------------------------------------------------------------- 請求元
class SenderIn(BaseModel):
    name: str
    match_from: str
    area: str = "money"
    doc_kind: str = "wholesale"
    due_rule: str = "eom"
    due_day: int = 10
    lead_days: int = 7
    task_id: Optional[int] = None
    note: Optional[str] = None
    active: bool = True


class SenderPatch(BaseModel):
    name: Optional[str] = None
    match_from: Optional[str] = None
    area: Optional[str] = None
    doc_kind: Optional[str] = None
    due_rule: Optional[str] = None
    due_day: Optional[int] = None
    lead_days: Optional[int] = None
    task_id: Optional[int] = None
    note: Optional[str] = None
    active: Optional[bool] = None


def _check_sender(data: dict):
    if "area" in data and data["area"] not in AREA_LABELS:
        raise HTTPException(400, "区分が違います: " + str(data["area"]))
    if "due_rule" in data and data["due_rule"] not in DUE_RULES:
        raise HTTPException(400, "期限の決め方が違います: " + str(data["due_rule"]))
    if "match_from" in data and "@" not in str(data["match_from"] or ""):
        raise HTTPException(400, "メールアドレスを入れてください")


@router.get("/senders")
def list_senders(db: Session = Depends(get_db)):
    svc.seed_if_empty(db)
    secretary_mail.seed_senders_if_empty(db)
    rows = db.query(SecretarySender).order_by(SecretarySender.id.asc()).all()
    return {"senders": [_sender_out(s) for s in rows],
            "due_rules": [
                {"key": "eom", "label": "届いた月の月末まで"},
                {"key": "eom_next", "label": "翌月末まで"},
                {"key": "day", "label": "毎月の決まった日まで"},
                {"key": "days", "label": "届いてから何日後か"},
            ]}


@router.post("/senders")
def add_sender(payload: SenderIn, db: Session = Depends(get_db)):
    data = payload.model_dump()
    _check_sender(data)
    if not (payload.name or "").strip():
        raise HTTPException(400, "名前が空です")
    row = SecretarySender(**data)
    row.name = row.name.strip()
    row.match_from = row.match_from.strip().lower()
    db.add(row)
    db.commit()
    db.refresh(row)
    return _sender_out(row)


@router.patch("/senders/{sender_id}")
def update_sender(sender_id: int, payload: SenderPatch,
                  db: Session = Depends(get_db)):
    """送られてきた項目だけを書き換える。"""
    row = db.query(SecretarySender).filter(SecretarySender.id == sender_id).first()
    if not row:
        raise HTTPException(404, "見つかりません")
    data = payload.model_dump(exclude_unset=True)
    _check_sender(data)
    if "match_from" in data and data["match_from"]:
        data["match_from"] = str(data["match_from"]).strip().lower()
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _sender_out(row)


class FetchMailIn(BaseModel):
    # 何日ぶん遡って見るか。ふだんは45日で足りる
    days: int = 45
    # 見に行くフォルダ。省くと受信トレイ。"*" で全フォルダ
    folder: Optional[str] = None


@router.post("/fetch-mail")
def fetch_mail(payload: FetchMailIn, db: Session = Depends(get_db)):
    """登録した請求元のメールを見て、振込待ちを立てる。

    同じ添付は二度入らないので、何度押しても増えない。
    """
    svc.seed_if_empty(db)
    secretary_mail.seed_senders_if_empty(db)
    svc.ensure_runs(db)
    try:
        return secretary_mail.fetch(db, days=max(1, min(payload.days, 365)),
                                    folder=payload.folder)
    except permit_mail_error() as e:
        raise HTTPException(502, str(e))


def permit_mail_error():
    from app.services.permit_mail import PermitMailError
    return PermitMailError


# ----------------------------------------------------------------- 毎朝の知らせ
class NotifyPatch(BaseModel):
    enabled: Optional[bool] = None
    hour: Optional[int] = None
    fetch_mail: Optional[bool] = None
    ahead_days: Optional[int] = None
    send_when_empty: Optional[bool] = None


def _notify_out(n) -> dict:
    return {
        "enabled": bool(n.enabled), "hour": n.hour,
        "fetch_mail": bool(n.fetch_mail), "ahead_days": n.ahead_days,
        "send_when_empty": bool(n.send_when_empty),
        "last_sent_on": n.last_sent_on,
        "last_sent_at": n.last_sent_at.isoformat() if n.last_sent_at else None,
        "last_error": n.last_error,
        # トークンそのものは返さない。入っているかどうかだけ
        "configured": secretary_line.is_configured(),
    }


@router.get("/notify")
def get_notify(db: Session = Depends(get_db)):
    """毎朝の知らせの設定と、いま送るとどうなるかの下書き。"""
    conf = secretary_line.get_or_create_settings(db)
    svc.seed_if_empty(db)
    preview = secretary_line.build_message(db, ahead_days=conf.ahead_days or 0)
    return {**_notify_out(conf), "preview": preview}


@router.patch("/notify")
def update_notify(payload: NotifyPatch, db: Session = Depends(get_db)):
    """送られてきた項目だけを書き換える。"""
    conf = secretary_line.get_or_create_settings(db)
    data = payload.model_dump(exclude_unset=True)
    if "hour" in data and not (0 <= int(data["hour"]) <= 23):
        raise HTTPException(400, "時刻は0〜23で入れてください")
    if "ahead_days" in data and not (0 <= int(data["ahead_days"]) <= 60):
        raise HTTPException(400, "先に見る日数は0〜60で入れてください")
    for key, value in data.items():
        setattr(conf, key, value)
    db.commit()
    db.refresh(conf)
    return _notify_out(conf)


@router.post("/notify/test")
def test_notify(db: Session = Depends(get_db)):
    """いまの内容で1通送ってみる。やることが無くても送る。"""
    try:
        return secretary_line.send_now(db, force=True)
    except secretary_line.LineError as e:
        raise HTTPException(502, e.message)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    """決まりをやめる。消さずに止めるだけにして、履歴は残す。"""
    row = db.query(SecretaryTask).filter(SecretaryTask.id == task_id).first()
    if not row:
        raise HTTPException(404, "見つかりません")
    row.active = False
    # これから先の未完了分は消す。履歴（済み）はそのまま
    (db.query(SecretaryRun)
     .filter(SecretaryRun.task_id == task_id, SecretaryRun.status == "open")
     .delete(synchronize_session=False))
    db.commit()
    return {"ok": True, "stopped": row.title}
