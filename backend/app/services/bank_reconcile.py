"""銀行の出金で卸の仕入を合わせる。

請求書が残っていない仕入がある（再発行もできない）。最終的には実際に
お金が出た記録が正しいので、楽天銀行の入出金明細CSVから卸への出金だけを
拾い、請求書と1件ずつ突き合わせる。

マレフィオーレは納品のたびに請求書を出し、その日のうちに税込額を振り込む
（請求額 × 1.1 ＝ 出金額）。2枚をまとめて払った日もある。
請求書に当たらなかった出金は「請求書の無い仕入」として、出金日の月に
税抜（÷1.1）で仕入に足す。

エジソン・リビックは支払いの間隔が不規則なので、月ごとに足すと二重に
数えるおそれがある。いまは並べて見せるだけにする（FILL_SUPPLIERS に入れない）。
"""
import csv
import io
import unicodedata
from collections import defaultdict
from itertools import combinations
from typing import Dict, List, Optional

# 明細の「入出金先内容」に含まれる文字 → 卸の仕入で使っている取引先名。
# 全角・半角カナの揺れは NFKC で揃えてから、空白を抜いて見る
SUPPLIER_PATTERNS = [
    (("マレフイオ",), "マレフィオーレ"),
    (("エシ", "ソンハンハ"), "株式会社エジソン販売"),
    (("リヒ", "ツク"), "株式会社リビック"),
    (("イノウ", "エンテツク"), "イノベンテック"),
]

# 請求書が無い支払いを仕入に足す取引先（納品ごとに請求・即日払い）
FILL_SUPPLIERS = {"マレフィオーレ"}

# 支払い条件。出金をどの月の仕入にするか（2026-11-20 ユーザーから）
#   per_invoice … 請求日に即日払い。出金を請求書に当て、当たらない分を出金月に足す
#   next_month  … 月末締め・翌月払い。出金月の前月の仕入（出金額が前月分の確定額）
#   prepay      … 前入金・数日で着。出金月の仕入
PAY_TERMS = {
    "マレフィオーレ": "per_invoice",
    "株式会社エジソン販売": "next_month",
    "イノベンテック": "next_month",
    "株式会社リビック": "prepay",
}


