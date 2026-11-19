"""月次管理表（発生ベース会計）。

第一歩として、タオタロウのデポジットの内訳を分解する。

いまの試算表はチャージした日で仕入が計上されている。チャージは
「まとめて入れる前払金」であって、その月に仕入れたものではない。
明細を1行ずつ持って区分ごとに分ければ、その月に実際に発生したぶんだけを
拾える。

設計の全体像は docs/月次管理表_発生ベース会計_設計.md にある。
"""
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
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
# 入出金明細には国際運賃の行がほとんど出てこない（10月1行・11月0行）。
# そこで配送依頼（便）ごとの費用をタオタロウのAPIから取り、
# taotaro_send_orders に保存して、出荷日の月で数える。
#
# 送料の「商品ごとの按分」は仕入管理（インボイスの取り込み）がすでにやっている
# （箱の重量で按分。箱データが無い便は金額比）。結果は CostHistory（商品）と
# MaterialCost（資材）にインボイス番号＝配送依頼の sn ごとに残るので、それを読む。
# インボイスを取り込んでいない便は「未取り込み」と出して気づけるようにする。

# 費用が確定している状態（出荷待ち・出荷済み・受け取り済み）。
# お支払い待ち(7)より前は金額が動くので数えない
_BILLED_STATES = (8, 2, 3)
# これ以上は変わらない状態。保存済みなら詳細を取り直さない
_FINAL_STATES = (2, 3)


@router.post("/freight/sync")
def freight_sync(pages: int = 10, full: bool = False, db: Session = Depends(get_db)):
    """配送依頼ごとの費用をタオタロウから取り込む。

    何度やっても同じ便は増えない（sid が主キー）。受け取り済みなど
    もう変わらない便は、保存済みなら詳細を取り直さない（full=true で全部取り直す）。
    """
    from app.models.taotaro_send_order import TaotaroSendOrder
    if not taotaro.is_configured():
        raise HTTPException(400, "タオタロウの設定がありません")

    added = updated = skipped = 0
    errors = []
    for page in range(1, max(1, min(pages, 50)) + 1):
        try:
            d = taotaro.list_send_orders(page=page, limit=100)
        except Exception as e:
            raise HTTPException(502, f"タオタロウから取れませんでした（{type(e).__name__}: {str(e)[:120]}）")
        for x in d.get("items") or []:
            sid = x.get("sid")
            if sid is None or x.get("state") not in _BILLED_STATES:
                continue
            row = db.query(TaotaroSendOrder).filter(TaotaroSendOrder.sid == int(sid)).first()
            if (row and not full and row.state in _FINAL_STATES
                    and row.state == x.get("state") and row.shipped_date):
                skipped += 1
                continue
            try:
                det = taotaro.get_send_order(int(sid))
            except Exception as e:
                errors.append(f"{x.get('sn') or sid}: {type(e).__name__}")
                continue
            new = row is None
            if new:
                row = TaotaroSendOrder(sid=int(sid))
                db.add(row)
            shipped = taotaro._shipped_date(det)
            row.sn = str(det.get("sn") or x.get("sn") or "").strip() or None
            row.state = det.get("state")
            row.state_label = det.get("state_label") or ""
            row.delivery_name = det.get("delivery_name") or ""
            row.count_weight = _num(det.get("count_weight"))
            row.shipped_date = shipped or None
            row.ym = shipped[:7] if shipped else None
            for k in ("send_price", "server_fee", "freight", "customs_fee",
                      "remote_fee", "total_send_fee"):
                setattr(row, k, _num(det.get(k)))
            if new:
                added += 1
            else:
                updated += 1
        db.commit()
        if not d.get("has_more_pages"):
            break
    return {"ok": True, "added": added, "updated": updated,
            "skipped": skipped, "errors": errors[:20]}


@router.get("/freight/months")
def freight_months(db: Session = Depends(get_db)):
    """便が出荷された月（新しい順）と、最後に取り込んだ日時。"""
    from app.models.taotaro_send_order import TaotaroSendOrder
    rows = db.query(TaotaroSendOrder.ym).distinct().all()
    last = (db.query(TaotaroSendOrder.updated_at)
            .order_by(TaotaroSendOrder.updated_at.desc()).first())
    return {"months": sorted({r[0] for r in rows if r[0]}, reverse=True),
            "synced_at": last[0].isoformat() if last and last[0] else None,
            "count": db.query(TaotaroSendOrder).count()}


