from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import io
from app.core.database import get_db
from app.models.product import Product
from app.models.settings import OrderSettings
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

    result = []
    for p in products:
        inv = inventory.get(p.fnsku, {})
        available   = inv.get("available", 0)
        inbound     = inv.get("inbound", 0)
        processing  = inv.get("processing", 0)
        s7  = sales_7.get(p.asin, 0)
        s15 = sales_15.get(p.asin, 0)
        s30 = sales_30.get(p.asin, 0)
        s60 = sales_60.get(p.asin, 0)

        calc = calc_order_qty(
            available=available, inbound=inbound, processing=processing,
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
def export_excel(req: ExportRequest):
    """発注リストをTAO太郎形式のExcelとしてダウンロード"""
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
        })

    if not items_data:
        raise HTTPException(status_code=400, detail="発注数が0の商品しかありません")

    from datetime import date
    excel_bytes = build_taotaro_excel(items_data)
    filename = f"taotaro_order_{date.today().strftime('%Y%m%d')}.xlsx"

    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

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
