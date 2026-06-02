from datetime import date
from typing import Optional
from dataclasses import dataclass

@dataclass
class CalcSettings:
    threshold_days: int = 75
    target_days_normal: int = 75
    target_days_sale: int = 90
    weight_d7: float = 0.05
    weight_d15: float = 0.10
    weight_d30: float = 0.30
    weight_d60: float = 0.55
    growth_ratio_threshold: float = 1.3
    growth_multiplier: float = 1.0
    decline_ratio_threshold: float = 0.7
    decline_multiplier: float = 0.8
    min_order_qty: int = 10
    sale_enabled: bool = False
    sale_start: Optional[date] = None
    sale_end: Optional[date] = None

@dataclass
class CalcResult:
    qty: int               # 発注数（セット単位）
    qty_pieces: int        # 発注数（ピース単位）
    days_left: int
    daily: float           # 加重日販
    stock: int             # 総在庫
    growth: float          # 成長率補正
    target: int            # 目標在庫日数
    available: int
    inbound: int
    is_sale: bool

def is_in_sale(s: CalcSettings) -> bool:
    if not s.sale_enabled or not s.sale_start or not s.sale_end:
        return False
    today = date.today()
    return s.sale_start <= today <= s.sale_end

def target_days(s: CalcSettings) -> int:
    return s.target_days_sale if is_in_sale(s) else s.target_days_normal

def weighted_daily(sales_7, sales_15, sales_30, sales_60, s: CalcSettings) -> float:
    return (
        sales_7  * s.weight_d7  +
        sales_15 * s.weight_d15 +
        sales_30 * s.weight_d30 +
        sales_60 * s.weight_d60
    )

def growth_mult(sales_7, sales_60, s: CalcSettings) -> float:
    if sales_60 <= 0:
        return 1.0
    ratio = sales_7 / sales_60
    if ratio >= s.growth_ratio_threshold:
        return s.growth_multiplier
    if ratio <= s.decline_ratio_threshold:
        return s.decline_multiplier
    return 1.0

def calc_order_qty(
    available: int, inbound: int, processing: int, extra_stock: int,
    sales_7: float, sales_15: float, sales_30: float, sales_60: float,
    set_size: int, s: CalcSettings
) -> CalcResult:
    set_size = max(1, set_size)
    stock = available + inbound + processing + extra_stock
    daily = weighted_daily(sales_7, sales_15, sales_30, sales_60, s)
    days_left = int(stock / daily) if daily > 0 else 9999
    growth = growth_mult(sales_7, sales_60, s)
    tgt = target_days(s)
    sale = is_in_sale(s)

    qty = 0
    qty_pieces = 0
    if days_left < s.threshold_days:
        need = max(0, round(tgt * daily * growth - stock))
        if need > 0:
            qty_sets = -(-need // set_size)  # ceil
            qty_pieces = qty_sets * set_size
            if qty_pieces >= s.min_order_qty:
                qty = qty_sets
            else:
                qty_pieces = 0

    return CalcResult(
        qty=qty, qty_pieces=qty_pieces,
        days_left=days_left, daily=round(daily, 2),
        stock=stock, growth=growth, target=tgt,
        available=available, inbound=inbound, is_sale=sale
    )
