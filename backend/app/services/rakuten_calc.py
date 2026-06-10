from dataclasses import dataclass

@dataclass
class RakutenCalcSettings:
    lead_days:          int   = 20    # 発注〜入荷日数
    target_days:        int   = 30    # 予測販売数の期間（日）
    safety_stock_rate:  float = 0.15  # 安全在庫率
    threshold_days:     int   = 30    # 発注タイミング閾値（日）

@dataclass
class RakutenCalcResult:
    order_qty:     int    # 提案発注数
    predicted_30:  float  # 予測販売数（30日）
    lead_sales:    float  # 発注〜入荷まで売れる数
    safety_stock:  float  # 安全在庫数
    growth_rate:   float  # 成長率（%）
    daily_avg:     float  # 日販（直近30日平均）
    total_stock:   int    # 全在庫（手持ち+輸送中+発注済み）
    days_left:     float  # 在庫日数（実在庫ベース）
    needs_order:   bool   # 発注タイミング到来フラグ

def calc_rakuten_order(
    stock:           int,   # 実在庫（手持ちのみ）
    inbound:         int,   # 輸送中
    ordered:         int,   # 発注済み（未納品）
    sales_30_recent: float, # 直近30日販売数
    sales_30_prev:   float, # 60日前〜31日前の30日販売数
    super_sale_qty:  int = 0, # スーパーセール追加分（modeB時）
    s: RakutenCalcSettings = None,
) -> RakutenCalcResult:
    if s is None:
        s = RakutenCalcSettings()

    # --- 成長率 ---
    # 成長率 = (直近30日 / 前30日 - 1)
    if (sales_30_prev or 0) > 0:
        growth_rate = (sales_30_recent / sales_30_prev) - 1.0
    else:
        growth_rate = 0.0
    # 成長率を -50% 〜 +200% にクランプ（極端な値を抑制）
    growth_rate = max(-0.5, min(growth_rate, 2.0))

    # --- 予測販売数（30日） ---
    predicted_30 = (sales_30_recent or 0) * (1.0 + growth_rate)

    # --- 日販 ---
    daily_avg = predicted_30 / 30.0 if predicted_30 > 0 else 0.0

    # --- 発注〜入荷まで売れる数（20日分） ---
    lead_sales = daily_avg * s.lead_days

    # --- 安全在庫 ---
    safety_stock = (predicted_30 + lead_sales) * s.safety_stock_rate

    # --- 全在庫（提案発注数の計算に使う） ---
    total_stock = (stock or 0) + (inbound or 0) + (ordered or 0)

    # --- 提案発注数 ---
    raw = predicted_30 + lead_sales + safety_stock + (super_sale_qty or 0) - total_stock
    order_qty = max(0, round(raw))

    # --- 発注タイミング判定（全在庫が閾値以下） ---
    threshold = daily_avg * s.threshold_days
    needs_order = total_stock <= threshold

    # --- 在庫日数（実在庫ベース） ---
    days_left = (stock or 0) / daily_avg if daily_avg > 0 else 9999.0

    return RakutenCalcResult(
        order_qty=order_qty,
        predicted_30=round(predicted_30, 1),
        lead_sales=round(lead_sales, 1),
        safety_stock=round(safety_stock, 1),
        growth_rate=round(growth_rate * 100, 1),
        daily_avg=round(daily_avg, 2),
        total_stock=total_stock,
        days_left=round(days_left, 1),
        needs_order=needs_order,
    )