@router.get("/freight")
def freight(ym: str, db: Session = Depends(get_db)):
    """その月に出荷された便の費用と、保存済みインボイスの按分結果。"""
    from app.models.cost_history import CostHistory
    from app.models.material_cost import MaterialCost
    from app.models.taotaro_send_order import TaotaroSendOrder

    rows = (db.query(TaotaroSendOrder).filter(TaotaroSendOrder.ym == ym)
            .order_by(TaotaroSendOrder.shipped_date.asc()).all())

    sns = [r.sn for r in rows if r.sn]
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

    r2 = lambda v: round(v or 0, 2)
    ships = []
    for r in rows:
        items = items_of.get(r.sn or "", [])
        # インボイスの按分は「国内運賃＋国際運賃」を配っている。比べるのも同じ範囲
        shipping = r2((r.send_price or 0) + (r.freight or 0))
        alloc = r2(sum(x["freight_cny"] for x in items))
        methods = {x["method"] for x in items if x["method"]}
        ships.append({
            "sid": r.sid, "sn": r.sn or "", "state_label": r.state_label or "",
            "delivery_name": r.delivery_name or "", "weight": r.count_weight,
            "shipped_date": r.shipped_date or "",
            "domestic": r2(r.send_price), "international": r2(r.freight),
            "customs_fee": r2(r.customs_fee), "server_fee": r2(r.server_fee),
            "remote_fee": r2(r.remote_fee), "total_send_fee": r2(r.total_send_fee),
            "shipping": shipping,
            "imported": bool(items),
            "allocated_cny": alloc,
            # 送料（国内＋国際）とインボイスで按分した送料の差（元）。大きければ見直す
            "diff_cny": r2(shipping - alloc) if items else None,
            "method": ("重量" if methods == {"weight"} else "金額比" if methods == {"money"}
                       else "混在" if methods else ""),
            "items": sorted(items, key=lambda x: -x["freight_cny"]),
        })
    tot = lambda k: r2(sum(x[k] for x in ships))
    return {
        "ym": ym,
        "ship_count": len(ships),
        "imported_count": sum(1 for x in ships if x["imported"]),
        "missing": [x["sn"] or str(x["sid"]) for x in ships if not x["imported"]],
        "totals": {k: tot(k) for k in ("domestic", "international", "customs_fee",
                                        "server_fee", "remote_fee", "total_send_fee",
                                        "shipping")},
        "ships": ships,
    }


# ---------- 月次サマリー ----------
#
# 各タブで作った数字を月ごとに1行にまとめる。
#   売上        … 楽天：売上管理で取り込んだ月の売上（RMS）／Amazon：日別実績（daily_sales）
#   当月の仕入  … 発生ベース。商品代（＋値引・調整・削除）は明細の日、
#                 中国国内送料・代行手数料・国際送料・通関手数料は便の出荷日、
#                 関税は輸入許可日。元は月の実勢レートで円にする
#   売上原価    … 期首在庫 ＋ 当月の仕入 − 期末在庫（在庫金額タブの月末確定値）
#   固定費      … タオタロウ月会費など。原価とは別
#   消費税      … 輸入時の消費税・地方消費税は仮払消費税なので、原価に入れず別に出す

def _month_rates(db: Session) -> dict:
    """月ごとの実勢レート（円/元）。明細の円換算額 ÷ 元 の平均。"""
    rows = (db.query(TaotaroTransaction.ym, TaotaroTransaction.money,
                     TaotaroTransaction.exchange_money)
            .filter(TaotaroTransaction.ym.isnot(None)).all())
    acc: dict = {}
    for ym, money, jpy in rows:
        if money and jpy:
            r = abs(jpy) / abs(money)
            if 10 < r < 40:          # 明らかにおかしい行は除く
                a = acc.setdefault(ym, [0.0, 0.0])
                a[0] += abs(jpy)
                a[1] += abs(money)
    return {ym: a[0] / a[1] for ym, a in acc.items() if a[1]}


