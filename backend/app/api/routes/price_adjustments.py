from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.core.database import get_db
from app.models.price_log import PriceAdjustmentLog
from app.models.product import Product

router = APIRouter(prefix="/price-adjustments", tags=["price-adjustments"])


@router.get("/")
def list_adjustments(status: str = "pending", db: Session = Depends(get_db)):
    """価格調整提案一覧（statusでフィルタ: pending/applied/rejected）"""
    logs = (
        db.query(PriceAdjustmentLog)
        .filter(PriceAdjustmentLog.status == status)
        .order_by(PriceAdjustmentLog.suggested_at.desc())
        .all()
    )
    result = []
    for log in logs:
        product = db.query(Product).filter(Product.id == log.product_id).first()
        # 変更後の利益率を計算
        profit_rate_after = None
        if product and product.price and product.fba_fee:
            from app.models.settings import OrderSettings
            settings = db.query(OrderSettings).first()
            exchange_rate = settings.exchange_rate if settings else 21.0
            cost_jpy = product.price * exchange_rate
            amazon_fee = log.new_price * (product.amazon_fee_rate or 0.1)
            profit = log.new_price - cost_jpy - amazon_fee - product.fba_fee
            profit_rate_after = round(profit / log.new_price * 100, 1) if log.new_price > 0 else None

        result.append({
            "id": log.id,
            "product_id": log.product_id,
            "sku": log.sku,
            "name": product.name if product else "",
            "old_price": log.old_price,
            "new_price": log.new_price,
            "change_amt": log.new_price - log.old_price,
            "reason": log.reason,
            "daily_before": log.daily_before,
            "daily_after": log.daily_after,
            "profit_rate_after": profit_rate_after,
            "status": log.status,
            "suggested_at": log.suggested_at.isoformat() if log.suggested_at else None,
            "applied_at": log.applied_at.isoformat() if log.applied_at else None,
        })
    return result


@router.post("/{log_id}/approve")
def approve_adjustment(log_id: int, db: Session = Depends(get_db)):
    """承認: SP-APIで価格変更してDBを更新"""
    log = db.query(PriceAdjustmentLog).filter(PriceAdjustmentLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="提案が見つかりません")
    if log.status != "pending":
        raise HTTPException(status_code=400, detail=f"ステータスが pending ではありません: {log.status}")

    from app.services.amazon_api import update_listing_price
    success = update_listing_price(log.sku, log.new_price)
    if not success:
        raise HTTPException(status_code=500, detail="SP-APIへの価格反映に失敗しました")

    # DBの selling_price も更新
    product = db.query(Product).filter(Product.id == log.product_id).first()
    if product:
        product.selling_price = log.new_price

    log.status = "applied"
    log.applied_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.post("/{log_id}/reject")
def reject_adjustment(log_id: int, db: Session = Depends(get_db)):
    """却下"""
    log = db.query(PriceAdjustmentLog).filter(PriceAdjustmentLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="提案が見つかりません")
    if log.status != "pending":
        raise HTTPException(status_code=400, detail=f"ステータスが pending ではありません: {log.status}")
    log.status = "rejected"
    db.commit()
    return {"ok": True}


@router.post("/suggest")
def trigger_suggest(db: Session = Depends(get_db)):
    """手動で価格調整提案を生成"""
    from app.core.config import settings as app_settings
    if not app_settings.SP_API_REFRESH_TOKEN:
        raise HTTPException(status_code=400, detail="SP-API未設定")
    from app.services.price_adjuster import suggest_adjustments
    count = suggest_adjustments(db)
    return {"suggested": count}
