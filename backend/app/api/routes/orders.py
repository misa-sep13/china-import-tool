from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import io
import uuid
import time
import threading
from app.core.database import get_db, SessionLocal
from app.models.product import Product
from app.models.settings import OrderSettings
from app.models.order_history import OrderHistory
from app.services.calc import CalcSettings, calc_order_qty
from app.services.excel_export import build_taotaro_excel

router = APIRouter(prefix="/orders", tags=["orders"])

# バックグラウンドジョブ管理（メモリ内）
_jobs: dict = {}
_jobs_lock = threading.Lock()

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
    spec: str = ""
    customer_memo: str = ""
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


def _run_preview_job(job_id: str):
    """バックグラウンドでSP-APIデータを取得して推奨発注数を計算"""
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "result": None, "error": None, "started_at": time.time()}

    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.is_active == True).all()
        if not products:
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["result"] = []
            return

        settings_row = db.query(OrderSettings).first()
        s = _build_calc_settings(settings_row)

        from app.core.config import settings as app_settings
        if app_settings.SP_API_REFRESH_TOKEN:
            from app.services.amazon_api import fetch_inventory, fetch_all_sales
            from concurrent.futures import ThreadPoolExecutor
            asin_list = [p.asin for p in products if p.asin]
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_inv   = ex.submit(fetch_inventory)
                f_sales = ex.submit(fetch_all_sales, asin_list)
            inventory = f_inv.result()
            sales_7, sales_15, sales_30, sales_60, sales_90 = f_sales.result()
        else:
            inventory = {}
            sales_7 = sales_15 = sales_30 = sales_60 = sales_90 = {}

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
            s90 = sales_90.get(p.asin, 0)

            calc = calc_order_qty(
                available=available, inbound=inbound + ordered, processing=processing,
                extra_stock=p.extra_stock or 0,
                sales_7=s7, sales_15=s15, sales_30=s30, sales_60=s60,
                set_size=p.set_size or 1, s=s, sales_90=s90,
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
                "spec": p.spec or "",
                "customer_memo": p.customer_memo or "",
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
                "sales_90": s90,
                "days_left": calc.days_left,
                "daily": calc.daily,
                "stock": calc.stock,
                "recommended_qty": calc.qty,
                "qty": calc.qty,
            })

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
    finally:
        db.close()


def _run_stock_job(job_id: str):
    """全在庫一覧用バックグラウンドジョブ（推奨発注数マイナス含む全商品）"""
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "result": None, "error": None, "started_at": time.time()}

    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.is_active == True).all()
        if not products:
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["result"] = []
            return

        settings_row = db.query(OrderSettings).first()
        s = _build_calc_settings(settings_row)

        from app.core.config import settings as app_settings
        if app_settings.SP_API_REFRESH_TOKEN:
            from app.services.amazon_api import fetch_inventory, fetch_all_sales
            from concurrent.futures import ThreadPoolExecutor
            asin_list = [p.asin for p in products if p.asin]
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_inv   = ex.submit(fetch_inventory)
                f_sales = ex.submit(fetch_all_sales, asin_list)
            inventory = f_inv.result()
            sales_7, sales_15, sales_30, sales_60, sales_90 = f_sales.result()
        else:
            inventory = {}
            sales_7 = sales_15 = sales_30 = sales_60 = sales_90 = {}

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
            available  = inv.get("available", 0)
            inbound    = inv.get("inbound", 0)
            processing = inv.get("processing", 0)
            ordered    = ordered_qty_by_sku.get(p.sku, 0)
            s7  = sales_7.get(p.asin, 0)
            s15 = sales_15.get(p.asin, 0)
            s30 = sales_30.get(p.asin, 0)
            s60 = sales_60.get(p.asin, 0)
            s90 = sales_90.get(p.asin, 0)

            calc = calc_order_qty(
                available=available, inbound=inbound + ordered, processing=processing,
                extra_stock=p.extra_stock or 0,
                sales_7=s7, sales_15=s15, sales_30=s30, sales_60=s60,
                set_size=p.set_size or 1, s=s, sales_90=s90,
            )

            # 全商品を表示。在庫充足の場合はneeded_piecesをマイナスで計算
            from app.services.calc import weighted_daily
            daily = weighted_daily(s7, s15, s30, s60, s90, s)
            stock = available + inbound + ordered + processing + (p.extra_stock or 0)
            needed_pieces = round(daily * calc.growth * s.lead_days - stock) if daily > 0 else 0

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
                "spec": p.spec or "",
                "customer_memo": p.customer_memo or "",
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
                "sales_90": s90,
                "days_left": calc.days_left,
                "daily": round(daily, 2),
                "stock": stock,
                "recommended_qty": calc.qty,
                "recommended_pieces": needed_pieces,
                "qty": max(0, calc.qty),
            })

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
    finally:
        db.close()


