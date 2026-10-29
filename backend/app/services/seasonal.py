"""季節商品を、去年の実績から見つける。

冬物・夏物は「売れ始めてから発注」では間に合わない。中国から届くまで
2か月前後かかるので、売れ始める2か月前には発注していないといけない。

やっていることは単純で、
  ・いま発注したぶんが届くのは「◯月ごろ」
  ・去年のその時期、この商品は平月の何倍売れていたか
を出すだけ。倍率が高いものが季節商品の候補になる。

在庫切れの日は数えない。売れなかったのではなく、売るものが無かった
だけなので、混ぜると季節性が薄まって見える。

注意：去年の同じ時期のデータが無いと何も言えない。日別実績は
2026年7月からしか溜まっていないので、それ以前を見るには受注を
遡って埋める必要がある（GitHub Actions の Daily Rakuten Sales Sync に
days を渡すと埋まる）。足りないときは黙って候補を出さず、
足りないことを返す。
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

# 判定の線引き。実績から決め直せるよう、ここにまとめておく
PEAK_RATIO = 1.5        # 平月の何倍売れていたら季節商品とみなすか
MIN_UNITS = 10          # 去年その時期にこれ未満しか売れていないものは見ない
MIN_BASE_DAYS = 120     # 平月を出すのに、最低これだけの日数が要る
WINDOW_DAYS = 30        # 「届いてから何日ぶんを見るか」


@dataclass
class DayRow:
    sku: str
    day: date
    qty: int
    stockout: bool


def _in_stock_days(rows: list[DayRow], start: date, end: date) -> int:
    """その期間のうち、売れる状態だった日数。

    実績は売れた日（と在庫切れの日）しか行が無いので、暦の日数から
    在庫切れの日を引いて出す。
    """
    total = (end - start).days + 1
    out = sum(1 for r in rows if start <= r.day <= end and r.stockout)
    return max(0, total - out)


def _units(rows: list[DayRow], start: date, end: date) -> int:
    return sum(r.qty for r in rows
               if start <= r.day <= end and not r.stockout)


@dataclass
class Candidate:
    sku: str
    name: str
    ratio: float          # 去年その時期 ÷ 平月
    units_last_year: int  # 去年その時期に売れた数
    daily_last_year: float
    daily_base: float     # 平月の日販
    extra_units: int      # 平月どおりなら売れなかったぶん（＝上積みが要る数）
    arrival_from: date    # いま発注すると届くころ
    arrival_to: date


def find_candidates(rows_by_sku: dict[str, list[DayRow]],
                    names: dict[str, str],
                    today: date, lead_days: int) -> dict:
    """いま仕入れるべき季節商品の候補。

    rows_by_sku は SKU ごとの日別実績（在庫切れの印つき）。
    """
    # いま発注すると届くころ。そこから1か月を「これから売る期間」とみなす
    arrival_from = today + timedelta(days=max(0, lead_days))
    arrival_to = arrival_from + timedelta(days=WINDOW_DAYS - 1)
    # 去年の同じ時期
    ly_from = arrival_from - timedelta(days=365)
    ly_to = arrival_to - timedelta(days=365)
    # 平月を出すための1年間（去年の同じ時期を含む1年）
    base_from = ly_to - timedelta(days=364)
    base_to = ly_to

    have_from = min((r.day for rs in rows_by_sku.values() for r in rs),
                    default=None)
    enough = have_from is not None and have_from <= ly_from
    if not enough:
        return {
            "enough_data": False,
            "need_from": ly_from.isoformat(),
            "have_from": have_from.isoformat() if have_from else None,
            "arrival_from": arrival_from.isoformat(),
            "arrival_to": arrival_to.isoformat(),
            "candidates": [],
        }

    out: list[Candidate] = []
    for sku, rows in rows_by_sku.items():
        base_days = _in_stock_days(rows, base_from, base_to)
        if base_days < MIN_BASE_DAYS:
            continue
        ly_days = _in_stock_days(rows, ly_from, ly_to)
        if ly_days <= 0:
            continue
        ly_units = _units(rows, ly_from, ly_to)
        if ly_units < MIN_UNITS:
            continue
        base_units = _units(rows, base_from, base_to)
        daily_base = base_units / base_days
        if daily_base <= 0:
            continue
        daily_ly = ly_units / ly_days
        ratio = daily_ly / daily_base
        if ratio < PEAK_RATIO:
            continue
        out.append(Candidate(
            sku=sku, name=names.get(sku, ""),
            ratio=round(ratio, 2),
            units_last_year=ly_units,
            daily_last_year=round(daily_ly, 2),
            daily_base=round(daily_base, 2),
            extra_units=round((daily_ly - daily_base) * WINDOW_DAYS),
            arrival_from=arrival_from, arrival_to=arrival_to,
        ))
    # 倍率ではなく「余分に要る個数」で並べる。10個が12倍になっても
    # 打つ手は無いが、1900個の商品が8倍なら仕入れを変える必要がある
    out.sort(key=lambda c: -c.extra_units)
    return {
        "enough_data": True,
        "arrival_from": arrival_from.isoformat(),
        "arrival_to": arrival_to.isoformat(),
        "last_year_from": ly_from.isoformat(),
        "last_year_to": ly_to.isoformat(),
        "candidates": [{
            "sku": c.sku, "name": c.name, "ratio": c.ratio,
            "units_last_year": c.units_last_year,
            "daily_last_year": c.daily_last_year,
            "daily_base": c.daily_base,
            "extra_units": c.extra_units,
        } for c in out],
    }


def rakuten_rows(db) -> tuple[dict[str, list[DayRow]], dict[str, str]]:
    from app.models.rakuten_daily_sales import RakutenDailySales
    from app.models.rakuten_product import RakutenProduct
    rows = defaultdict(list)
    for sku, day, qty, so in db.query(
            RakutenDailySales.sku, RakutenDailySales.sale_date,
            RakutenDailySales.qty, RakutenDailySales.is_stockout).all():
        if sku and day:
            rows[sku].append(DayRow(sku, day, int(qty or 0), bool(so)))
    names = {p.sku: (p.name or "") for p in db.query(RakutenProduct).all()
             if p.sku}
    return rows, names


def amazon_rows(db) -> tuple[dict[str, list[DayRow]], dict[str, str]]:
    from app.models.daily_sales import DailySales
    from app.models.product import Product
    rows = defaultdict(list)
    for sku, day, units, vine, in_stock in db.query(
            DailySales.sku, DailySales.day, DailySales.units,
            DailySales.vine_units, DailySales.in_stock).all():
        if not sku or not day:
            continue
        # Vineはレビュー用の無料配布で、季節の需要ではない
        qty = max(0, int(units or 0) - int(vine or 0))
        rows[sku].append(DayRow(sku, day, qty, not bool(in_stock)))
    names = {p.sku: (p.name or "") for p in db.query(Product).all() if p.sku}
    return rows, names
