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
    for p in r["matched"] + r["unmatched"]:
        k = (purchase_ym(p["supplier"], p["ym"]), p["supplier"])
        out[k]["paid"] += p["amount"]
        out[k]["paid_on"].append(p["paid_on"])
        if PAY_TERMS.get(p["supplier"]) in ("next_month", "prepay"):
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