def _prev_ym(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


@router.get("/summary")
def monthly_summary(months: int = 12, db: Session = Depends(get_db)):
    from collections import defaultdict
    from sqlalchemy import func as F
    from app.models.daily_sales import DailySales
    from app.models.import_permit import ImportPermit
    from app.models.inventory_snapshot import InventorySnapshot
    from app.models.rakuten_sales import RakutenSalesImport
    from app.models.settings import OrderSettings
    from app.models.taotaro_send_order import TaotaroSendOrder

    st = db.query(OrderSettings).first()
    default_rate = float(getattr(st, "exchange_rate", 0) or 21.0)
    rates = _month_rates(db)
    rate_of = lambda ym: rates.get(ym) or default_rate

    m: dict = defaultdict(lambda: defaultdict(float))

    # 売上
    for r in db.query(RakutenSalesImport).all():
        if r.period:
            m[r.period]["sales_rakuten"] += r.total_sales or 0
            m[r.period]["has_rakuten_sales"] = 1
    if db.bind.dialect.name == "postgresql":
        q = (db.query(F.to_char(DailySales.day, "YYYY-MM"), F.sum(DailySales.revenue),
                      F.sum(DailySales.promo_discount))
             .group_by(F.to_char(DailySales.day, "YYYY-MM")).all())
    else:
        tmp: dict = defaultdict(lambda: [0.0, 0.0])
        for d, rev, promo in db.query(DailySales.day, DailySales.revenue, DailySales.promo_discount):
            if d:
                tmp[d.strftime("%Y-%m")][0] += rev or 0
                tmp[d.strftime("%Y-%m")][1] += promo or 0
        q = [(k, v[0], v[1]) for k, v in tmp.items()]
    for ym, rev, promo in q:
        if ym:
            m[ym]["sales_amazon"] += (rev or 0) - (promo or 0)

    # 商品代と固定費（タオタロウ明細）。元を円に
    for t in db.query(TaotaroTransaction).filter(TaotaroTransaction.ym.isnot(None)):
        jpy = -(t.money or 0) * rate_of(t.ym)      # 引落はマイナス → 正の費用に
        if t.category in ("purchase", "purchase_adjust"):
            m[t.ym]["goods"] += jpy
        elif t.category == "fee":
            m[t.ym]["fixed"] += jpy
        elif t.category == "charge":
            m[t.ym]["charge"] += -jpy               # チャージは入金なので正で持つ

    # 便ごとの費用（出荷日の月）
    for s in db.query(TaotaroSendOrder).filter(TaotaroSendOrder.ym.isnot(None)):
        r = rate_of(s.ym)
        m[s.ym]["domestic"] += (s.send_price or 0) * r
        m[s.ym]["agency"] += (s.server_fee or 0) * r
        m[s.ym]["international"] += ((s.freight or 0) + (s.remote_fee or 0)) * r
        m[s.ym]["customs_fee"] += (s.customs_fee or 0) * r

    # 関税・消費税（輸入許可日の月）
    for p in db.query(ImportPermit).filter(ImportPermit.kind == "permit"):
        ym = (p.permit_date or "")[:7]
        if ym:
            m[ym]["duty"] += p.customs_duty or 0
            m[ym]["import_vat"] += (p.consumption_tax or 0) + (p.local_consumption_tax or 0)

    # 月末在庫（楽天＋Amazon）。タオタロウの仕入と突き合わせるのは中国輸入品だけ。
    # 日本メーカー品の仕入はツールに無いので、在庫の増減からは出せない
    inv: dict = defaultdict(float)          # 中国輸入品
    inv_manu: dict = defaultdict(float)     # 日本メーカー品
    inv_all: dict = defaultdict(float)
    inv_pf: dict = defaultdict(set)
    for period, pf, cat, amt in (db.query(InventorySnapshot.period, InventorySnapshot.platform,
                                          InventorySnapshot.category, F.sum(InventorySnapshot.amount))
                                 .group_by(InventorySnapshot.period, InventorySnapshot.platform,
                                           InventorySnapshot.category)):
        inv_all[period] += amt or 0
        if cat == "manufacturer":
            inv_manu[period] += amt or 0
        else:
            inv[period] += amt or 0
        inv_pf[period].add(pf)

    # 請求書から読めた実額。読めている月は見込みより優先する
    from app.models.billing_line import BillingLine
    bill: dict = defaultdict(lambda: defaultdict(float))
    has_invoice: set = set()
    for b in db.query(BillingLine).all():
        if not b.ym:
            continue
        bill[b.ym][b.bucket] += b.amount or 0
        if b.source == "rakuten_rms":
            has_invoice.add(b.ym)

    # メーカー品の仕入。届いた日で計上する（発注日でも支払日でもない）。
    # 分納があるので、入荷履歴を1行ずつ足す
    # メーカー品の仕入は取引先ごとに決める。
    # 請求書があればそれ（発注どおりに届くとは限らず、多く届くことも、
    # 頼んでいないものが入ることもある。実際に請求された額が仕入）。
    # 無ければ入荷履歴で埋める。
    # 月まるごとで切り替えると、請求書を残していない取引先（エジソン・
    # リビック）の仕入が、マレフィオーレの請求書がある月だけ消える
    from app.models.wholesale_invoice import WholesaleInvoiceLine
    from app.models.wholesale_receipt import WholesaleReceipt
    manu_inv: dict = defaultdict(float)      # (ym, 取引先) → 請求書
    manu_rec: dict = defaultdict(float)      # (ym, 取引先) → 入荷履歴
    for r in db.query(WholesaleReceipt.ym, WholesaleReceipt.supplier_name,
                      F.sum(WholesaleReceipt.amount)).group_by(
            WholesaleReceipt.ym, WholesaleReceipt.supplier_name):
        if r[0]:
            manu_rec[(r[0], r[1] or "")] += r[2] or 0
    for r in db.query(WholesaleInvoiceLine.ym, WholesaleInvoiceLine.supplier,
                      F.sum(WholesaleInvoiceLine.amount)).group_by(
            WholesaleInvoiceLine.ym, WholesaleInvoiceLine.supplier):
        if r[0]:
            manu_inv[(r[0], r[1] or "")] += r[2] or 0
    # 銀行の出金。請求書が残っていない仕入（再発行もできない）は、
    # 実際に払った額で埋める（請求書の無い出金を税抜にして出金日の月へ）
    try:
        from app.services import bank_reconcile
        bank = bank_reconcile.fill_by_month(db)
    except Exception:
        bank = {}
    manu_by_supplier: dict = defaultdict(dict)
    for key in (set(manu_inv) | set(manu_rec)
                | {k for k, v in bank.items() if v["fill"] or v["bank_purchase"]}):
        ym_, sup_ = key
        b = bank.get(key) or {}
        fill = b.get("fill", 0.0)
        bank_purchase = b.get("bank_purchase", 0.0)
        # 請求書 ＋ 請求書の無い支払い ＝ 実際に請求・支払いのあった仕入
        inv_amt, rec_amt = manu_inv.get(key, 0.0) + fill, manu_rec.get(key, 0.0)
        if bank_purchase:
            # 月末締め翌月払い・前入金の取引先は、出金がその月の仕入の確定額。
            # 最終的に銀行で合わせる（入荷履歴は参考として残す）
            use = bank_purchase
            manu_by_supplier[ym_][sup_] = {
                "invoice": round(manu_inv.get(key, 0.0)), "receipt": round(rec_amt),
                "used": round(use), "source": "bank",
                "gap": round(abs(use - rec_amt)), "both": bool(rec_amt),
                "bank_paid": round(b.get("paid", 0.0)), "bank_fill": 0,
                "bank_no_invoice_count": 0, "bank_paid_on": b.get("paid_on", [])}
            m[ym_]["manu_purchase"] += use
            m[ym_]["manu_invoice"] += manu_inv.get(key, 0.0)
            m[ym_]["manu_receipt"] += rec_amt
            continue
        # 多いほうを採る。マレフィオーレは納品のたびに請求書を出していて
        # 月をまたぐズレが構造的に起きないので、差が出る＝どちらかが
        # 欠けている。少ないほうを採ると仕入を過少に計上してしまう。
        #   7月・8月 … 発注ツールを使う前なので入荷履歴がほぼ無い → 請求書
        #   10月    … 請求書が2枚しか残っていない → 入荷履歴
        # 差は「🧾 卸の仕入」で1行ずつ追える
        use = max(inv_amt, rec_amt)
        src = ("invoice" if inv_amt >= rec_amt and inv_amt else
               "receipt" if rec_amt else "none")
        manu_by_supplier[ym_][sup_] = {
            "invoice": round(inv_amt), "receipt": round(rec_amt),
            "used": round(use), "source": src,
            # 片方がもう片方を大きく下回る＝資料が欠けている
            "gap": round(abs(inv_amt - rec_amt)),
            "both": bool(inv_amt and rec_amt),
            # 銀行：その月の出金（税込）と、請求書の無い出金から足した仕入（税抜）
            "bank_paid": round(b.get("paid", 0.0)),
            "bank_fill": round(fill),
            "bank_no_invoice_count": b.get("no_invoice_count", 0)}
        m[ym_]["manu_purchase"] += use
        m[ym_]["manu_invoice"] += inv_amt
        m[ym_]["manu_receipt"] += rec_amt

    # 日本メーカー品の売上原価：売上管理（楽天）の「売れた数 × 原価」
    from app.api.routes.rakuten import _is_manufacturer_product
    from app.models.rakuten_product import RakutenProduct
    from app.models.rakuten_sales import RakutenSalesSummary
    manu_skus = {p.sku for p in db.query(RakutenProduct).all()
                 if p.sku and _is_manufacturer_product(p)}
    for r in (db.query(RakutenSalesSummary.period, RakutenSalesSummary.sku_key,
                       RakutenSalesSummary.sales, RakutenSalesSummary.product_cost)
              .filter(RakutenSalesSummary.level == "sku")):
        if r.period and r.sku_key in manu_skus:
            m[r.period]["manu_sales"] += r.sales or 0
            m[r.period]["manu_cogs"] += r.product_cost or 0

    # 販売費。広告・ポイント・クーポンは売上に紐づくので、その売上が立った月
    # ＝発生した月でよい。
    # 親商品の行から拾う。RPP・クーポン広告・アフィリエイトのレポートは
    # 商品管理番号ごとなので、広告費はSKUの行には入っていない
    for r in (db.query(RakutenSalesSummary.period,
                       RakutenSalesSummary.rpp_cost, RakutenSalesSummary.coupon_ad_cost,
                       RakutenSalesSummary.affiliate_cost, RakutenSalesSummary.affiliate_fee,
                       RakutenSalesSummary.point_cost, RakutenSalesSummary.store_coupon,
                       RakutenSalesSummary.coupon_fee, RakutenSalesSummary.platform_fee)
              .filter(RakutenSalesSummary.level == "parent")):
        if not r.period:
            continue
        m[r.period]["ad"] += ((r.rpp_cost or 0) + (r.coupon_ad_cost or 0)
                              + (r.affiliate_cost or 0) + (r.affiliate_fee or 0))
        m[r.period]["promo"] += ((r.point_cost or 0) + (r.store_coupon or 0)
                                 + (r.coupon_fee or 0))
        # 楽天への手数料。いまは率からの見込み。店舗別内訳書を読めたら実額に差し替える
        m[r.period]["platform_fee"] += r.platform_fee or 0

    out = []
    for ym in sorted(m.keys(), reverse=True)[:max(1, min(months, 36))]:
        v = m[ym]
        purchase = sum(v[k] for k in ("goods", "domestic", "agency",
                                      "international", "customs_fee", "duty"))
        sales = v["sales_rakuten"] + v["sales_amazon"]
        begin = inv.get(_prev_ym(ym))
        end = inv.get(ym)
        china_cogs = (begin + purchase - end) if (begin is not None and end is not None) else None
        # メーカー品の売上原価は2通りで出す。
        #   在庫式 … 期首 ＋ 仕入 − 期末。実地棚卸が正なので決算はこちら
        #   販売式 … 売れた数 × 原価。売れたぶんだけで、減耗は入らない
        # 差は棚卸差異（破損・紛失・原価ズレ・記録漏れ）。毎月見れば異常に気づける
        manu_sold = v["manu_cogs"]
        manu_begin = inv_manu.get(_prev_ym(ym))
        manu_end = inv_manu.get(ym)
        # 取引先ごとに請求書／入荷履歴を選んだ合計
        manu_purchase = v["manu_purchase"]
        by_sup = manu_by_supplier.get(ym, {})
        srcs = {x["source"] for x in by_sup.values()}
        manu_purchase_source = (srcs.pop() if len(srcs) == 1
                                else "mixed" if srcs else "receipt")
        manu_by_inv = ((manu_begin + manu_purchase - manu_end)
                       if (manu_begin is not None and manu_end is not None) else None)
        manu_cogs = manu_by_inv if manu_by_inv is not None else manu_sold
        manu_method = "inventory" if manu_by_inv is not None else "sold"
        # 販売式は楽天の売上管理を取り込んだ月しか出ない。取り込んでいない月に
        # 差を出すと、在庫式の全額がそのまま差異に見えてしまう
        manu_variance = ((manu_by_inv - manu_sold)
                         if (manu_by_inv is not None and v["has_rakuten_sales"])
                         else None)
        cogs = (china_cogs + manu_cogs) if china_cogs is not None else None
        # 販売費及び一般管理費。粗利から引くと営業利益になる。
        # 楽天への費用は、請求書が読めている月は実額、無い月は見込み
        # 費目ごとに見る。楽天は品目で遅れ方が違い（決済は2か月、広告は3か月）、
        # 直近の月は決済だけ届いて広告はまだ、ということが普通に起きる。
        # 月まるごと切り替えると、届いていない費目が0になって利益が多く出る
        b = bill.get(ym, {})
        rakuten_fee_bill = (b.get("payment_fee", 0.0) + b.get("system_fee", 0.0)
                            + b.get("rent", 0.0) + b.get("other", 0.0))
        ad = b.get("ad") or v["ad"]
        promo = b.get("promo") or v["promo"]
        rakuten_fee = rakuten_fee_bill or v["platform_fee"]
        sga_source = {
            "ad": "invoice" if b.get("ad") else "estimate",
            "promo": "invoice" if b.get("promo") else "estimate",
            "platform_fee": "invoice" if rakuten_fee_bill else "estimate",
        }
        fee_source = ("invoice" if all(x == "invoice" for x in sga_source.values())
                      else "estimate" if all(x == "estimate" for x in sga_source.values())
                      else "mixed")
        shipping_jpy = b.get("shipping", 0.0)      # ヤマトの請求書
        sga = ad + promo + rakuten_fee + shipping_jpy + v["fixed"]
        gross = (sales - cogs) if cogs is not None else None
        operating = (gross - sga) if gross is not None else None
        out.append({
            "ym": ym,
            "rate": round(rate_of(ym), 3),
            "rate_is_default": ym not in rates,
            "sales_rakuten": round(v["sales_rakuten"]),
            "sales_amazon": round(v["sales_amazon"]),
            "has_rakuten_sales": bool(v["has_rakuten_sales"]),
            "sales": round(sales),
            "purchase": {k: round(v[k]) for k in ("goods", "domestic", "agency",
                                                   "international", "customs_fee", "duty")},
            "purchase_total": round(purchase),
            "inventory_begin": round(begin) if begin is not None else None,
            "inventory_end": round(end) if end is not None else None,
            "inventory_platforms": sorted(inv_pf.get(ym, [])),
            "china_cogs": round(china_cogs) if china_cogs is not None else None,
            "manu_sales": round(v["manu_sales"]),
            "manu_cogs": round(manu_cogs),
            "manu_method": manu_method,
            "manu_purchase": round(manu_purchase),
            "manu_purchase_source": manu_purchase_source,
            "manu_purchase_invoice": round(v["manu_invoice"]),
            "manu_purchase_receipt": round(v["manu_receipt"]),
            "manu_by_supplier": by_sup,
            "manu_inventory_begin": round(manu_begin) if manu_begin is not None else None,
            "manu_inventory_end": round(manu_end) if manu_end is not None else None,
            "manu_cogs_sold": round(manu_sold),
            # 棚卸差異。在庫式 − 販売式
            "manu_variance": round(manu_variance) if manu_variance is not None else None,
            "inventory_end_all": round(inv_all[ym]) if ym in inv_all else None,
            "cogs": round(cogs) if cogs is not None else None,
            # 楽天の売上を取り込んでいない月は、原価だけ立って赤字に見えるので出さない
            "gross_profit": (round(sales - cogs)
                             if cogs is not None and v["has_rakuten_sales"] else None),
            "gross_rate": (round((sales - cogs) / sales * 100, 1)
                           if cogs is not None and sales and v["has_rakuten_sales"] else None),
            "fixed": round(v["fixed"]),
            "sga": {
                "ad": round(ad),
                "promo": round(promo),
                "platform_fee": round(rakuten_fee),
                "shipping": round(shipping_jpy),
                "fixed": round(v["fixed"]),
            },
            "sga_total": round(sga),
            # invoice … 請求書の実額 / estimate … 率からの見込み / mixed … 混在
            "fee_source": fee_source,
            "sga_source": sga_source,
            "has_shipping_invoice": bool(shipping_jpy),
            "operating_profit": (round(operating)
                                 if operating is not None and v["has_rakuten_sales"] else None),
            "operating_rate": (round(operating / sales * 100, 1)
                               if operating is not None and sales and v["has_rakuten_sales"] else None),
            "import_vat": round(v["import_vat"]),
            "charge": round(v["charge"]),
        })
    return {"months": out, "default_rate": default_rate}


# ---------- 請求書から実額を読む ----------
#
# 楽天への手数料とヤマトの送料は、率からの見込みではなく請求書が正。
# 書類タブに入れてある原本をそのまま読む。
#
# 楽天は「精算対象期間」で計上する。3月分のシステム利用料が6月発行の
# 請求書に載っていて、品目ごとに遅れ方も違う（楽天ペイ利用料は2か月、
# 広告は3か月）。発行月で計上するとまるごとずれる。


def _doc_key(no: str) -> str:
    """店舗別内訳書Noの枝番を落とす。

    同じ内容が翌月に「再掲」として -31 → -32 で出てくる。
    枝番を落として同じものと見なせば、二重に数えない。
    """
    return (no or "").rsplit("-", 1)[0] if "-" in (no or "") else (no or "")


@router.post("/billing/parse")
def billing_parse(db: Session = Depends(get_db)):
    """書類タブに入っている請求書を読んで、明細を取り込む。

    何度やっても増えない（同じ請求書の行は入れ替える）。
    """
    from app.models.billing_line import BillingLine
    from app.models.import_permit import ImportPermit
    from app.services import doc_period, invoice_parse

    docs = (db.query(ImportPermit)
            .filter(ImportPermit.kind.in_(("rms", "yamato"))).all())
    added = 0
    failed = []
    seen_keys = set()
    for d in docs:
        if not d.pdf:
            continue
        text = doc_period.text_of(d.pdf, d.filename or "")
        if not text:
            failed.append({"id": d.id, "file": d.filename, "why": "文字が取れません"})
            continue
        if d.kind == "rms":
            r = invoice_parse.parse_rakuten_rms(text)
            if not r["items"]:
                # 集約版帳票（Billing_Summary）は品目の明細を持たない。
                # 同じ内容は店舗別内訳書にあるので、読めなくてよい
                if "Billing_Summary" not in (d.filename or ""):
                    failed.append({"id": d.id, "file": d.filename, "why": "明細が読めません"})
                continue
            key = (_doc_key(r["doc_no"]), r["shop_id"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            db.query(BillingLine).filter(
                BillingLine.source == "rakuten_rms",
                BillingLine.doc_no == _doc_key(r["doc_no"]),
                BillingLine.shop_id == r["shop_id"]).delete()
            for x in r["items"]:
                db.add(BillingLine(
                    source="rakuten_rms", document_id=d.id,
                    doc_no=_doc_key(r["doc_no"]), shop_id=r["shop_id"], shop=r["shop"],
                    bucket=x["bucket"], name=x["name"],
                    period_start=x["period_start"], period_end=x["period_end"],
                    ym=x["ym"], amount=x["amount"]))
                added += 1
        else:
            r = invoice_parse.parse_yamato(text)
            if not r.get("ok"):
                failed.append({"id": d.id, "file": d.filename, "why": "合計が決まりません"})
                continue
            # 計上月は書類タブで決まっている月（ファイル名の締め日から
            # 振り分けていて、画面で付け替えもできる）
            ym = (d.permit_date or "")[:7] or None
            if not re.fullmatch(r"\d{4}-\d{2}", ym or ""):
                failed.append({"id": d.id, "file": d.filename, "why": "何月分か決まりません"})
                continue
            db.query(BillingLine).filter(
                BillingLine.source == "yamato",
                BillingLine.doc_no == r["doc_no"]).delete()
            db.add(BillingLine(
                source="yamato", document_id=d.id, doc_no=r["doc_no"],
                bucket="shipping", name="ヤマト運輸 送料",
                period_end=None, ym=ym, amount=r["amount"]))
            added += 1
    db.commit()
    return {"ok": True, "documents": len(docs), "lines": added, "failed": failed[:20]}


@router.get("/billing/monthly")
def billing_monthly(db: Session = Depends(get_db)):
    """月 × 費目。請求書から読めた実額。"""
    from app.models.billing_line import BillingLine
    from app.services.invoice_parse import BUCKET_LABEL

    by: dict = {}
    for r in db.query(BillingLine).all():
        if not r.ym:
            continue
        m = by.setdefault(r.ym, {"ym": r.ym, "buckets": {}, "items": []})
        m["buckets"][r.bucket] = m["buckets"].get(r.bucket, 0) + (r.amount or 0)
        m["items"].append({
            "source": r.source, "shop": r.shop or "", "bucket": r.bucket,
            "name": r.name or "", "amount": r.amount or 0,
            "period": f"{r.period_start or ''}〜{r.period_end or ''}".strip("〜"),
        })
    for m in by.values():
        m["total"] = sum(m["buckets"].values())
        m["items"].sort(key=lambda x: -x["amount"])
    return {"months": [by[k] for k in sorted(by, reverse=True)],
            "bucket_labels": BUCKET_LABEL}


# ---------- 卸の請求書（メーカー品の仕入） ----------
#
# 発注どおりに届くとは限らないので、仕入の金額は請求書を正にする。
# 請求書は納品のたびに出ているので、請求日をそのまま発生日に使える。
# ただし請求書のDL漏れもあるため、請求書が無い月は入荷履歴で埋める。

# 請求書の差出人から取引先を決める。発注の取引先名と字面が違う
SUPPLIER_WORDS = [
    ("Mare Fiore", "マレフィオーレ"),
    ("マレフィオーレ", "マレフィオーレ"),
    ("エジソン", "株式会社エジソン販売"),
    ("リビック", "株式会社リビック"),
]


def _supplier_of(text: str, filename: str) -> str:
    hay = (text or "") + " " + (filename or "")
    for word, name in SUPPLIER_WORDS:
        if word in hay:
            return name
    return "（取引先不明）"


def _norm(s: str) -> str:
    """品名を突き合わせるための形にそろえる。

    請求書は「DENT. チェックアップ ジェル バナナ 60g」、発注は
    「チェックアップジェルバナナ」のように書き方が違う。
    空白と記号を落とせば、片方がもう片方を含む形になる。
    """
    out = []
    for ch in (s or ""):
        if ch.isalnum() or ord(ch) > 0x2000:
            out.append(ch)
    return "".join(out).replace("DENT", "").upper()


@router.post("/wholesale-invoices/parse")
def wholesale_invoices_parse(db: Session = Depends(get_db)):
    """書類タブの「卸請求書」を読んで、明細を取り込む。

    何度やっても増えない（同じ請求Noの行は入れ替える）。
    修正版が後から来たときも、入れ直せば新しいほうになる。
    """
    from app.models.import_permit import ImportPermit
    from app.models.wholesale_invoice import WholesaleInvoiceLine
    from app.services import doc_period, invoice_parse

    docs = (db.query(ImportPermit)
            .filter(ImportPermit.kind == "wholesale")
            .order_by(ImportPermit.id.asc()).all())
    added, read, moved = 0, 0, 0
    failed = []
    revised_keys = set()
    for d in docs:
        if not d.pdf:
            continue
        text = doc_period.text_of(d.pdf, d.filename or "")
        if not text:
            failed.append({"id": d.id, "file": d.filename,
                           "why": "文字が取れません（画像のPDFです）"})
            continue
        r = invoice_parse.parse_wholesale_invoice(text)
        if not r["ok"]:
            why = ("明細が見つかりません" if not r["items"]
                   else "明細の合計と小計が合いません")
            failed.append({"id": d.id, "file": d.filename, "why": why})
            continue
        if not r["issued"]:
            # 請求日が無いと月に入れられない（返金の控えなど、請求書でない
            # 書類が混ざっていることがある）
            failed.append({"id": d.id, "file": d.filename,
                           "why": "請求日が読めません"})
            continue
        supplier = _supplier_of(text, d.filename or "")
        no = r["doc_no"] or f"file-{d.id}"
        key = (supplier, no)
        # 同じ請求Noで「修正版」が来ることがある。修正版があればそちらを採り、
        # あとから元の版を読んでも上書きしない
        if key in revised_keys and not r["revised"]:
            continue
        # 書類タブの月も請求日に合わせる。卸の請求書は納品のたびに出ていて
        # 請求日＝到着日なので、ほかの請求書のように前月へ寄せてはいけない。
        # 先に入れたぶんは前月に振り分けられているので、ここで直す
        if r["issued"]:
            want = r["issued"][:7] + "-01"
            if (d.permit_date or "") != want:
                d.permit_date = want
                moved += 1
        db.query(WholesaleInvoiceLine).filter(
            WholesaleInvoiceLine.doc_no == no,
            WholesaleInvoiceLine.supplier == supplier).delete()
        for x in r["items"]:
            db.add(WholesaleInvoiceLine(
                document_id=d.id, supplier=supplier, doc_no=no,
                issued=r["issued"] or None, ym=(r["issued"] or "")[:7] or None,
                name=x["name"], qty=x["qty"], unit_price=x["unit_price"],
                amount=x["amount"], note=x.get("note") or None))
            added += 1
        if r["revised"]:
            revised_keys.add(key)
        read += 1
    db.commit()
    return {"ok": True, "documents": len(docs), "read": read,
            "lines": added, "moved": moved, "failed": failed[:30]}


@router.get("/wholesale-invoices/monthly")
def wholesale_invoices_monthly(db: Session = Depends(get_db)):
    """月 × 取引先。請求書から読めたメーカー品の仕入（税抜）。"""
    from app.models.wholesale_invoice import WholesaleInvoiceLine
    by: dict = {}
    for r in db.query(WholesaleInvoiceLine).all():
        if not r.ym:
            continue
        m = by.setdefault(r.ym, {"ym": r.ym, "amount": 0.0, "count": 0,
                                 "suppliers": {}, "docs": set()})
        m["amount"] += r.amount or 0
        m["count"] += 1
        m["suppliers"][r.supplier] = round(
            m["suppliers"].get(r.supplier, 0) + (r.amount or 0), 2)
        m["docs"].add(r.doc_no)
    out = []
    for ym in sorted(by, reverse=True):
        m = by[ym]
        m["amount"] = round(m["amount"], 2)
        m["invoices"] = len(m.pop("docs"))
        out.append(m)
    return {"months": out}


@router.get("/wholesale-invoices/reconcile")
def wholesale_reconcile(ym: str, db: Session = Depends(get_db)):
    """その月の 請求書 と 入荷履歴 を突き合わせる。

    品名の書き方が違うので、空白と記号を落として片方がもう片方を
    含むかで見る。付かなかったものは、それぞれ片側だけとして出す。
    """
    from app.models.wholesale_invoice import WholesaleInvoiceLine
    from app.models.wholesale_receipt import WholesaleReceipt

    inv = db.query(WholesaleInvoiceLine).filter(WholesaleInvoiceLine.ym == ym).all()
    rec = db.query(WholesaleReceipt).filter(WholesaleReceipt.ym == ym).all()

    recs = [{"name": r.name or "", "qty": r.qty or 0,
             "amount": round(r.amount or 0), "key": _norm(r.name or ""),
             "used": False, "supplier": r.supplier_name or ""} for r in rec]

    rows = []
    for i in inv:
        key = _norm(i.name or "")
        hit = None
        for r in recs:
            if r["used"] or not r["key"]:
                continue
            if key and (key in r["key"] or r["key"] in key):
                hit = r
                r["used"] = True
                break
        rows.append({
            "name": i.name, "supplier": i.supplier, "doc_no": i.doc_no,
            "issued": i.issued,
            "inv_qty": i.qty, "inv_amount": round(i.amount or 0),
            "rec_name": hit["name"] if hit else "",
            "rec_qty": hit["qty"] if hit else None,
            "rec_amount": hit["amount"] if hit else None,
            "diff_qty": (i.qty - hit["qty"]) if hit else None,
            "diff_amount": (round(i.amount or 0) - hit["amount"]) if hit else None,
        })
    only_receipt = [{"name": r["name"], "supplier": r["supplier"],
                     "qty": r["qty"], "amount": r["amount"]}
                    for r in recs if not r["used"]]

    inv_total = round(sum(x["inv_amount"] for x in rows))
    rec_total = round(sum(r["amount"] for r in recs))
    return {
        "ym": ym,
        "invoice_total": inv_total,
        "receipt_total": rec_total,
        "diff": inv_total - rec_total,
        "rows": sorted(rows, key=lambda x: -(abs(x["diff_amount"] or 0))),
        "only_receipt": only_receipt,
    }


# ---------- 銀行の出金で卸の仕入を合わせる ----------
#
# 請求書が残っていない仕入がある（再発行もできない）。楽天銀行の入出金明細CSVから
# 卸への出金だけを拾い、請求書と1件ずつ突き合わせる。ほかの行は保存しない。

@router.post("/bank/import")
async def bank_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """楽天銀行の入出金明細CSVを入れる。何度入れても同じ出金は増えない。"""
    from app.models.bank_payment import BankPayment
    from app.services import bank_reconcile
    try:
        rows = bank_reconcile.parse_rakuten_csv(await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))
    added = 0
    for r in rows:
        if db.query(BankPayment).filter(BankPayment.key == r["key"]).first():
            continue
        db.add(BankPayment(**r))
        added += 1
    db.commit()
    days = sorted(r["paid_on"] for r in rows)
    by_sup: dict = defaultdict(int)
    for r in rows:
        by_sup[r["supplier"]] += 1
    return {"ok": True, "found": len(rows), "added": added,
            "from": days[0] if days else None, "to": days[-1] if days else None,
            "suppliers": dict(by_sup)}


@router.get("/bank/reconcile")
def bank_reconcile_view(db: Session = Depends(get_db)):
    """出金と請求書の突き合わせ。請求書の無い出金・出金の無い請求書を出す。"""
    from app.models.bank_payment import BankPayment
    from app.services import bank_reconcile as br
    r = br.reconcile(db)
    rng = db.query(BankPayment.paid_on).order_by(BankPayment.paid_on.asc()).all()
    return {
        "from": rng[0][0] if rng else None, "to": rng[-1][0] if rng else None,
        "matched_count": len(r["matched"]),
        "unmatched": sorted(
            [{**p, "fill": p["supplier"] in br.FILL_SUPPLIERS,
              "net": round(p["amount"] / br.TAX)} for p in r["unmatched"]],
            key=lambda x: x["paid_on"]),
        # 銀行の期間内に請求日があるのに、出金に当たらなかった請求書
        "unpaid_docs": sorted(
            [d for d in r["unpaid_docs"]
             if rng and rng[0][0] <= (d.get("issued") or "") <= rng[-1][0]],
            key=lambda d: d.get("issued") or ""),
        "fill_suppliers": sorted(br.FILL_SUPPLIERS),
    }


# ---------- 税理士に見せる公開URL ----------
#
# 月次管理表には実際の売上と利益が出るので、誰でも開ける形にはしない。
# 合言葉つきのURLでだけ開く。合言葉はここで作ってDBに持ち、
# いつでも作り直せる（作り直すと前のURLは開かなくなる）。


def _share_url(token: str) -> str:
    return ("https://misa-sep13.github.io/china-import-tool/"
            f"#/accounting-public?share={token}")


@router.get("/share")
def get_share(db: Session = Depends(get_db)):
    """いまの公開URL。まだ作っていなければ token は空。"""
    from app.models.settings import OrderSettings
    st = db.query(OrderSettings).first()
    token = (getattr(st, "accounting_share_token", "") or "") if st else ""
    return {"token": token, "url": _share_url(token) if token else ""}


@router.post("/share")
def make_share(db: Session = Depends(get_db)):
    """公開URLを作る・作り直す。作り直すと前のURLは開かなくなる。"""
    import secrets
    from app.models.settings import OrderSettings
    st = db.query(OrderSettings).first()
    if not st:
        st = OrderSettings(id=1)
        db.add(st)
    st.accounting_share_token = secrets.token_urlsafe(24)
    db.commit()
    return {"token": st.accounting_share_token,
            "url": _share_url(st.accounting_share_token)}


@router.delete("/share")
def drop_share(db: Session = Depends(get_db)):
    """公開をやめる。URLは開かなくなる。"""
    from app.models.settings import OrderSettings
    st = db.query(OrderSettings).first()
    if st:
        st.accounting_share_token = None
        db.commit()
    return {"ok": True, "token": "", "url": ""}
