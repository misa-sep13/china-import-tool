from datetime import date
from typing import Optional
from dataclasses import dataclass

@dataclass
class CalcSettings:
    # リードタイム（日）
    lead_days: int = 93          # 発注〜FBA着+余裕 合計
    # 加重平均の重み
    weight_d7: float = 0.05
    weight_d15: float = 0.15
    weight_d30: float = 0.25
    weight_d60: float = 0.25
    weight_d90: float = 0.30
    # 成長・下落補正
    growth_ratio_threshold: float = 1.3
    growth_multiplier: float = 1.0   # 上限（伸びすぎ抑制）
    decline_ratio_threshold: float = 0.7
    decline_multiplier: float = 0.5  # 下限（落ち過ぎ抑制）
    min_order_qty: int = 10
    sale_enabled: bool = False
    sale_start: Optional[date] = None
    sale_end: Optional[date] = None
    sale_extra_days: int = 0         # セール期間の上乗せ日数
    # 後方互換（旧設定から移行）
    threshold_days: int = 75
    target_days_normal: int = 75
    target_days_sale: int = 90

@dataclass
class CalcResult:
    qty: int               # 発注数（セット単位）
    qty_pieces: int        # 発注数（ピース単位）
    days_left: int
    daily: float           # 加重日販
    stock: int             # 総在庫
    growth: float          # 成長率補正
    target: int            # 目標在庫数（個）
    available: int
    inbound: int
    is_sale: bool

def is_in_sale(s: CalcSettings) -> bool:
    if not s.sale_enabled or not s.sale_start or not s.sale_end:
        return False
    today = date.today()
    return s.sale_start <= today <= s.sale_end

def weighted_daily(sales_7, sales_15, sales_30, sales_60, sales_90, s: CalcSettings) -> float:
    """5期間の加重平均日販を返す。各値は「その期間の日販」"""
    return (
        sales_7  * s.weight_d7  +
        sales_15 * s.weight_d15 +
        sales_30 * s.weight_d30 +
        sales_60 * s.weight_d60 +
        sales_90 * s.weight_d90
    )

def growth_mult(sales_7, sales_15, sales_90, s: CalcSettings) -> float:
    """直近(7日・15日平均) vs 90日 の比率で補正係数を返す（0.5〜1.0）"""
    if sales_90 <= 0:
        return 1.0
    recent = (sales_7 + sales_15) / 2
    ratio = recent / sales_90
    if ratio >= s.growth_ratio_threshold:
        return min(s.growth_multiplier, 1.0)
    if ratio <= s.decline_ratio_threshold:
        return max(s.decline_multiplier, 0.5)
    return 1.0

def calc_order_qty(
    available: int, inbound: int, processing: int, extra_stock: int,
    sales_7: float, sales_15: float, sales_30: float, sales_60: float,
    set_size: int, s: CalcSettings,
    sales_90: float = 0.0,
) -> CalcResult:
    set_size = max(1, set_size)
    # 総在庫 = FBA + 輸送中 + ラクマート等 + 梱包中
    stock = available + inbound + processing + extra_stock

    daily = weighted_daily(sales_7, sales_15, sales_30, sales_60, sales_90, s)
    days_left = int(stock / daily) if daily > 0 else 9999
    growth = growth_mult(sales_7, sales_15, sales_90, s)

    # セール期間は上乗せ日数を加算
    sale = is_in_sale(s)
    lead = s.lead_days + (s.sale_extra_days if sale else 0)

    # 目標在庫数 = 日販 × 補正 × リードタイム合計日数
    target_stock = round(daily * growth * lead)

    # 不足分だけ発注（マイナスなら0）
    qty_pieces = 0
    qty = 0
    need = max(0, target_stock - stock)
    if need > 0:
        qty_sets = -(-need // set_size)   # ceil除算
        qty_pieces = qty_sets * set_size
        if qty_pieces >= s.min_order_qty:
            qty = qty_sets
        else:
            qty_pieces = 0

    return CalcResult(
        qty=qty, qty_pieces=qty_pieces,
        days_left=days_left, daily=round(daily, 2),
        stock=stock, growth=growth, target=target_stock,
        available=available, inbound=inbound, is_sale=sale
    )