def _prev_ym(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def purchase_ym(supplier: str, paid_ym: str) -> str:
    return _prev_ym(paid_ym) if PAY_TERMS.get(supplier) == "next_month" else paid_ym


# 取引先名の揺れ（商品マスタは「エジソン販売」、銀行は「株式会社エジソン販売」など）
_SUPPLIER_KEY = {
    "株式会社エジソン販売": "エジソン",
    "イノベンテック": "INNOVENTECH",
    "株式会社リビック": "リビック",
    "マレフィオーレ": "マレフィオーレ",
}


def arrivals_by_month(db, supplier: str) -> Dict[str, float]:
    """在庫に入った記録（メーカー入荷・卸入荷）から、月ごとの入荷金額（税抜）を出す。

    発注ツールを使う前（〜8月）の入荷も、在庫の操作ログには残っている。
    原価マスタは税込なので÷1.1。日時はUTCなので日本時間に直して月を決める。
    """
    from datetime import timedelta
    from app.models.inventory_reflection_log import InventoryReflectionLog
    from app.models.rakuten_product import RakutenProduct
    key = _SUPPLIER_KEY.get(supplier, supplier)
    prods = {p.sku: p for p in db.query(RakutenProduct).all()
             if p.sku and key.lower() in (p.supplier or "").lower()}
    if not prods:
        return {}
    out: Dict[str, float] = defaultdict(float)
    rows = (db.query(InventoryReflectionLog)
            .filter(InventoryReflectionLog.sku.in_(list(prods)),
                    InventoryReflectionLog.received_qty > 0).all())
    for r in rows:
        if "receive" not in (r.source or "") or not r.created_at:
            continue
        ym = (r.created_at + timedelta(hours=9)).strftime("%Y-%m")
        out[ym] += (r.received_qty or 0) * float(prods[r.sku].cost_jpy or 0) / TAX
    return dict(out)


def _split_next_month(payments: List[dict], arrivals: Dict[str, float]) -> List[tuple]:
    """月末締め翌月払いの出金を、仕入の月に割り当てる。

    ふつうは出金月の前月。ただし払っていない月があると、次の出金に
    何か月分かがまとまる（エジソン：7月・8月分を9/03にまとめて払った）。
    前の出金の対象月より後で、前月までの入荷のある月（最大3か月）に、
    入荷金額の割合で分ける。入荷の記録が無ければ前月にまとめる。
    戻り値: [(仕入の月, 金額, 出金), ...]
    """
    out = []
    last = None
    for p in sorted(payments, key=lambda x: x["paid_on"]):
        target = _prev_ym(p["ym"])
        months = [target]
        if last:
            m = target
            for _ in range(2):
                m = _prev_ym(m)
                if m <= last:
                    break
                months.insert(0, m)
        weights = {m: arrivals.get(m, 0.0) for m in months}
        total = sum(weights.values())
        if len(months) > 1 and total > 0:
            for m in months:
                if weights[m] > 0:
                    out.append((m, p["amount"] * weights[m] / total, p))
        else:
            out.append((target, p["amount"], p))
        last = max(target, last) if last else target
    return out

TAX = 1.1
TOL = 3   # 円。端数の丸め違い


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").replace(" ", "").replace("　", "")


def supplier_of(memo: str) -> Optional[str]:
    m = _norm(memo)
    for words, name in SUPPLIER_PATTERNS:
        if all(w in m for w in words):
            return name
    return None


def _decode(content: bytes) -> str:
    for enc in ("cp932", "utf-8-sig"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSVの文字コードが読めません（楽天銀行のCSVをそのまま入れてください）")


def parse_rakuten_csv(content: bytes) -> List[dict]:
    """楽天銀行の入出金明細CSV（取引日,入出金(円),残高(円),入出金先内容）。

    卸への出金だけを返す。ほかの行は捨てる（保存しない）。
    """
    rows = list(csv.reader(io.StringIO(_decode(content))))
    if not rows or "取引日" not in rows[0][0]:
        raise ValueError("楽天銀行の入出金明細CSVではないようです（1行目が「取引日」で始まりません）")
    out, seq = [], defaultdict(int)
    for r in rows[1:]:
        if len(r) < 4 or not r[0].strip().isdigit():
            continue
        try:
            amt = int(r[1])
        except ValueError:
            continue
        if amt >= 0:
            continue
        sup = supplier_of(r[3])
        if not sup:
            continue
        d = r[0].strip()
        day = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        k0 = f"{day}|{-amt}|{sup}"
        seq[k0] += 1
        out.append({"key": f"{k0}|{seq[k0]}", "paid_on": day, "ym": day[:7],
                    "supplier": sup, "amount": float(-amt)})
    return out


def match_payments(payments: List[dict], docs: List[dict]) -> dict:
    """出金と請求書を突き合わせる。

    payments: [{key, paid_on, amount, supplier}]（税込）
    docs:     [{doc_no, issued, ym, amount, supplier}]（請求書1枚ずつ・税抜）
    1枚の税込額に一致 → 2枚の合計に一致、の順に当てる。近い日付の請求書を優先。
    """
    used = set()
    matched, unmatched = [], []
    by_sup = defaultdict(list)
    for d in docs:
        by_sup[d["supplier"]].append(d)

    def near(p, d):
        return abs(_days(p["paid_on"]) - _days(d.get("issued") or d["ym"] + "-15"))

    for p in sorted(payments, key=lambda x: x["paid_on"]):
        cands = [d for d in by_sup.get(p["supplier"], []) if d["doc_no"] not in used]
        hit = None
        one = [d for d in cands if abs(round(d["amount"] * TAX) - p["amount"]) <= TOL]
        if one:
            hit = [min(one, key=lambda d: near(p, d))]
        else:
            near_c = sorted(cands, key=lambda d: near(p, d))[:12]
            for a, b in combinations(near_c, 2):
                if abs(round(a["amount"] * TAX) + round(b["amount"] * TAX) - p["amount"]) <= TOL:
                    hit = [a, b]
                    break
        if hit:
            for d in hit:
                used.add(d["doc_no"])
            matched.append({**p, "docs": [d["doc_no"] for d in hit]})
        else:
            unmatched.append(p)
    unpaid = [d for docs_ in by_sup.values() for d in docs_ if d["doc_no"] not in used]
    return {"matched": matched, "unmatched": unmatched, "unpaid_docs": unpaid}


def _days(day: str) -> int:
    from datetime import date
    try:
        y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
        return date(y, m, d).toordinal()
    except (ValueError, IndexError):
        return 0


def invoice_docs(db) -> List[dict]:
    """保存済みの卸請求書を1枚ずつ（税抜の合計）にする。"""
    from app.models.wholesale_invoice import WholesaleInvoiceLine
    by: Dict[tuple, dict] = {}
    for r in db.query(WholesaleInvoiceLine).all():
        k = (r.supplier or "", r.doc_no or "")
        d = by.setdefault(k, {"supplier": k[0], "doc_no": k[1], "issued": r.issued or "",
                              "ym": r.ym or "", "amount": 0.0})
        d["amount"] += r.amount or 0
    return list(by.values())


def reconcile(db) -> dict:
    from app.models.bank_payment import BankPayment
    pays = [{"key": p.key, "paid_on": p.paid_on, "ym": p.ym, "supplier": p.supplier,
             "amount": p.amount} for p in db.query(BankPayment).all()]
    return match_payments(pays, invoice_docs(db))


def covered_months(db) -> set:
    """銀行の明細が月の初めから終わりまでそろっている月。

    この月は銀行が正。マレフィオーレは「請求の翌日着」なので、月末の請求分は
    翌月の入荷履歴に入る。入荷履歴との多いほうを採ると、同じ商品を
    請求書の月と入荷の月で二重に数えてしまう。
    """
    import calendar
    from app.models.bank_payment import BankStatement
    out = set()
    for st in db.query(BankStatement).all():
        first, last = st.from_day or "", st.to_day or ""
        if not first or not last:
            continue
        y, m = int(first[:4]), int(first[5:7])
        while f"{y}-{m:02d}" <= last[:7]:
            ym = f"{y}-{m:02d}"
            end = f"{ym}-{calendar.monthrange(y, m)[1]:02d}"
            if first <= f"{ym}-01" and last >= end:
                out.add(ym)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def statement_range(content: bytes) -> tuple:
    """CSVの最初と最後の取引日。"""
    days = []
    for r in csv.reader(io.StringIO(_decode(content))):
        if r and r[0].strip().isdigit() and len(r[0].strip()) == 8:
            d = r[0].strip()
            days.append(f"{d[:4]}-{d[4:6]}-{d[6:8]}")
    return (min(days), max(days)) if days else ("", "")


def fill_by_month(db) -> Dict[tuple, dict]:
    """(仕入の月, 取引先) → 銀行の情報。

    per_invoice（マレフィオーレ）… 請求書の無い出金を税抜で fill に入れる（請求書に足す）
    next_month / prepay      … 出金そのものが仕入の確定額。税抜で bank_purchase に入れ、
                               月次サマリーではこれを正にする（無い月は入荷履歴のまま）
    """
    r = reconcile(db)
    out: Dict[tuple, dict] = defaultdict(lambda: {"paid": 0.0, "no_invoice": 0.0,
                                                  "no_invoice_count": 0, "fill": 0.0,
                                                  "bank_purchase": 0.0, "paid_on": []})
    allp = r["matched"] + r["unmatched"]
    # 月末締め翌月払いの取引先は、まとめ払いを入荷の割合で月に分ける
    by_sup: Dict[str, list] = defaultdict(list)
    for p in allp:
        if PAY_TERMS.get(p["supplier"]) == "next_month":
            by_sup[p["supplier"]].append(p)
    for sup, ps in by_sup.items():
        try:
            arr = arrivals_by_month(db, sup)
        except Exception:
            arr = {}
        for ym, amt, p in _split_next_month(ps, arr):
            k = (ym, sup)
            out[k]["paid"] += amt
            out[k]["paid_on"].append(p["paid_on"])
            out[k]["bank_purchase"] += amt / TAX
    for p in allp:
        if PAY_TERMS.get(p["supplier"]) == "next_month":
            continue
        k = (purchase_ym(p["supplier"], p["ym"]), p["supplier"])
        out[k]["paid"] += p["amount"]
        out[k]["paid_on"].append(p["paid_on"])
        if PAY_TERMS.get(p["supplier"]) == "prepay":
            out[k]["bank_purchase"] += p["amount"] / TAX
    for p in r["unmatched"]:
        if PAY_TERMS.get(p["supplier"]) in ("next_month", "prepay"):
            continue
        o = out[(p["ym"], p["supplier"])]
        o["no_invoice"] += p["amount"]
        o["no_invoice_count"] += 1
        if p["supplier"] in FILL_SUPPLIERS:
            o["fill"] += p["amount"] / TAX
    return out
