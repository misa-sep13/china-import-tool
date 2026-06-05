from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import io
from app.core.database import get_db
from app.models.product import Product
from app.models.settings import OrderSettings
from app.models.order_history import OrderHistory
from app.services.calc import CalcSettings, calc_order_qty
from app.services.excel_export import build_taotaro_excel

router = APIRouter(prefix="/orders", tags=["orders"])

class OrderItem(BaseModel):
    product_id: int
    sku: str
    name: str
    asin: str
    fnsku: str
    buy_url: str
    photo_url: str
    color: str
    size: str
    price: float
    repack: str
    note: str
    amazon_url: str
    set_size: int
    available: int
    inbound: int
    sales_7: float
    sales_15: float
    sales_30: float
    sales_60: float
    days_left: int
    daily: float
    stock: int
    recommended_qty: int
    qty: int  # 最終発注数（ユーザーが調整可能）

class ExportRequest(BaseModel):
    items: List[OrderItem]

@router.get("/preview")
def preview_orders(db: Session = Depends(get_db)):
    """SP-APIからデータ取得して推奨発注数を計算して返す"""
    products = db.query(Product).filter(Product.is_active == True).all()
    if not products:
        return []

    settings_row = db.query(OrderSettings).first()
    s = _build_calc_settings(settings_row)

    # SP-API取得（未設定時はモックデータで動作確認）
    from app.core.config import settings as app_settings
    if app_settings.SP_API_REFRESH_TOKEN:
        from app.services.amazon_api import fetch_inventory, fetch_sales
        inventory = fetch_inventory()
        asin_list = [p.asin for p in products if p.asin]
        sales_7  = fetch_sales(7, asin_list)
        sales_15 = fetch_sales(15, asin_list)
        sales_30 = fetch_sales(30, asin_list)
        sales_60 = fetch_sales(60, asin_list)
    else:
        inventory = {}
        sales_7 = sales_15 = sales_30 = sales_60 = {}

    # 発注済み（未削除）の数量をSKUごとに集計
    from sqlalchemy import func as sqlfunc
    ordered_qty_by_sku = dict(
        db.query(OrderHistory.sku, sqlfunc.sum(OrderHistory.qty))
        .filter(OrderHistory.is_deleted == False)
        .group_by(OrderHistory.sku)
        .all()
    )

    result = []
    for p in products:
        inv = inventory.get(p.fnsku, {})
        available   = inv.get("available", 0)
        inbound     = inv.get("inbound", 0)
        processing  = inv.get("processing", 0)
        ordered     = ordered_qty_by_sku.get(p.sku, 0)
        s7  = sales_7.get(p.asin, 0)
        s15 = sales_15.get(p.asin, 0)
        s30 = sales_30.get(p.asin, 0)
        s60 = sales_60.get(p.asin, 0)

        calc = calc_order_qty(
            available=available, inbound=inbound + ordered, processing=processing,
            extra_stock=p.extra_stock or 0,
            sales_7=s7, sales_15=s15, sales_30=s30, sales_60=s60,
            set_size=p.set_size or 1, s=s
        )
        if calc.qty == 0:
            continue

        result.append({
            "product_id": p.id,
            "sku": p.sku or "",
            "name": p.name or "",
            "asin": p.asin or "",
            "fnsku": p.fnsku or "",
            "buy_url": p.buy_url or "",
            "photo_url": p.photo_url or "",
            "color": p.color or "",
            "size": p.size or "",
            "price": p.price or 0,
            "repack": p.repack or "",
            "note": p.note or "",
            "amazon_url": p.amazon_url or (f"https://www.amazon.co.jp/dp/{p.asin}" if p.asin else ""),
            "set_size": p.set_size or 1,
            "available": available,
            "inbound": inbound,
            "ordered": ordered,
            "sales_7": s7,
            "sales_15": s15,
            "sales_30": s30,
            "sales_60": s60,
            "days_left": calc.days_left,
            "daily": calc.daily,
            "stock": calc.stock,
            "recommended_qty": calc.qty,
            "qty": calc.qty,
        })

    return result

@router.post("/export")
def export_excel(req: ExportRequest, db: Session = Depends(get_db)):
    """発注リストをTAO太郎形式のExcelとしてダウンロードし、発注履歴に保存"""
    if not req.items:
        raise HTTPException(status_code=400, detail="発注リストが空です")

    items_data = []
    for item in req.items:
        if item.qty <= 0:
            continue
        items_data.append({
            "sku": item.sku,
            "name": item.name,
            "amazon_url": item.amazon_url,
            "buy_url": item.buy_url,
            "photo_url": item.photo_url,
            "color": item.color,
            "size": item.size,
            "qty": item.qty,
            "price": item.price,
            "repack": item.repack,
            "note": item.note,
            "set_size": item.set_size,
            "asin": item.asin,
            "fnsku": item.fnsku,
        })

    if not items_data:
        raise HTTPException(status_code=400, detail="発注数が0の商品しかありません")

    # 発注履歴に保存
    for item in items_data:
        db.add(OrderHistory(
            sku=item["sku"],
            name=item["name"],
            color=item["color"],
            size=item["size"],
            qty=item["qty"],
            price=item["price"],
            buy_url=item["buy_url"],
            photo_url=item["photo_url"],
            asin=item["asin"],
            fnsku=item["fnsku"],
            note=item["note"],
        ))
    db.commit()

    from datetime import date
    excel_bytes = build_taotaro_excel(items_data)
    filename = f"taotaro_order_{date.today().strftime('%Y%m%d')}.xlsx"

    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/history")
def get_order_history(db: Session = Depends(get_db)):
    """発注済みリストを取得（未削除・新しい順）"""
    rows = db.query(OrderHistory).filter(OrderHistory.is_deleted == False).order_by(OrderHistory.ordered_at.desc()).all()
    return [
        {
            "id": r.id,
            "ordered_at": r.ordered_at.isoformat() if r.ordered_at else None,
            "sku": r.sku,
            "name": r.name,
            "color": r.color,
            "size": r.size,
            "qty": r.qty,
            "price": r.price,
            "buy_url": r.buy_url,
            "photo_url": r.photo_url,
            "asin": r.asin,
            "fnsku": r.fnsku,
            "note": r.note,
        }
        for r in rows
    ]

@router.delete("/history/{history_id}")
def delete_order_history(history_id: int, db: Session = Depends(get_db)):
    """発注済みレコードを削除（FBA納品プラン作成後に呼ぶ）"""
    row = db.query(OrderHistory).filter(OrderHistory.id == history_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="レコードが見つかりません")
    row.is_deleted = True
    db.commit()
    return {"ok": True}

def _build_calc_settings(row: Optional[OrderSettings]) -> CalcSettings:
    if not row:
        return CalcSettings()
    return CalcSettings(
        threshold_days=row.threshold_days,
        target_days_normal=row.target_days_normal,
        target_days_sale=row.target_days_sale,
        weight_d7=row.weight_d7,
        weight_d15=row.weight_d15,
        weight_d30=row.weight_d30,
        weight_d60=row.weight_d60,
        growth_ratio_threshold=row.growth_ratio_threshold,
        growth_multiplier=row.growth_multiplier,
        decline_ratio_threshold=row.decline_ratio_threshold,
        decline_multiplier=row.decline_multiplier,
        min_order_qty=row.min_order_qty,
        sale_enabled=row.sale_enabled,
        sale_start=row.sale_start,
        sale_end=row.sale_end,
    )
