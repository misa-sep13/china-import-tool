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

        if app_settings.SP_API_REFRESH_TOKEN:
            from app.services.amazon_api import fetch_inventory, fetch_sales_detail
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_inv   = ex.submit(fetch_inventory)
                f_sales = ex.submit(fetch_sales_detail, asin_list, days)
            inventory   = f_inv.result()
            sales_detail = f_sales.result()
        else:
            inventory = {}
            sales_detail = {}

        # 為替レート
        settings_row = db.query(OrderSettings).first()
        exchange_rate = getattr(settings_row, 'exchange_rate', 21.0) or 21.0
        amazon_fee_rate = 0.1  # デフォルト10%

        items = []
        total_revenue = 0
        total_units = 0
        total_profit = 0

        for p in products:
            inv = inventory.get(p.fnsku, {})
            available  = inv.get("available", 0)
            inbound    = inv.get("inbound", 0)
            sd = sales_detail.get(p.asin, {"units": 0, "revenue": 0, "avg_price": 0})
            units   = sd["units"]
            revenue = sd["revenue"]
            avg_price = sd["avg_price"] or (p.selling_price or 0)

            # 手数料計算
            fba_fee      = (p.fba_fee or 0) * units
            amazon_fee   = round(revenue * (p.amazon_fee_rate or amazon_fee_rate), 0)
            cost_jpy     = round((p.price or 0) * exchange_rate * units, 0)
            total_cost   = fba_fee + amazon_fee + cost_jpy
            profit       = round(revenue - total_cost, 0)
            profit_rate  = round(profit / revenue * 100, 1) if revenue > 0 else 0

            total_revenue += revenue
            total_units   += units
            total_profit  += profit

            items.append({
                "product_id":   p.id,
                "asin":         p.asin or "",
                "sku":          p.sku or "",
                "name":         p.name or "",
                "photo_url":    p.photo_url or "",
                "amazon_url":   p.amazon_url or (f"https://www.amazon.co.jp/dp/{p.asin}" if p.asin else ""),
                "color":        p.color or "",
                "size":         p.size or "",
                # 売上
                "units":        units,
                "revenue":      revenue,
                "avg_price":    avg_price,
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
        keys = [k for k in _cache if k.startswith("sales_detail")]
        for k in keys:
            _cache.pop(k, None)
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
