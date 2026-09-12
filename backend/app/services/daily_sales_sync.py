"""日別実績をレポートから取り込んでDBに溜める。

毎日走らせる前提。取り込んだところまでを daily_sales_sync に残し、
古くなったら発注計算を止める（鮮度が落ちると「直近日が欠品扱い」→
「平常日が減る」→「セールを信じすぎる」方向に倒れるため）。
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.daily_sales import DailySales, DailySalesSync
from app.services import amazon_reports

log = logging.getLogger("daily_sales")

# 発注ロジックが見る窓は60日。少し余裕を持って遡る
KEEP_DAYS = 90
# レポートは1回で取れる期間に限りがあるので、この日数ずつに切る
CHUNK_DAYS = 30


def _sync_row(db: Session, kind: str) -> DailySalesSync:
    row = db.query(DailySalesSync).filter(DailySalesSync.kind == kind).first()
    if not row:
        row = DailySalesSync(kind=kind)
        db.add(row)
        db.flush()
    return row


def _upsert(db: Session, sku: str, day: date, **fields) -> None:
    row = (db.query(DailySales)
           .filter(DailySales.sku == sku, DailySales.day == day).first())
    if not row:
        row = DailySales(sku=sku, day=day)
        db.add(row)
    for k, v in fields.items():
        if v is not None:
            setattr(row, k, v)


def _ranges(start: date, end: date):
    """レポートの取得期間を CHUNK_DAYS ずつに切る。"""
    cur = start
    while cur <= end:
        last = min(cur + timedelta(days=CHUNK_DAYS - 1), end)
        yield cur, last
        cur = last + timedelta(days=1)


def sync_orders(db: Session, start: Optional[date] = None,
                end: Optional[date] = None) -> dict:
    """注文明細を取り込む。日別の販売数・売上・プロモ値引き・Vine。"""
    today = date.today()
    # 今日はまだ終わっていないので昨日まで
    end = end or (today - timedelta(days=1))
    if start is None:
        row = _sync_row(db, "orders")
        # 前回の続きから。初回は窓のぶんだけ遡る
        start = (row.last_day + timedelta(days=1)) if row.last_day \
            else (end - timedelta(days=KEEP_DAYS - 1))
    if start > end:
        return {"skipped": True, "reason": "取り込む日がありません"}

    row = _sync_row(db, "orders")
    total = 0
    try:
        for s, e in _ranges(start, end):
            for x in amazon_reports.fetch_orders(s, e):
                _upsert(db, x["sku"], x["day"],
                        asin=x.get("asin") or None,
                        units=x["units"], vine_units=x["vine_units"],
                        revenue=x["revenue"], promo_discount=x["promo_discount"])
                total += 1
            db.flush()
        row.last_day = end
        row.last_error = None
    except amazon_reports.ReportError as ex:
        row.last_error = str(ex)
        row.last_run_at = datetime.now(timezone.utc)
        db.commit()
        raise
    row.last_run_at = datetime.now(timezone.utc)
    db.commit()
    return {"from": str(start), "to": str(end), "rows": total}


def sync_ledger(db: Session, start: Optional[date] = None,
                end: Optional[date] = None) -> dict:
    """在庫元帳を取り込む。その日の終わりに売れる在庫があったか。

    元帳に行が無い日は「その倉庫に在庫が無かった」ことを意味するので、
    注文が付いている日だけを在庫ありに倒すのではなく、
    元帳の期末残がある日を在庫ありとして印を付ける。
    """
    today = date.today()
    end = end or (today - timedelta(days=1))
    if start is None:
        row = _sync_row(db, "ledger")
        start = (row.last_day + timedelta(days=1)) if row.last_day \
            else (end - timedelta(days=KEEP_DAYS - 1))
    if start > end:
        return {"skipped": True, "reason": "取り込む日がありません"}

    row = _sync_row(db, "ledger")
    seen: set = set()
    try:
        for s, e in _ranges(start, end):
            for x in amazon_reports.fetch_ledger(s, e):
                _upsert(db, x["sku"], x["day"],
                        sellable_end=x["sellable_end"],
                        in_stock=bool(x["sellable_end"] > 0))
                seen.add((x["sku"], x["day"]))
            db.flush()

        # 元帳に出てこなかった日は在庫が無かった日。
        # ただし注文が付いている日は、元帳の粒度の問題なので在庫ありに残す
        rows = (db.query(DailySales)
                .filter(DailySales.day >= start, DailySales.day <= end).all())
        for r in rows:
            if (r.sku, r.day) in seen:
                continue
            if (r.units or 0) > 0:
                continue
            r.in_stock = False

        row.last_day = end
        row.last_error = None
    except amazon_reports.ReportError as ex:
        row.last_error = str(ex)
        row.last_run_at = datetime.now(timezone.utc)
        db.commit()
        raise
    row.last_run_at = datetime.now(timezone.utc)
    db.commit()
    return {"from": str(start), "to": str(end), "skus": len({s for s, _ in seen})}


def purge_old(db: Session, keep_days: int = KEEP_DAYS + 30) -> int:
    """古い日別データを捨てる。窓は60日なので、これ以上は使わない。"""
    limit = date.today() - timedelta(days=keep_days)
    n = db.query(DailySales).filter(DailySales.day < limit).delete()
    db.commit()
    return n


def freshness(db: Session) -> dict:
    """どこまで取り込めているか。発注計算を止めるかの判断に使う。

    仕様書のfail-closed: 検査が「実行できなかった」ことと「不合格」を
    同じ扱いにする。取り込めていない＝古い、として止める。
    """
    today = date.today()
    out = {"ok": True, "kinds": {}, "reasons": []}
    for kind in ("orders", "ledger"):
        row = db.query(DailySalesSync).filter(DailySalesSync.kind == kind).first()
        last = row.last_day if row else None
        age = (today - last).days if last else None
        out["kinds"][kind] = {
            "last_day": str(last) if last else None,
            "age_days": age,
            "error": (row.last_error if row else None),
        }
        if last is None:
            out["ok"] = False
            out["reasons"].append(f"{kind} をまだ一度も取り込めていません")
        elif age > 7:
            out["ok"] = False
            out["reasons"].append(f"{kind} が {age} 日前で止まっています")
    return out
