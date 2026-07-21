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
    daily_avg:     float  # 加重日販（発注計算に使用）
    daily_avg_7:   float  # 7日日販
    daily_avg_30:  float  # 30日日販
    total_stock:   int    # 全在庫（手持ち+輸送中+発注済み）
    days_left:     float  # 在庫日数（7日日販ベース）
    needs_order:   bool   # 発注タイミング到来フラグ

def calc_rakuten_order(
    stock:            int,   # 実在庫（手持ちのみ）
    inbound:          int,   # 輸送中
    ordered:          int,   # 発注済み（未納品）
    sales_30_recent:  float, # 直近30日販売数（成長率計算用）
    sales_30_prev:    float, # 60日前〜31日前の販売数（成長率計算用）
    super_sale_qty:   int = 0,  # スーパーセール追加分（modeB時）
    sales_90:         float = 0, # 直近63日販売数（フォールバック用）
    stockout_days_90: int = 0,   # 過去63日の在庫切れ日数
    daily_avg_7:      float = 0, # 7日日販（rakuten_daily_salesから算出）
    daily_avg_30:     float = 0, # 30日日販（rakuten_daily_salesから算出）
    s: RakutenCalcSettings = None,
) -> RakutenCalcResult:
    if s is None:
        s = RakutenCalcSettings()

    # --- 日販（7日・30日の加重平均: 0.4 × 7日 + 0.6 × 30日）---
    if (daily_avg_7 or 0) > 0 or (daily_avg_30 or 0) > 0:
        da7 = daily_avg_7 or 0
        da30 = daily_avg_30 or 0
        if da7 > 0 and da30 > 0:
            daily_avg = da7 * 0.4 + da30 * 0.6
        elif da7 > 0:
            daily_avg = da7
        else:
            daily_avg = da30
    elif (sales_90 or 0) > 0:
        effective_days = max(1, 63 - (stockout_days_90 or 0))
        daily_avg = (sales_90 or 0) / effective_days
        daily_avg_7 = daily_avg
        daily_avg_30 = daily_avg
    elif (sales_30_recent or 0) > 0:
        daily_avg = (sales_30_recent or 0) / 30.0
        daily_avg_7 = daily_avg
        daily_avg_30 = daily_avg
    else:
        daily_avg = 0.0

    # --- 成長率（直近30日 vs 前30日）---
    if (sales_30_prev or 0) > 0 and (sales_30_recent or 0) > 0:
        growth_rate = (sales_30_recent / sales_30_prev) - 1.0
        growth_rate = max(-0.5, min(growth_rate, 2.0))
    else:
        growth_rate = 0.0

    # --- 予測販売数（目標日数分）---
    predicted_30 = daily_avg * s.target_days * (1.0 + growth_rate)

    # --- 発注〜入荷まで売れる数 ---
    lead_sales = daily_avg * s.lead_days

    # --- 安全在庫 ---
    safety_stock = (predicted_30 + lead_sales) * s.safety_stock_rate

    # --- 全在庫 ---
    total_stock = (stock or 0) + (inbound or 0) + (ordered or 0)

    # --- 提案発注数 ---
    raw = predicted_30 + lead_sales + safety_stock + (super_sale_qty or 0) - total_stock
    order_qty = max(0, round(raw))

    # --- 発注タイミング判定 ---
    threshold = daily_avg * s.threshold_days
    needs_order = (total_stock <= threshold) and daily_avg > 0

    # --- 在庫日数（7日日販ベース＝直近のペースで何日持つか）---
    da_for_days = daily_avg_7 if (daily_avg_7 or 0) > 0 else daily_avg
    days_left = total_stock / da_for_days if da_for_days > 0 else 9999.0

    return RakutenCalcResult(
        order_qty=order_qty,
        predicted_30=round(predicted_30, 1),
        lead_sales=round(lead_sales, 1),
        safety_stock=round(safety_stock, 1),
        growth_rate=round(growth_rate * 100, 1),
        daily_avg=round(daily_avg, 2),
        daily_avg_7=round(daily_avg_7 or 0, 2),
        daily_avg_30=round(daily_avg_30 or 0, 2),
        total_stock=total_stock,
        days_left=round(days_left, 1),
        needs_order=needs_order,
    )
