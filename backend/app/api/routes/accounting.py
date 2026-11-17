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


# ---------- 関税・消費税（輸入許可日で計上） ----------
#
# 輸入許可書は import_permits に保存済み。計上日は輸入許可日（到着日は実データが無い）。
# 会計上の扱いが違うので分けて出す：
#   ・関税 … 仕入原価（仕入諸掛）
#   ・消費税・地方消費税 … 仮払消費税。原価には入れない
# 申告番号で保存済みインボイスと結び付け、商品原価へ按分済みかも出す。

@router.get("/import-tax/monthly")
def import_tax_monthly(db: Session = Depends(get_db)):
    """月ごと（輸入許可日の月）の関税・消費税の合計。"""
    from app.models.import_permit import ImportPermit
    rows = (db.query(ImportPermit)
            .filter(ImportPermit.kind == "permit").all())
    out: dict = {}
    for p in rows:
        ym = (p.permit_date or "")[:7] or "日付なし"
        m = out.setdefault(ym, {"ym": ym, "count": 0, "customs_duty": 0,
                                "consumption_tax": 0, "local_consumption_tax": 0,
                                "total_tax": 0})
        m["count"] += 1
        m["customs_duty"] += p.customs_duty or 0
        m["consumption_tax"] += p.consumption_tax or 0
        m["local_consumption_tax"] += p.local_consumption_tax or 0
        m["total_tax"] += p.total_tax or 0
    return {"months": sorted(out.values(), key=lambda x: x["ym"], reverse=True)}


@router.get("/import-tax")
def import_tax(ym: str, db: Session = Depends(get_db)):
    """その月に許可された輸入許可書の一覧と、インボイスへの按分状況。"""
    from app.models.import_permit import ImportPermit
    from app.models.invoice import Invoice
    rows = (db.query(ImportPermit)
            .filter(ImportPermit.kind == "permit",
                    ImportPermit.permit_date.like(f"{ym}%"))
            .order_by(ImportPermit.permit_date.asc()).all())
    nos = [p.permit_no for p in rows if p.permit_no]
    invs = (db.query(Invoice).filter(Invoice.declaration_no.in_(nos)).all() if nos else [])
    inv_of = {}
    for i in invs:
        inv_of.setdefault(i.declaration_no, []).append(i.invoice_no or "")
    items = [{
        "id": p.id, "permit_no": p.permit_no or "", "permit_date": p.permit_date or "",
        "transport": {"sea": "船便", "air": "航空便"}.get(p.transport or "", p.transport or ""),
        "permit_cny": p.permit_cny or 0, "weight": p.cargo_weight or 0,
        "packages": p.package_count or 0,
        "customs_duty": p.customs_duty or 0,
        "consumption_tax": p.consumption_tax or 0,
        "local_consumption_tax": p.local_consumption_tax or 0,
        "total_tax": p.total_tax or 0,
        # 保存済みインボイス（申告番号で照合）。あれば商品原価へ按分済み
        "invoices": inv_of.get(p.permit_no or "", []),
        "has_pdf": bool(p.size_bytes),
    } for p in rows]
    tot = lambda k: sum(x[k] for x in items)
    return {
        "ym": ym, "count": len(items),
        "customs_duty": tot("customs_duty"),
        "consumption_tax": tot("consumption_tax"),
        "local_consumption_tax": tot("local_consumption_tax"),
        "total_tax": tot("total_tax"),
        "not_allocated": [x["permit_no"] for x in items if not x["invoices"]],
        "items": items,
    }


# ---------- 便ごとの送料 ----------
#
# 送料の「商品ごとの按分」は仕入管理（インボイスの取り込み）がすでにやっている
# （箱の重量で按分。箱データが無い便は金額比。通関料は金額比、税は申告欄ごと）。
# 結果は CostHistory（商品）と MaterialCost（資材）に便＝インボイス番号ごとに残る。
# ここでは作り直さず、それを読むだけにする。
#   ・月の運賃（実額）… タオタロウの明細の国際運賃・国内運賃（引落日の月）
#   ・商品ごとの内訳 … 保存済みのインボイス（インボイス番号＝配送依頼の sn）
# インボイスを取り込んでいない便は「未取り込み」と出して気づけるようにする。

