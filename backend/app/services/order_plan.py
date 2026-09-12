"""日別実績を読んで、発注数まで出す。

order_logic.py は計算式だけを持つ純粋な部分で、DBを知らない。
ここがDBから日別実績・セール期間・在庫を集めて、式に渡す。
分けてあるのは、式そのものをデータ無しで検算できるようにするため。
"""
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.daily_sales import DailySales, SaleWindow
from app.models.product import Product
from app.services import order_logic
from app.services.order_logic import DayRow, LogicSettings, OrderResult

log = logging.getLogger("order_plan")


def active_sale(db: Session, day: Optional[date] = None) -> Optional[SaleWindow]:
    """その日が入っているセール期間。無ければ None。"""
    d = day or date.today()
    return (db.query(SaleWindow)
            .filter(SaleWindow.start_date <= d, SaleWindow.end_date >= d)
            .order_by(SaleWindow.start_date.desc()).first())


def sale_mult_for(w: SaleWindow, is_target: bool, day: date) -> float:
    """その日に使う倍率。優先順は 手動 > 実測 > 見込み。

    実測に切り替えるのはセール3日目から。初日・2日目は母数が小さく、
    その日の偏りがそのまま倍率になってしまう。
    """
    manual = w.manual_target if is_target else w.manual_other
    if manual:
        return float(manual)
    elapsed = (day - w.start_date).days + 1
    if elapsed >= 3:
        actual = w.actual_target if is_target else w.actual_other
        if actual:
            return float(actual)
    planned = w.planned_target if is_target else w.planned_other
    return float(planned or 1.0)


def _is_sale_target(row: DailySales, plain_price: float) -> bool:
    """その日、セール価格になっていたか。

    実効単価（(売上−プロモ値引き)÷数量）が平常の95%以下に下がったかで
    見分ける。セール対象に指定したかどうかではなく、実際に値が
    下がったかで判定するので、設定漏れがあっても拾える。
    """
    units = row.units or 0
    if units <= 0 or plain_price <= 0:
        return False
    eff = ((row.revenue or 0) - (row.promo_discount or 0)) / units
    return eff <= plain_price * 0.95


def _plain_price(rows: List[DailySales], sale_days: set) -> float:
    """平常日の実効単価。セール対象かどうかを見分ける物差し。"""
    vals = []
    for r in rows:
        if r.day in sale_days or (r.units or 0) <= 0:
            continue
        vals.append(((r.revenue or 0) - (r.promo_discount or 0)) / r.units)
    return (sum(vals) / len(vals)) if vals else 0.0


def load_days(db: Session, sku: str, s: LogicSettings,
              today: Optional[date] = None) -> List[DayRow]:
    """1商品ぶんの日別実績を、計算に渡せる形にする。

    セール期間に入っている日は、その日に使う倍率を添える。
    対象か対象外かは、実効単価が下がったかで日ごとに判定する。
    """
    today = today or date.today()
    start = today - timedelta(days=s.window_days)
    rows = (db.query(DailySales)
            .filter(DailySales.sku == sku,
                    DailySales.day >= start, DailySales.day < today)
            .order_by(DailySales.day).all())
    if not rows:
        return []

    windows = (db.query(SaleWindow)
               .filter(SaleWindow.end_date >= start,
                       SaleWindow.start_date < today).all())
    sale_days = {r.day for r in rows
                 for w in windows if w.start_date <= r.day <= w.end_date}
    base_price = _plain_price(rows, sale_days)

    out = []
    for r in rows:
        w = next((x for x in windows if x.start_date <= r.day <= x.end_date), None)
        mult = 1.0
        if w:
            mult = sale_mult_for(w, _is_sale_target(r, base_price), r.day)
        out.append(DayRow(
            day=r.day, units=r.units or 0, vine_units=r.vine_units or 0,
            in_stock=bool(r.in_stock), is_sale=bool(w), sale_mult=mult,
        ))
    return out


