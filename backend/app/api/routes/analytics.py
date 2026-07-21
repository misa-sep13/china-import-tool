from fastapi import APIRouter, BackgroundTasks
from app.core.database import SessionLocal
from app.models.product import Product
from app.models.settings import OrderSettings
import threading, time, uuid

router = APIRouter(prefix="/analytics", tags=["analytics"])

_jobs: dict = {}
_jobs_lock = threading.Lock()


def _prune_jobs():
    """古い・完了済みのジョブをメモリから掃除する。
    結果（全商品リスト）を保持したまま残り続けると、毎時のウォームアップの
    たびに溜まってメモリリークになる（Render 512MBのOOM要因）。"""
    now = time.time()
    with _jobs_lock:
        for jid in [j for j, v in _jobs.items() if now - v.get("started_at", now) > 1200]:
            _jobs.pop(jid, None)
        if len(_jobs) > 10:
            for jid, _ in sorted(_jobs.items(), key=lambda kv: kv[1].get("started_at", 0))[:-10]:
                _jobs.pop(jid, None)


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
            from app.services.amazon_api import fetch_inventory, fetch_sales_detail, fetch_catalog_info, fetch_all_sales, fetch_new_product_info, fetch_ads_data
            with ThreadPoolExecutor(max_workers=7) as ex:
                f_inv       = ex.submit(fetch_inventory)
                f_sales     = ex.submit(fetch_sales_detail, asin_list, days)
                _oqc = getattr(db.query(OrderSettings).first(), 'order_qty_cap', 0) or 0
                f_all_sales = ex.submit(fetch_all_sales, asin_list, _oqc)
                f_catalog   = ex.submit(fetch_catalog_info, asin_list)
                f_t4s       = ex.submit(fetch_product_data, asin_list, days)
                f_new       = ex.submit(fetch_new_product_info, asin_list)
                f_ads       = ex.submit(fetch_ads_data, asin_list, days)
            inventory    = f_inv.result()
            sales_detail = f_sales.result()
            catalog_info = f_catalog.result()
            all_sales_7, all_sales_15, all_sales_30, all_sales_60, all_sales_90 = f_all_sales.result()
            new_product_info = f_new.result()
            ads_data = f_ads.result()
            try:
                t4s_data = f_t4s.result()
            except Exception:
                t4s_data = {}
        else:
            inventory = {}
            sales_detail = {}
            catalog_info = {}
            all_sales_7 = all_sales_15 = all_sales_30 = all_sales_60 = all_sales_90 = {}
            new_product_info = {}
            ads_data = {}
            try:
                t4s_data = fetch_product_data(asin_list, days)
            except Exception:
                t4s_data = {}

        # 設定値取得
        settings_row = db.query(OrderSettings).first()
        exchange_rate = getattr(settings_row, 'exchange_rate', 21.0) or 21.0
        amazon_fee_rate = 0.1
        exclude_vine = getattr(settings_row, 'new_product_exclude_vine', True)

        # 発注計算設定（発注管理と同じロジック）
        from app.services.calc import CalcSettings, calc_order_qty
        from app.api.routes.orders import _build_calc_settings
        from app.models.order_history import OrderHistory
        from sqlalchemy import func as sqlfunc
        calc_settings = _build_calc_settings(settings_row)

        ordered_qty_by_sku = dict(
            db.query(OrderHistory.sku, sqlfunc.sum(OrderHistory.qty))
            .filter(OrderHistory.is_deleted == False)
            .group_by(OrderHistory.sku)
            .all()
        )

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
            fba_fee_unit = p.fba_fee
            fba_fee      = (fba_fee_unit or 0) * normal_units
            amazon_fee   = round(normal_revenue * (p.amazon_fee_rate or amazon_fee_rate), 0)
            cost_jpy     = round((p.price or 0) * normal_units, 0)
            total_cost   = fba_fee + amazon_fee + cost_jpy
            profit       = round(normal_revenue - total_cost, 0)
            profit_rate  = round(profit / normal_revenue * 100, 1) if normal_revenue > 0 else 0

            # 発注数計算
            ordered = ordered_qty_by_sku.get(p.sku, 0)
            processing = inventory.get(p.fnsku, {}).get("processing", 0)
            stock = available + inbound + ordered + processing + (p.extra_stock or 0)
            np_info = new_product_info.get(p.asin, {})
            elapsed_days = np_info.get("elapsed_days")  # Noneなら既存商品

            if elapsed_days is not None:
                # 新商品: 累計販売数÷経過日数×リードタイム−在庫
                total_units_np = np_info.get("total_units", 0)
                vine_units = vine_orders if exclude_vine else 0
                net_total = max(total_units_np - vine_units, 0)
                daily_new = net_total / elapsed_days if elapsed_days > 0 else 0
                need = max(0, round(daily_new * (calc_settings.lead_days or 75) - stock))
                set_size = max(1, p.set_size or 1)
                qty_sets = -(-need // set_size) if need > 0 else 0
                new_order_qty = qty_sets * set_size
                is_new_product = True
            else:
                # 既存商品: 発注管理と同じロジック
                s7  = all_sales_7.get(p.asin, 0)
                s15 = all_sales_15.get(p.asin, 0)
                s30 = all_sales_30.get(p.asin, 0)
                s60 = all_sales_60.get(p.asin, 0)
                s90 = all_sales_90.get(p.asin, 0)
                calc = calc_order_qty(
                    available=available, inbound=inbound + ordered, processing=processing,
                    extra_stock=p.extra_stock or 0,
                    sales_7=s7, sales_15=s15, sales_30=s30, sales_60=s60,
                    set_size=p.set_size or 1, s=calc_settings, sales_90=s90,
                )
                new_order_qty = calc.qty_pieces
                is_new_product = False

            # 広告データ
            ads = ads_data.get(p.asin, {})
            ad_spend    = ads.get("ad_spend") or None
            impressions = ads.get("impressions") or None
            clicks      = ads.get("clicks") or None
            ad_orders   = ads.get("ad_orders") or None
            ad_revenue  = ads.get("ad_revenue") or None
            acos  = round(ad_spend / ad_revenue * 100, 1) if ad_spend and ad_revenue else None
            roas  = round(ad_revenue / ad_spend, 2)       if ad_spend and ad_revenue else None
            tacos = round(ad_spend / normal_revenue * 100, 1) if ad_spend and normal_revenue else None
            ctr   = round(clicks / impressions * 100, 2)  if clicks and impressions else None
            ad_cvr = round(ad_orders / clicks * 100, 1)   if ad_orders and clicks else None
            ad_revenue_rate = round(ad_revenue / normal_revenue * 100, 1) if ad_revenue and normal_revenue else None

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
                "elapsed_days":  elapsed_days if elapsed_days is not None and elapsed_days < 9999 else None,
                # コスト
                "fba_fee_unit": fba_fee_unit,
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
                "ad_spend":         round(ad_spend, 0) if ad_spend else None,
                "impressions":      impressions,
                "clicks":           clicks,
                "ctr":              ctr,
                "acos":             acos,
                "roas":             roas,
                "tacos":            tacos,
                "ad_orders":        ad_orders,
                "ad_cvr":           ad_cvr,
                "ad_revenue":       round(ad_revenue, 0) if ad_revenue else None,
                "ad_revenue_rate":  ad_revenue_rate,
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
        import traceback
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = f"{str(e)}\n{traceback.format_exc()}"
    finally:
        db.close()


@router.post("/start")
def start_analytics(background_tasks: BackgroundTasks, days: int = 30, force: bool = False):
    _prune_jobs()
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
