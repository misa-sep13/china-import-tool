"""楽天の1日ぶんの発送件数と売上金額。

受注APIから毎回数え直すと1年ぶんで数百回の呼び出しになるので、
一度数えた日はDBに置いて、次からは足りない日だけ取りに行く。

日付は「発送日」。注文日ではない。
"""
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.models.rakuten_settings import RakutenSettings
from app.models.rakuten_shipping_daily import RakutenShippingDaily

router = APIRouter(prefix="/rakuten/shipping-daily", tags=["rakuten"])

# 取り込みの進み具合。画面が数十秒〜数分待つので、途中経過を見せる
_jobs: dict = {}


def _parse_day(s: Optional[str], default: date) -> date:
    if not s:
        return default
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "日付の形が違います（2025-07-01 の形で）")


def _month_ranges(start: date, end: date):
    """月ごとに区切る。1回の呼び出しを軽くするため。"""
    cur = start.replace(day=1)
    while cur <= end:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield max(cur, start), min(nxt - timedelta(days=1), end)
        cur = nxt


@router.get("")
def list_days(date_from: Optional[str] = None, date_to: Optional[str] = None,
              db: Session = Depends(get_db)):
    """溜めてある日ごとの数を返す。月ごとの合計も添える。"""
    today = date.today()
    start = _parse_day(date_from, date(2025, 7, 1))
    end = _parse_day(date_to, today)

    rows = (db.query(RakutenShippingDaily)
            .filter(RakutenShippingDaily.day >= start,
                    RakutenShippingDaily.day <= end)
            .order_by(RakutenShippingDaily.day).all())

    days, months = [], {}
    for r in rows:
        d = {"day": r.day.isoformat(),
             "order_count": r.order_count or 0,
             "package_count": r.package_count or 0,
             "total_price": round(r.total_price or 0),
             "goods_price": round(r.goods_price or 0)}
        days.append(d)
        m = months.setdefault(r.day.strftime("%Y-%m"),
                              {"month": r.day.strftime("%Y-%m"),
                               "order_count": 0, "package_count": 0,
                               "total_price": 0, "goods_price": 0, "days": 0})
        m["order_count"] += d["order_count"]
        m["package_count"] += d["package_count"]
        m["total_price"] += d["total_price"]
        m["goods_price"] += d["goods_price"]
        m["days"] += 1

    return {
        "from": start.isoformat(), "to": end.isoformat(),
        "days": days,
        "months": [months[k] for k in sorted(months)],
        "total": {
            "order_count": sum(d["order_count"] for d in days),
            "package_count": sum(d["package_count"] for d in days),
            "total_price": sum(d["total_price"] for d in days),
            "goods_price": sum(d["goods_price"] for d in days),
        },
    }


def _save(db: Session, day_str: str, v: dict) -> None:
    d = datetime.strptime(day_str, "%Y-%m-%d").date()
    row = (db.query(RakutenShippingDaily)
           .filter(RakutenShippingDaily.day == d).first())
    if not row:
        row = RakutenShippingDaily(day=d)
        db.add(row)
    row.order_count = v["order_count"]
    row.package_count = v["package_count"]
    row.total_price = round(v["total_price"], 2)
    row.goods_price = round(v["goods_price"], 2)


async def _run_import(job_id: str, start: date, end: date):
    from app.services import rakuten_rms

    db = SessionLocal()
    try:
        s = db.query(RakutenSettings).first()
        if not s or not s.rms_service_secret or not s.rms_license_key:
            _jobs[job_id] = {"status": "error",
                             "error": "RMS APIキーが設定されていません"}
            return
        ranges = list(_month_ranges(start, end))
        _jobs[job_id] = {"status": "running", "done_months": 0,
                         "total_months": len(ranges), "now": "", "saved": 0}
        saved = 0
        for n, (a, b) in enumerate(ranges, 1):
            _jobs[job_id]["now"] = f"{a.isoformat()}〜{b.isoformat()}"
            out = await rakuten_rms.fetch_shipping_daily(
                s.rms_service_secret, s.rms_license_key, a, b)
            for day_str, v in out["days"].items():
                _save(db, day_str, v)
                saved += 1
            db.commit()
            _jobs[job_id]["done_months"] = n
            _jobs[job_id]["saved"] = saved
        _jobs[job_id] = {"status": "done", "saved": saved,
                         "total_months": len(ranges)}
    except Exception as e:
        _jobs[job_id] = {"status": "error", "error": str(e)}
    finally:
        db.close()


@router.post("/import")
def start_import(background_tasks: BackgroundTasks,
                 date_from: Optional[str] = None,
                 date_to: Optional[str] = None):
    """受注APIから数え直す。月ごとに区切って順に取りに行く。"""
    start = _parse_day(date_from, date(2025, 7, 1))
    end = _parse_day(date_to, date.today())
    if start > end:
        raise HTTPException(400, "期間が逆になっています")
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "done_months": 0,
                     "total_months": 0, "now": "", "saved": 0}
    background_tasks.add_task(_run_import, job_id, start, end)
    return {"job_id": job_id}


@router.get("/import/{job_id}")
def import_status(job_id: str):
    return _jobs.get(job_id) or {"status": "unknown"}