def first_sale_day(db: Session, sku: str) -> Optional[date]:
    """初めて売れた日。新商品は窓をここまでに縮める。

    新商品用の別の式は持たない。窓を縮めるだけで同じ式を使う。
    """
    r = (db.query(DailySales.day)
         .filter(DailySales.sku == sku, DailySales.units > 0)
         .order_by(DailySales.day).first())
    return r[0] if r else None


def sale_extra(db: Session, s: LogicSettings,
               today: Optional[date] = None) -> float:
    """セールで上乗せする日数。残りセール日数 ×（倍率−1）。"""
    today = today or date.today()
    w = active_sale(db, today)
    if not w:
        # 開始前でも、近ければ先に積んでおく
        w = (db.query(SaleWindow)
             .filter(SaleWindow.start_date > today)
             .order_by(SaleWindow.start_date).first())
        if not w or (w.start_date - today).days > 14:
            return 0.0
        days = (w.end_date - w.start_date).days + 1
    else:
        # 当日ぶんはもう売れているので数えない
        days = (w.end_date - today).days
    mult = sale_mult_for(w, True, today)
    return order_logic.sale_extra_days(days, mult)


def recompute_sale_mult(db: Session, w: SaleWindow) -> dict:
    """セールの実測倍率を出して保存する。

        M = Σセール日の実売（Vine控除） ÷ Σ各商品の平常日販

    商品ごとの倍率は持たない。割り算がその商品の個性を消してしまい、
    「よく伸びた商品ほど平常に見える」というおかしなことになる。
    対象／対象外の2グループだけ持つ。

    分母が小さすぎるときは実測を入れない。黙って膨らませないため、
    その場合は見込み値のまま運用する（fail-safe）。
    """
    today = date.today()
    end = min(w.end_date, today - timedelta(days=1))
    if end < w.start_date:
        return {"skipped": True, "reason": "まだ集計できる日がありません"}

    # 窓の外（セール前）を平常として使う
    plain_start = w.start_date - timedelta(days=order_logic.WINDOW_DAYS)
    rows = (db.query(DailySales)
            .filter(DailySales.day >= plain_start, DailySales.day <= end).all())

    by_sku: Dict[str, List[DailySales]] = {}
    for r in rows:
        by_sku.setdefault(r.sku, []).append(r)

    sums = {True: [0.0, 0.0], False: [0.0, 0.0]}   # [セール実売, 平常日販合計]
    for sku, rs in by_sku.items():
        plain = [r for r in rs if r.day < w.start_date and r.in_stock]
        if not plain:
            continue
        d0 = sum(max(0, (r.units or 0) - (r.vine_units or 0))
                 for r in plain) / len(plain)
        if d0 <= 0:
            continue
        base_price = _plain_price(plain, set())

        sale_rows = [r for r in rs
                     if w.start_date <= r.day <= end and r.in_stock]
        if not sale_rows:
            continue
        # 対象／対象外は、セール中に値が下がったかで決める
        is_target = any(_is_sale_target(r, base_price) for r in sale_rows)
        units = sum(max(0, (r.units or 0) - (r.vine_units or 0))
                    for r in sale_rows)
        sums[is_target][0] += units
        sums[is_target][1] += d0 * len(sale_rows)

    out = {}
    for is_target, (units, denom) in sums.items():
        m = order_logic.measured_sale_mult(units, denom)
        key = "target" if is_target else "other"
        out[key] = {"multiplier": m, "units": round(units, 1),
                    "denominator": round(denom, 1)}
        if m is None:
            continue
        if is_target:
            w.actual_target = m
        else:
            w.actual_other = m
    db.commit()
    return out


@dataclass
class PlanRow:
    sku: str
    name: str
    result: OrderResult


def plan_for(db: Session, product: Product, stock: int,
             s: Optional[LogicSettings] = None,
             today: Optional[date] = None) -> OrderResult:
    """1商品ぶんの発注数。"""
    s = s or LogicSettings()
    rows = load_days(db, product.sku, s, today)
    return order_logic.calc_order(
        rows, stock=stock, set_size=(product.set_size or 1), s=s,
        first_sale_day=first_sale_day(db, product.sku),
        sale_extra=sale_extra(db, s, today),
    )