@router.post("/stock/start")
def start_stock(background_tasks: BackgroundTasks, force: bool = False):
    """全在庫一覧取得をバックグラウンドで開始"""
    if force:
        from app.services.amazon_api import _cache
        _cache.clear()
    job_id = str(uuid.uuid4())
    background_tasks.add_task(_run_stock_job, job_id)
    return {"job_id": job_id}


@router.post("/preview/start")
def start_preview(background_tasks: BackgroundTasks, force: bool = False):
    """SP-APIデータ取得をバックグラウンドで開始し、job_idを返す。force=TrueでキャッシュをクリアしてからAPIを叩く"""
    if force:
        from app.services.amazon_api import _cache
        _cache.clear()
    job_id = str(uuid.uuid4())
    background_tasks.add_task(_run_preview_job, job_id)
    return {"job_id": job_id}


@router.get("/preview/status/{job_id}")
def get_preview_status(job_id: str):
    """ジョブの状態と結果を返す"""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {
        "status": job["status"],   # "running" | "done" | "error"
        "result": job["result"],
        "error": job["error"],
        "elapsed": round(time.time() - job["started_at"], 1),
    }


@router.get("/preview")
def preview_orders(db: Session = Depends(get_db)):
    """後方互換：同期でSP-APIデータ取得（キャッシュ済みなら高速）"""
    products = db.query(Product).filter(Product.is_active == True).all()
    if not products:
        return []

    settings_row = db.query(OrderSettings).first()
    s = _build_calc_settings(settings_row)

    from app.core.config import settings as app_settings
    if app_settings.SP_API_REFRESH_TOKEN:
        from app.services.amazon_api import fetch_inventory, fetch_all_sales
        from concurrent.futures import ThreadPoolExecutor
        asin_list = [p.asin for p in products if p.asin]
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_inv   = ex.submit(fetch_inventory)
            f_sales = ex.submit(fetch_all_sales, asin_list)
        inventory = f_inv.result()
        sales_7, sales_15, sales_30, sales_60, sales_90 = f_sales.result()
    else:
        inventory = {}
        sales_7 = sales_15 = sales_30 = sales_60 = sales_90 = {}

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
        s90 = sales_90.get(p.asin, 0)

        calc = calc_order_qty(
            available=available, inbound=inbound + ordered, processing=processing,
            extra_stock=p.extra_stock or 0,
            sales_7=s7, sales_15=s15, sales_30=s30, sales_60=s60,
            set_size=p.set_size or 1, s=s, sales_90=s90,
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
            "spec": p.spec or "",
            "customer_memo": p.customer_memo or "",
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
            "sales_90": s90,
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
            "spec": item.spec,
            "customer_memo": item.customer_memo,
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
    filename = f"{date.today().strftime('%Y%m%d')}_order.xlsx"

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
        lead_days=getattr(row, 'lead_days', 93) or 93,
        weight_d7=row.weight_d7,
        weight_d15=row.weight_d15,
        weight_d30=row.weight_d30,
        weight_d60=row.weight_d60,
        weight_d90=getattr(row, 'weight_d90', 0.30) or 0.30,
        growth_ratio_threshold=row.growth_ratio_threshold,
        growth_multiplier=min(row.growth_multiplier, 1.0),
        decline_ratio_threshold=row.decline_ratio_threshold,
        decline_multiplier=max(row.decline_multiplier, 0.5),
        min_order_qty=row.min_order_qty,
        sale_enabled=row.sale_enabled,
        sale_start=row.sale_start,
        sale_end=row.sale_end,
        sale_extra_days=getattr(row, 'sale_extra_days', 0) or 0,
        # 後方互換
        threshold_days=row.threshold_days,
        target_days_normal=row.target_days_normal,
        target_days_sale=row.target_days_sale,
    )
