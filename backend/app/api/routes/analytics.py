from fastapi import APIRouter, BackgroundTasks
from app.core.database import SessionLocal
from app.models.product import Product
from app.models.settings import OrderSettings
import threading, time, uuid

router = APIRouter(prefix="/analytics", tags=["analytics"])

_jobs: dict = {}
_jobs_lock = threading.Lock()


def _run_analytics_job(job_id: str, days: int):
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "result": None, "error": None, "started_at": time.time()}

    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.is_active == True).all()
        if not products:
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["result"] = {"summary": {}, "items": []}
            return

        from app.core.config import settings as app_settings
        from concurrent.futures import ThreadPoolExecutor

        asin_list = [p.asin for p in products if p.asin]

        from app.services.tool4seller import fetch_product_data

        if app_settings.SP_API_REFRESH_TOKEN:
            from app.services.amazon_api import fetch_inventory, fetch_sales_detail, fetch_catalog_info
            with ThreadPoolExecutor(max_workers=4) as ex:
                f_inv     = ex.submit(fetch_inventory)
                f_sales   = ex.submit(fetch_sales_detail, asin_list, days)
                f_catalog = ex.submit(fetch_catalog_info, asin_list)
                f_t4s     = ex.submit(fetch_product_data, asin_list, days)
            inventory    = f_inv.result()
            sales_detail = f_sales.result()
            catalog_info = f_catalog.result()
            try:
                t4s_data = f_t4s.result()
            except Exception:
                t4s_data = {}
        else:
            inventory = {}
            sales_detail = {}
            catalog_info = {}
            try:
                t4s_data = fetch_product_data(asin_list, days)
            except Exception:
                t4s_data = {}

        # 設定値取得
        settings_row = db.query(OrderSettings).first()
        exchange_rate = getattr(settings_row, 'exchange_rate', 21.0) or 21.0
        amazon_fee_rate = 0.1
        required_days = getattr(settings_row, 'new_product_required_days', 30) or 30
        exclude_vine = getattr(settings_row, 'new_product_exclude_vine', True)

        # 子ASIN→親ASINのマッピングを構築（Tool4Sellerはparentasin単位）
        child_to_parent = {}
        for asin, cat_data in catalog_info.items():
            pa = cat_data.get("parent_asin")
            if pa:
                child_to_parent[asin] = pa

        items = []
        total_revenue = 0
        total_units = 0
        total_profit = 0

        for p in products:
            inv = inventory.get(p.fnsku, {})
            available  = inv.get("available", 0)
            inbound    = inv.get("inbound", 0)
            cat = catalog_info.get(p.asin, {})
            # Tool4Sellerデータ（parentAsin経由でマッチング）
            parent_asin = child_to_parent.get(p.asin) or p.asin
            t4s = t4s_data.get(parent_asin) or t4s_data.get(p.asin) or {}
            t4s_rating    = t4s.get("rating")
            vine_revenue  = t4s.get("promotion") or 0
            sd = sales_detail.get(p.asin, {"units": 0, "revenue": 0, "avg_price": 0})
            units   = sd["units"]
            revenue = sd["revenue"]
            avg_price = sd["avg_price"] or (p.selling_price or 0)

            # VINE除外後の通常販売数・売上
            vine_orders = t4s.get("orders") or 0 if vine_revenue > 0 else 0
            normal_units   = max(units - vine_orders, 0)
            normal_revenue = max(revenue - vine_revenue, 0)

            # 手数料計算（VINE分を除外）
            fba_fee      = (p.fba_fee or 0) * normal_units
            amazon_fee   = round(normal_revenue * (p.amazon_fee_rate or amazon_fee_rate), 0)
            cost_jpy     = round((p.price or 0) * exchange_rate * normal_units, 0)
            total_cost   = fba_fee + amazon_fee + cost_jpy
            profit       = round(normal_revenue - total_cost, 0)
            profit_rate  = round(profit / normal_revenue * 100, 1) if normal_revenue > 0 else 0

            # 発注数計算（vine_ordersは上で計算済み）
            net_units = normal_units if exclude_vine else units

            # 商品登録日から経過日数を計算
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            if p.created_at:
                created = p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=timezone.utc)
                elapsed_days = max((now - created).days, 1)
            else:
                elapsed_days = 9999

            if elapsed_days < 90:
                # 新商品: 経過日数ベースで計算
                new_order_qty = round(net_units / elapsed_days * required_days)
                is_new_product = True
            else:
                # 既存商品: 選択期間ベースで計算
                new_order_qty = round(net_units / days * required_days) if days > 0 else 0
                is_new_product = False

            total_revenue += normal_revenue
            total_units   += normal_units
            total_profit  += profit

            items.append({
                "product_id":   p.id,
                "asin":         p.asin or "",
                "sku":          p.sku or "",
                "name":         p.name or "",
                "photo_url":    cat.get("image_url") or p.photo_url or "",
                "rating":       t4s_rating if t4s_rating is not None else cat.get("rating"),
                "rating_count": cat.get("rating_count"),
                "amazon_url":   p.amazon_url or (f"https://www.amazon.co.jp/dp/{p.asin}" if p.asin else ""),
                "color":        p.color or "",
                "size":         p.size or "",
                # 売上（VINE除外後）
                "units":        normal_units,
                "revenue":      normal_revenue,
                "avg_price":    avg_price,
                "total_units":  units,       # VINE含む総販売数
                "total_revenue": revenue,    # VINE含む総売上
                "vine_revenue":   vine_revenue,
                "vine_orders":   vine_orders,
                "new_order_qty": new_order_qty,
                "is_new_product": is_new_product,
                "elapsed_days":  elapsed_days if elapsed_days < 9999 else None,
                # コスト
                "fba_fee":      fba_fee,
                "amazon_fee":   amazon_fee,
                "cost_jpy":     cost_jpy,
                "total_cost":   total_cost,
                # 利益
                "profit":       profit,
                "profit_rate":  profit_rate,
                # 在庫
                "available":    available,
                "inbound":      inbound,
                # 広告（Ads API実装後に追加）
                "ad_spend":     None,
                "acos":         None,
                "roas":         None,
                "impressions":  None,
                "clicks":       None,
                "ctr":          None,
            })

        # 売上順にソート
        items.sort(key=lambda x: x["revenue"], reverse=True)

        summary = {
            "revenue":      round(total_revenue, 0),
            "units":        total_units,
            "profit":       round(total_profit, 0),
            "profit_rate":  round(total_profit / total_revenue * 100, 1) if total_revenue > 0 else 0,
        }

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = {"summary": summary, "items": items}

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
    finally:
        db.close()


@router.post("/start")
def start_analytics(background_tasks: BackgroundTasks, days: int = 30, force: bool = False):
    if force:
        from app.services.amazon_api import _cache
        keys = [k for k in _cache if k.startswith("sales_detail") or k == "catalog_info"]
        for k in keys:
            _cache.pop(k, None)
        from app.services.tool4seller import _data_cache
        _data_cache.clear()
    job_id = str(uuid.uuid4())
    background_tasks.add_task(_run_analytics_job, job_id, days)
    return {"job_id": job_id}


@router.get("/status/{job_id}")
def get_analytics_status(job_id: str):
    from fastapi import HTTPException
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {
        "status":  job["status"],
        "result":  job["result"],
        "error":   job["error"],
        "elapsed": round(time.time() - job["started_at"], 1),
    }