@router.get("/freight/months")
def freight_months(db: Session = Depends(get_db)):
    """運賃の引落がある月（新しい順）。"""
    rows = (db.query(TaotaroTransaction.ym)
            .filter(TaotaroTransaction.category == "shipping")
            .distinct().all())
    return {"months": sorted({r[0] for r in rows if r[0]}, reverse=True)}


@router.get("/freight")
def freight(ym: str, db: Session = Depends(get_db)):
    """その月に運賃が引き落とされた便と、保存済みインボイスの按分結果。"""
    from app.models.cost_history import CostHistory
    from app.models.material_cost import MaterialCost

    txs = (db.query(TaotaroTransaction)
           .filter(TaotaroTransaction.category == "shipping",
                   TaotaroTransaction.ym == ym)
           .order_by(TaotaroTransaction.occurred_at.asc()).all())

    by_ship: dict = {}
    for t in txs:
        key = (t.sn or "").strip() or f"sid:{t.sid or '?'}"
        s = by_ship.setdefault(key, {
            "sn": (t.sn or "").strip(), "sid": t.sid or "",
            "first_at": t.occurred_at.isoformat() if t.occurred_at else None,
            "domestic": 0.0, "international": 0.0, "other": 0.0, "lines": 0,
        })
        amt = -(t.money or 0)      # 引落はマイナスで入っている
        a = t.action or ""
        if "国内" in a:
            s["domestic"] += amt
        elif "国際" in a:
            s["international"] += amt
        else:
            s["other"] += amt
        s["lines"] += 1

    sns = [s["sn"] for s in by_ship.values() if s["sn"]]
    costs = (db.query(CostHistory).filter(CostHistory.invoice_no.in_(sns)).all()
             if sns else [])
    mats = (db.query(MaterialCost).filter(MaterialCost.invoice_no.in_(sns)).all()
            if sns else [])
    items_of: dict = {}
    for c in costs:
        items_of.setdefault(c.invoice_no, []).append({
            "kind": "商品", "source": c.source or "", "sku": c.sku or "",
            "qty": c.qty or 0, "goods_cny": round(c.total_price_cny or 0, 2),
            "freight_cny": round(c.freight_alloc_cny or 0, 2),
            "tax_jpy": round(c.tax_alloc_jpy or 0),
            "customs_jpy": round(c.customs_fee_alloc_jpy or 0),
            "cost_jpy": round(c.cost_jpy or 0, 1),
            "method": c.freight_method or "",
        })
    for m in mats:
        items_of.setdefault(m.invoice_no, []).append({
            "kind": "資材", "source": m.source or "", "sku": m.sku or "",
            "qty": m.qty or 0, "goods_cny": round(m.total_price_cny or 0, 2),
            "freight_cny": round(m.freight_alloc_cny or 0, 2),
            "tax_jpy": round(m.tax_alloc_jpy or 0),
            "customs_jpy": round(m.customs_fee_alloc_jpy or 0),
            "cost_jpy": round(m.total_cost_jpy or 0, 1),
            "method": "",
        })

    ships = []
    for s in by_ship.values():
        total = round(s["domestic"] + s["international"] + s["other"], 2)
        items = items_of.get(s["sn"], [])
        alloc = round(sum(x["freight_cny"] for x in items), 2)
        methods = {x["method"] for x in items if x["method"]}
        ships.append({
            **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items()},
            "total": total,
            "imported": bool(items),
            "allocated_cny": alloc,
            # 明細の運賃とインボイスで按分した送料の差（元）。大きければ見直す
            "diff_cny": round(total - alloc, 2) if items else None,
            "method": ("重量" if methods == {"weight"} else "金額比" if methods == {"money"}
                       else "混在" if methods else ""),
            "items": sorted(items, key=lambda x: -x["freight_cny"]),
        })
    ships.sort(key=lambda x: x["first_at"] or "")
    return {
        "ym": ym,
        "total_cny": round(sum(x["total"] for x in ships), 2),
        "ship_count": len(ships),
        "imported_count": sum(1 for x in ships if x["imported"]),
        "missing": [x["sn"] or x["sid"] for x in ships if not x["imported"]],
        "ships": ships,
    }
