from typing import Optional
from sqlalchemy.orm import Session
from app.models.product import Product
from app.models.settings import OrderSettings
from app.models.price_log import PriceAdjustmentLog


def calc_min_price(product: Product, settings: OrderSettings) -> Optional[float]:
    """利益率下限を下回らない最低販売価格を計算"""
    if not product.price or not product.fba_fee:
        return None
    exchange_rate = settings.exchange_rate or 21.0
    min_profit_rate = settings.min_profit_rate or 0.10
    amazon_fee_rate = product.amazon_fee_rate or 0.10
    cost_jpy = product.price * exchange_rate
    # selling_price = (cost_jpy + fba_fee) / (1 - amazon_fee_rate - min_profit_rate)
    denom = 1 - amazon_fee_rate - min_profit_rate
    if denom <= 0:
        return None
    return (cost_jpy + product.fba_fee) / denom


def _round_to_10(price: float) -> float:
    """10円単位に丸める"""
    return round(price / 10) * 10


def suggest_adjustments(db: Session) -> int:
    """
    全商品を評価して価格調整提案をDBに保存する。
    戻り値: 生成した提案件数
    """
    from app.services.amazon_api import fetch_sales_period

    settings = db.query(OrderSettings).first()
    if not settings or not settings.price_adjust_enabled:
        return 0

    drop_threshold = settings.price_drop_threshold or 0.20
    change_pct = settings.price_change_pct or 0.03

    products = (
        db.query(Product)
        .filter(Product.is_active == True, Product.price_auto_adjust == True)
        .all()
    )

    asin_list = [p.asin for p in products if p.asin]
    # 今期14日 / 前期14日（14〜28日前）
    sales_now = fetch_sales_period(days=14, offset_days=0, asin_list=asin_list)
    sales_prev = fetch_sales_period(days=14, offset_days=14, asin_list=asin_list)

    count = 0
    for p in products:
        if not p.selling_price:
            continue

        # 既にpendingの提案があればスキップ
        existing = (
            db.query(PriceAdjustmentLog)
            .filter(
                PriceAdjustmentLog.product_id == p.id,
                PriceAdjustmentLog.status == "pending",
            )
            .first()
        )
        if existing:
            continue

        daily_now = sales_now.get(p.asin, 0)
        daily_prev = sales_prev.get(p.asin, 0)
        min_price = calc_min_price(p, settings)
        change_amt = _round_to_10(p.selling_price * change_pct)
        if change_amt < 10:
            change_amt = 10

        reason = None
        new_price = None

        # 前回値上げからの巻き戻し判定
        last_up = (
            db.query(PriceAdjustmentLog)
            .filter(
                PriceAdjustmentLog.product_id == p.id,
                PriceAdjustmentLog.reason == "up",
                PriceAdjustmentLog.status == "applied",
            )
            .order_by(PriceAdjustmentLog.applied_at.desc())
            .first()
        )
        if last_up and last_up.daily_before is not None:
            # 値上げ前の日販より drop_threshold% 以上落ちていたら巻き戻し
            if daily_now < last_up.daily_before * (1 - drop_threshold):
                reason = "revert"
                new_price = _round_to_10(last_up.old_price)

        if reason is None:
            if daily_prev > 0 and daily_now < daily_prev * (1 - drop_threshold):
                # 値下げ提案
                candidate = _round_to_10(p.selling_price - change_amt)
                if min_price and candidate < min_price:
                    candidate = _round_to_10(min_price)
                if candidate < p.selling_price:
                    reason = "down"
                    new_price = candidate
            elif daily_now >= daily_prev and daily_now > 0:
                # 値上げ提案
                candidate = _round_to_10(p.selling_price + change_amt)
                if p.price_max and candidate > p.price_max:
                    candidate = p.price_max
                if candidate > p.selling_price:
                    reason = "up"
                    new_price = candidate

        if reason and new_price and new_price != p.selling_price:
            log = PriceAdjustmentLog(
                product_id=p.id,
                sku=p.sku,
                old_price=p.selling_price,
                new_price=new_price,
                reason=reason,
                daily_before=daily_prev,
                daily_after=daily_now,
                status="pending",
            )
            db.add(log)
            count += 1

    db.commit()
    return count
