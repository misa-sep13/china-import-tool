"""月次管理表（発生ベース会計）。

第一歩として、タオタロウのデポジットの内訳を分解する。

いまの試算表はチャージした日で仕入が計上されている。チャージは
「まとめて入れる前払金」であって、その月に仕入れたものではない。
明細を1行ずつ持って区分ごとに分ければ、その月に実際に発生したぶんだけを
拾える。

設計の全体像は docs/月次管理表_発生ベース会計_設計.md にある。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.taotaro_transaction import TaotaroTransaction
from app.services import taotaro

router = APIRouter(prefix="/accounting", tags=["accounting"])


# タオタロウの区分名 → 会計上の扱い。
# 区分名は日本語でそのまま返ってくる。表記ゆれに備えて部分一致で見る
CATEGORY_RULES = [
    ("商品購入", "purchase"),
    ("値引交渉", "purchase_adjust"),
    ("価格調整", "purchase_adjust"),
    ("数量調整", "purchase_adjust"),
    ("オーダー削除", "purchase_adjust"),
    ("注文削除", "purchase_adjust"),
    ("国際運賃", "shipping"),
    ("国内運賃", "shipping"),
    ("運賃", "shipping"),
    ("管理員操作", "charge"),
    ("チャージ", "charge"),
    ("入金", "charge"),
    ("倉庫保管", "fee"),
    ("保管料", "fee"),
    ("その他", "fee"),
]

CATEGORY_LABELS = {
    "purchase":        "仕入（商品代）",
    "purchase_adjust": "仕入の修正（値引・調整・削除）",
    "shipping":        "仕入諸掛（運賃）",
    "fee":             "固定費（月会費など）",
    "charge":          "前払金の増減（チャージ）",
    "unknown":         "未分類",
}

# 月次の原価に入れるもの。charge（チャージ）は前払金の出し入れなので入れない。
# fee（月会費）は原価ではなく固定費なので、原価とは別に出す
COST_CATEGORIES = ("purchase", "purchase_adjust", "shipping")


def _category(action: Optional[str]) -> str:
    a = (action or "").strip()
    for word, cat in CATEGORY_RULES:
        if word in a:
            return cat
    return "unknown"


def _num(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_at(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


@router.post("/taotaro/sync")
def sync_transactions(pages: int = 20, limit: int = 100,
                      db: Session = Depends(get_db)):
    """タオタロウの入出金明細を取り込む。

    何度やっても同じ行は増えない（タオタロウの明細IDを主キーにしている）。
    既にある行は金額と区分を上書きする（タオタロウ側で直されることがある）。
    """
    if not taotaro.is_configured():
        raise HTTPException(400, "タオタロウの設定がありません")

    pages = max(1, min(pages, 100))
    limit = max(1, min(limit, 100))

    added, updated, seen = 0, 0, 0
    stopped_early = False
    for page in range(1, pages + 1):
        try:
            d = taotaro.transactions(page=page, limit=limit)
        except Exception as e:
            raise HTTPException(502, f"タオタロウから取れませんでした（{type(e).__name__}: {str(e)[:120]}）")
        items = d.get("items") or []
        if not items:
            break
        for x in items:
            tid = x.get("id")
            if tid is None:
                continue
            seen += 1
            at = _parse_at(x.get("at"))
            row = db.query(TaotaroTransaction).filter(
                TaotaroTransaction.id == int(tid)).first()
            new = row is None
            if new:
                row = TaotaroTransaction(id=int(tid))
                db.add(row)
            row.occurred_at = at
            row.ym = at.strftime("%Y-%m") if at else None
            row.kind = x.get("kind")
            row.action = x.get("action")
            row.category = _category(x.get("action"))
            row.money = _num(x.get("money"))
            row.balance_after = _num(x.get("balance_after"))
            row.exchange_rate = _num(x.get("exchange_rate"))
            row.exchange_money = _num(x.get("exchange_money"))
            row.oid = str(x.get("oid") or "") or None
            row.sid = str(x.get("sid") or "") or None
            row.sn = str(x.get("sn") or "") or None
            row.product_total_price = _num(x.get("product_total_price"))
            row.service_charge = _num(x.get("service_charge"))
            row.remark = x.get("remark")
            if new:
                added += 1
            else:
                updated += 1
        if not d.get("has_more_pages"):
            break
    else:
        # pages を使い切ったのにまだ続きがある。古い月が欠けている可能性がある
        stopped_early = True

    db.commit()
    return {"ok": True, "added": added, "updated": updated, "seen": seen,
            "stopped_early": stopped_early}


@router.get("/taotaro/monthly")
def monthly(months: int = 12, db: Session = Depends(get_db)):
    """月 × 区分の集計。デポジットの内訳はここで分解される。"""
    rows = (db.query(TaotaroTransaction)
            .filter(TaotaroTransaction.ym.isnot(None))
            .order_by(TaotaroTransaction.ym.desc()).all())

    by_ym: dict = {}
    for r in rows:
        m = by_ym.setdefault(r.ym, {
            "ym": r.ym,
            "categories": {},
            "actions": {},
            "count": 0,
        })
        m["count"] += 1
        cat = r.category or "unknown"
        c = m["categories"].setdefault(cat, {"cny": 0.0, "jpy": 0.0, "count": 0})
        c["cny"] += (r.money or 0.0)
        c["jpy"] += (r.exchange_money or 0.0)
        c["count"] += 1
        a = m["actions"].setdefault(r.action or "（区分なし）",
                                    {"cny": 0.0, "jpy": 0.0, "count": 0, "category": cat})
        a["cny"] += (r.money or 0.0)
        a["jpy"] += (r.exchange_money or 0.0)
        a["count"] += 1

    out = []
    for ym in sorted(by_ym.keys(), reverse=True)[:max(1, min(months, 60))]:
        m = by_ym[ym]
        # 原価は引落なのでマイナスで入っている。表では正の数で見たいので符号を返す
        cost = -sum(m["categories"].get(c, {}).get("cny", 0.0) for c in COST_CATEGORIES)
        fee = -m["categories"].get("fee", {}).get("cny", 0.0)
        charge = m["categories"].get("charge", {}).get("cny", 0.0)
        m["cost_cny"] = round(cost, 2)
        m["fee_cny"] = round(fee, 2)
        m["charge_cny"] = round(charge, 2)
        for d in (m["categories"], m["actions"]):
            for v in d.values():
                v["cny"] = round(v["cny"], 2)
                v["jpy"] = round(v["jpy"], 2)
        out.append(m)

    return {
        "months": out,
        "category_labels": CATEGORY_LABELS,
        "cost_categories": list(COST_CATEGORIES),
        "total_rows": len(rows),
    }


@router.get("/taotaro/transactions")
def list_transactions(ym: Optional[str] = None, category: Optional[str] = None,
                      action: Optional[str] = None, sid: Optional[str] = None,
                      limit: int = 500, db: Session = Depends(get_db)):
    """明細。月や区分の数字をクリックしたときに中身を見るためのもの。"""
    q = db.query(TaotaroTransaction)
    if ym:
        q = q.filter(TaotaroTransaction.ym == ym)
    if category:
        q = q.filter(TaotaroTransaction.category == category)
    if action:
        q = q.filter(TaotaroTransaction.action == action)
    if sid:
        q = q.filter(TaotaroTransaction.sid == str(sid))
    rows = (q.order_by(TaotaroTransaction.occurred_at.desc(),
                       TaotaroTransaction.id.desc())
            .limit(max(1, min(limit, 2000))).all())
    return {"items": [{
        "id": r.id,
        "at": r.occurred_at.isoformat() if r.occurred_at else None,
        "ym": r.ym,
        "action": r.action or "",
        "category": r.category or "unknown",
        "money": r.money,
        "exchange_money": r.exchange_money,
        "exchange_rate": r.exchange_rate,
        "balance_after": r.balance_after,
        "oid": r.oid or "",
        "sid": r.sid or "",
        "sn": r.sn or "",
        "remark": r.remark or "",
    } for r in rows]}


@router.get("/taotaro/status")
def status(db: Session = Depends(get_db)):
    """取り込み済みの範囲。いつからいつまで入っているかが分かる。"""
    n = db.query(TaotaroTransaction).count()
    if not n:
        return {"count": 0, "first": None, "last": None, "unknown": 0}
    first = (db.query(TaotaroTransaction)
             .order_by(TaotaroTransaction.occurred_at.asc()).first())
    last = (db.query(TaotaroTransaction)
            .order_by(TaotaroTransaction.occurred_at.desc()).first())
    unknown = (db.query(TaotaroTransaction)
               .filter(TaotaroTransaction.category == "unknown").count())
    return {
        "count": n,
        "first": first.occurred_at.isoformat() if first and first.occurred_at else None,
        "last": last.occurred_at.isoformat() if last and last.occurred_at else None,
        # 分類できなかった区分。ここが0でないなら CATEGORY_RULES に足す
        "unknown": unknown,
    }
