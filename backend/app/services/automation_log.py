"""自動で動いたものを1行ずつ残す。

巡回の中から呼ぶ。失敗しても巡回は止めない（記録のために
本処理が落ちては本末転倒）。
"""
import logging
from datetime import datetime, timedelta, timezone

from app.models.automation_run import AutomationRun

logger = logging.getLogger("automation_log")

JST = timezone(timedelta(hours=9))
# 残す日数。古いものは消す。ここが膨らんでも読まない
KEEP_DAYS = 120


def record(db, job: str, area: str, summary: str, status: str = "ok") -> None:
    try:
        db.add(AutomationRun(job=job, area=area, status=status,
                             summary=(summary or "")[:500]))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"[automation-log] 記録できませんでした {job}: {e}")


def record_new_session(job: str, area: str, summary: str,
                       status: str = "ok") -> None:
    """自分でセッションを開いて書く。巡回の外側から呼ぶとき用。"""
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        record(db, job, area, summary, status)
    finally:
        db.close()


def prune(db) -> int:
    cut = datetime.now(JST) - timedelta(days=KEEP_DAYS)
    try:
        n = (db.query(AutomationRun)
             .filter(AutomationRun.created_at < cut)
             .delete(synchronize_session=False))
        db.commit()
        return n
    except Exception:
        db.rollback()
        return 0
