from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import Base, engine
from app.api.routes import products, orders, settings, fba, invoices, price_adjustments, analytics, shipment_orders
from app.api.routes import rakuten
from app.models import invoice as invoice_models
from app.models import order_history as order_history_models
from app.models import price_log as price_log_models
from app.models import rakuten_product as rakuten_product_models
from app.models import rakuten_order as rakuten_order_models
from app.models import rakuten_settings as rakuten_settings_models
from app.models import shipment_order as shipment_order_models
from app.models import rakuten_ss_sales as rakuten_ss_sales_models

def _migrate():
    from sqlalchemy import text, inspect
    import logging
    logger = logging.getLogger("migrate")

    Base.metadata.create_all(bind=engine)

    migrations = [
        ("products",      "selling_price",       "ALTER TABLE products ADD COLUMN selling_price FLOAT"),
        ("products",      "fba_fee",             "ALTER TABLE products ADD COLUMN fba_fee FLOAT"),
        ("products",      "amazon_fee_rate",     "ALTER TABLE products ADD COLUMN amazon_fee_rate FLOAT DEFAULT 0.1"),
        ("products",      "fees_updated_at",     "ALTER TABLE products ADD COLUMN fees_updated_at TIMESTAMP"),
        ("products",      "price_auto_adjust",   "ALTER TABLE products ADD COLUMN price_auto_adjust BOOLEAN DEFAULT TRUE"),
        ("products",      "price_max",           "ALTER TABLE products ADD COLUMN price_max FLOAT"),
        ("products",      "spec",                "ALTER TABLE products ADD COLUMN spec VARCHAR"),
        ("products",      "customer_memo",       "ALTER TABLE products ADD COLUMN customer_memo TEXT"),
        ("products",      "supplier",            "ALTER TABLE products ADD COLUMN supplier VARCHAR DEFAULT 'タオタロウ'"),
        ("order_settings","exchange_rate",        "ALTER TABLE order_settings ADD COLUMN exchange_rate FLOAT DEFAULT 21.0"),
        ("order_settings","price_adjust_enabled", "ALTER TABLE order_settings ADD COLUMN price_adjust_enabled BOOLEAN DEFAULT FALSE"),
        ("order_settings","price_drop_threshold", "ALTER TABLE order_settings ADD COLUMN price_drop_threshold FLOAT DEFAULT 0.20"),
        ("order_settings","price_change_pct",     "ALTER TABLE order_settings ADD COLUMN price_change_pct FLOAT DEFAULT 0.03"),
        ("order_settings","min_profit_rate",      "ALTER TABLE order_settings ADD COLUMN min_profit_rate FLOAT DEFAULT 0.10"),
        ("order_settings","new_product_exclude_vine",  "ALTER TABLE order_settings ADD COLUMN new_product_exclude_vine BOOLEAN DEFAULT TRUE"),
        ("order_settings","lead_days",        "ALTER TABLE order_settings ADD COLUMN lead_days INTEGER DEFAULT 75"),
        ("order_settings","weight_d90",       "ALTER TABLE order_settings ADD COLUMN weight_d90 FLOAT DEFAULT 0.30"),
        ("order_settings","sale_multiplier",  "ALTER TABLE order_settings ADD COLUMN sale_multiplier FLOAT DEFAULT 3.0"),
        # 楽天商品マスタ 追加フィールド
        ("rakuten_products","spec",             "ALTER TABLE rakuten_products ADD COLUMN spec VARCHAR"),
        ("rakuten_products","rakuten_item_url", "ALTER TABLE rakuten_products ADD COLUMN rakuten_item_url VARCHAR"),
        ("rakuten_products","rakuten_sku_id",   "ALTER TABLE rakuten_products ADD COLUMN rakuten_sku_id VARCHAR"),
        ("rakuten_products","supplier",         "ALTER TABLE rakuten_products ADD COLUMN supplier VARCHAR"),
        ("rakuten_products","standard_stock",   "ALTER TABLE rakuten_products ADD COLUMN standard_stock INTEGER DEFAULT 0"),
        ("rakuten_products","customer_memo",    "ALTER TABLE rakuten_products ADD COLUMN customer_memo TEXT"),
        ("rakuten_products","notes",            "ALTER TABLE rakuten_products ADD COLUMN notes TEXT"),
        ("rakuten_products","set_components",   "ALTER TABLE rakuten_products ADD COLUMN set_components TEXT"),
        ("rakuten_products","is_component",       "ALTER TABLE rakuten_products ADD COLUMN is_component BOOLEAN DEFAULT FALSE"),
        ("rakuten_settings","rms_service_secret", "ALTER TABLE rakuten_settings ADD COLUMN rms_service_secret VARCHAR"),
        ("rakuten_settings","rms_license_key",    "ALTER TABLE rakuten_settings ADD COLUMN rms_license_key VARCHAR"),
        ("rakuten_settings","rms_key_expires_at",  "ALTER TABLE rakuten_settings ADD COLUMN rms_key_expires_at DATE"),
        ("rakuten_products","sales_90",            "ALTER TABLE rakuten_products ADD COLUMN sales_90 INTEGER DEFAULT 0"),
        ("rakuten_products","stockout_days_90",    "ALTER TABLE rakuten_products ADD COLUMN stockout_days_90 INTEGER DEFAULT 0"),
        ("rakuten_products","selling_price",       "ALTER TABLE rakuten_products ADD COLUMN selling_price FLOAT"),
        ("rakuten_products","cost_jpy",            "ALTER TABLE rakuten_products ADD COLUMN cost_jpy FLOAT"),
        ("rakuten_settings","commission_rate",     "ALTER TABLE rakuten_settings ADD COLUMN commission_rate FLOAT DEFAULT 0.09"),
        ("rakuten_products","shipping_fee",        "ALTER TABLE rakuten_products ADD COLUMN shipping_fee INTEGER DEFAULT 180"),
        ("rakuten_settings","default_shipping_fee", "ALTER TABLE rakuten_settings ADD COLUMN default_shipping_fee INTEGER DEFAULT 180"),
        ("rakuten_products","supplier_spec",       "ALTER TABLE rakuten_products ADD COLUMN supplier_spec VARCHAR"),
        ("rakuten_products","invoice_note",        "ALTER TABLE rakuten_products ADD COLUMN invoice_note TEXT"),
        # インボイス：輸入許可書情報
        ("invoices","customs_duty",          "ALTER TABLE invoices ADD COLUMN customs_duty INTEGER DEFAULT 0"),
        ("invoices","consumption_tax",       "ALTER TABLE invoices ADD COLUMN consumption_tax INTEGER DEFAULT 0"),
        ("invoices","local_consumption_tax", "ALTER TABLE invoices ADD COLUMN local_consumption_tax INTEGER DEFAULT 0"),
        ("invoices","total_tax",             "ALTER TABLE invoices ADD COLUMN total_tax INTEGER DEFAULT 0"),
        ("invoices","bl_number",             "ALTER TABLE invoices ADD COLUMN bl_number VARCHAR"),
        ("invoices","declaration_no",        "ALTER TABLE invoices ADD COLUMN declaration_no VARCHAR"),
    ]

    inspector = inspect(engine)
    for table, col, sql in migrations:
        try:
            existing = [c["name"] for c in inspector.get_columns(table)]
        except Exception as e:
            logger.warning(f"migrate: get_columns failed for {table}: {e}")
            existing = []
        if col not in existing:
            try:
                with engine.begin() as conn:
                    conn.execute(text(sql))
                logger.info(f"migrate: added {table}.{col}")
            except Exception as e:
                logger.warning(f"migrate: {table}.{col} -> {e}")

    drop_migrations = [
        ("order_settings", "new_product_required_days"),
        ("order_settings", "sale_extra_days"),
    ]
    for table, col in drop_migrations:
        try:
            existing = [c["name"] for c in inspector.get_columns(table)]
        except Exception:
            existing = []
        if col in existing:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
                logger.info(f"migrate: dropped {table}.{col}")
            except Exception as e:
                logger.warning(f"migrate: drop {table}.{col} -> {e}")

from contextlib import asynccontextmanager
import asyncio
import logging
from datetime import datetime as dt, timezone, timedelta

JST = timezone(timedelta(hours=9))
from collections import deque

logger = logging.getLogger("scheduler")

# 在庫同期ログ履歴（直近100件）
_sync_logs: deque = deque(maxlen=100)

# 処理済み注文番号と状態（重複処理防止＋キャンセル状態遷移追跡）
# {order_number: "active" | "cancelled"} — 直近500件を保持
_processed_orders: dict[str, str] = {}
_processed_orders_queue: deque = deque(maxlen=500)

def _get_component_parent_skus(products) -> set:
    """セット商品（set_components有り）の構成品SKUを全て収集して返す"""
    import json as _json
    parent_skus = set()
    for p in products:
        if not p.set_components:
            continue
        try:
            comps = _json.loads(p.set_components)
        except Exception:
            continue
        for c in comps:
            c_sku = c.get("sku")
            if c_sku:
                parent_skus.add(c_sku)
    return parent_skus

async def _sync_rakuten_stock():
    """1分ごと: 受注を検知し、単品在庫を減算（キャンセルは戻す）、セット在庫を再計算する。
    pushは別途 RMS_PUSH_ENABLED で制御。ここではDB在庫の更新のみ。"""
    from app.core.database import SessionLocal
    from app.models.rakuten_settings import RakutenSettings
    from app.models.rakuten_product import RakutenProduct
    from app.services.rakuten_rms import fetch_recent_orders
    import json as _json

    db = SessionLocal()
    try:
        settings = db.query(RakutenSettings).first()
        if not settings or not settings.rms_service_secret or not settings.rms_license_key:
            return

        orders_by_num, order_nums, cancelled_nums = await fetch_recent_orders(
            settings.rms_service_secret, settings.rms_license_key, minutes=2
        )
        if not order_nums:
            return

        # 差分を計算: 新規受注(減算)、新規キャンセル(加算)、状態遷移
        new_sold: dict[str, int] = {}       # 新規有効受注のSKU数量
        new_cancelled: dict[str, int] = {}  # 新規キャンセルのSKU数量（戻す）
        processed_new = 0

        for n in order_nums:
            prev_state = _processed_orders.get(n)
            is_cancelled = n in cancelled_nums
            cur_state = "cancelled" if is_cancelled else "active"

            if prev_state == cur_state:
                continue  # 前回と同じ状態 → 処理済み

            skus = orders_by_num.get(n) or {}
            if not skus:
                continue

            if prev_state is None and cur_state == "active":
                # 新規有効受注 → 減算
                for sku, qty in skus.items():
                    new_sold[sku] = new_sold.get(sku, 0) + qty
            elif prev_state is None and cur_state == "cancelled":
                pass  # 初見でキャンセル済み → 減算も加算もしない
            elif prev_state == "active" and cur_state == "cancelled":
                # 有効→キャンセルに遷移 → 減算分を戻す
                for sku, qty in skus.items():
                    new_cancelled[sku] = new_cancelled.get(sku, 0) + qty

            _processed_orders[n] = cur_state
            _processed_orders_queue.append(n)
            processed_new += 1

        # キューが満杯時、古い注文をdictからも削除
        while len(_processed_orders) > 500:
            old = _processed_orders_queue.popleft()
            _processed_orders.pop(old, None)

        if not new_sold and not new_cancelled:
            if processed_new > 0:
                _sync_logs.appendleft({
                    "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
                    "note": f"受注{processed_new}件処理（在庫変動なし）",
                })
            return

        # 全商品取得・SKU→商品マップ構築
        all_products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
        sku_to_product = {p.sku: p for p in all_products}
        sku_stock = {p.sku: (p.stock or 0) for p in all_products}

        def parse_comps(p):
            try:
                return _json.loads(p.set_components or "[]")
            except Exception:
                return []

        # Step1: 売れたSKUの在庫を減算（セット商品なら構成品を展開して減算）
        updated_skus = set()
        for sku, qty in new_sold.items():
            p = sku_to_product.get(sku)
            if not p:
                continue
            comps = parse_comps(p)
            if comps:
                # セット商品 → 構成品の単品在庫を減算
                for c in comps:
                    c_sku = c.get("sku")
                    c_qty = (c.get("qty") or 1) * qty
                    cp = sku_to_product.get(c_sku)
                    if cp and cp.stock is not None:
                        cp.stock = max(0, cp.stock - c_qty)
                        sku_stock[c_sku] = cp.stock
                        updated_skus.add(c_sku)
            else:
                # 単品 → 自分自身を減算
                if p.stock is not None:
                    p.stock = max(0, p.stock - qty)
                    sku_stock[sku] = p.stock
                    updated_skus.add(sku)

        # Step2: キャンセル分を戻す（セット商品なら構成品を展開して加算）
        for sku, qty in new_cancelled.items():
            p = sku_to_product.get(sku)
            if not p:
                continue
            comps = parse_comps(p)
            if comps:
                for c in comps:
                    c_sku = c.get("sku")
                    c_qty = (c.get("qty") or 1) * qty
                    cp = sku_to_product.get(c_sku)
                    if cp and cp.stock is not None:
                        cp.stock = cp.stock + c_qty
                        sku_stock[c_sku] = cp.stock
                        updated_skus.add(c_sku)
            else:
                if p.stock is not None:
                    p.stock = p.stock + qty
                    sku_stock[sku] = p.stock
                    updated_skus.add(sku)

        # Step3: 更新された単品を参照する全セット商品の在庫を再計算
        for p in all_products:
            comps = parse_comps(p)
            if not comps:
                continue
            if not any(c.get("sku") in updated_skus for c in comps):
                continue
            req: dict[str, int] = {}
            for c in comps:
                c_sku = c.get("sku")
                c_qty = c.get("qty") or 1
                if c_sku:
                    req[c_sku] = req.get(c_sku, 0) + c_qty
            set_qty = None
            for c_sku, c_qty in req.items():
                avail = sku_stock.get(c_sku, 0) // c_qty
                set_qty = avail if set_qty is None else min(set_qty, avail)
            if set_qty is not None:
                p.stock = set_qty
                sku_stock[p.sku] = set_qty

        db.commit()

        _sync_logs.appendleft({
            "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            "sold": new_sold if new_sold else None,
            "cancelled": new_cancelled if new_cancelled else None,
            "updated_skus": list(updated_skus),
        })
        logger.info(f"[scheduler] 在庫更新: sold={new_sold} cancelled={new_cancelled} updated={updated_skus}")
    except Exception as e:
        _sync_logs.appendleft({"time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"), "error": str(e)})
        logger.warning(f"[scheduler] 在庫同期エラー: {e}")
    finally:
        db.close()


async def _sync_rakuten_sales():
    """1時間ごと: RMSから販売数を取得してDBに保存"""
    from app.core.database import SessionLocal
    from app.models.rakuten_settings import RakutenSettings
    from app.models.rakuten_product import RakutenProduct
    from app.services.rakuten_rms import fetch_sales_by_sku
    from datetime import datetime

    db = SessionLocal()
    try:
        settings = db.query(RakutenSettings).first()
        if not settings or not settings.rms_service_secret or not settings.rms_license_key:
            return

        sku_sales = await fetch_sales_by_sku(settings.rms_service_secret, settings.rms_license_key, days=60)
        products = db.query(RakutenProduct).filter(
            RakutenProduct.is_active == True, RakutenProduct.is_component == False
        ).all()
        updated = 0
        for p in products:
            sales = sku_sales.get(p.rakuten_sku_id or "") or sku_sales.get(p.sku or "") or {}
            if sales:
                p.sales_30_recent  = sales.get("recent", 0)
                p.sales_30_prev    = sales.get("prev", 0)
                p.sales_90         = sales.get("total_90", 0)
                p.stockout_days_90 = sales.get("stockout_days", 0)
                p.sales_updated_at = datetime.now()
                updated += 1
        db.commit()
        logger.info(f"[scheduler] 販売数同期完了: {updated}件")
    except Exception as e:
        logger.warning(f"[scheduler] 販売数同期エラー: {e}")
    finally:
        db.close()


async def _pull_rms_stock():
    """RMSから在庫数を取得してDBに上書き。
    ただし「セットの構成品になっている単品SKU」はpullで上書きしない。
    単品在庫はツールが受注減算で管理し、セット在庫は楽天から取得する。"""
    from app.core.database import SessionLocal
    from app.models.rakuten_settings import RakutenSettings
    from app.models.rakuten_product import RakutenProduct
    from app.services.rakuten_rms import fetch_inventory_from_rms

    db = SessionLocal()
    try:
        settings = db.query(RakutenSettings).first()
        if not settings or not settings.rms_service_secret or not settings.rms_license_key:
            return

        products = db.query(RakutenProduct).filter(
            RakutenProduct.is_active == True,
        ).all()
        sku_to_product = {p.sku: p for p in products}

        # セットの構成品になっているSKUを特定（pullで上書きしない対象）
        component_parent_skus = _get_component_parent_skus(products)

        import re as _re
        items = []
        for p in products:
            sku = (p.sku or "").strip()
            if not sku or p.is_component:
                continue
            if not _re.match(r'^[a-zA-Z0-9_\-]+$', sku):
                continue
            manage_number = (p.rakuten_item_url or sku.split("_")[0]).strip()
            items.append({"manage_number": manage_number, "variant_id": sku})

        rms_stock = await fetch_inventory_from_rms(
            settings.rms_service_secret, settings.rms_license_key, items
        )

        updated = 0
        skipped = 0
        for sku, qty in rms_stock.items():
            p = sku_to_product.get(sku)
            if not p:
                continue
            # セットの構成品になっている単品はpullで上書きしない（受注減算で管理）
            if sku in component_parent_skus:
                skipped += 1
                continue
            p.stock = qty
            updated += 1

        db.commit()
        logger.info(f"[scheduler] RMS在庫取得完了: {updated}件更新, {skipped}件スキップ(単品管理)")
        _sync_logs.appendleft({
            "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            "type": "rms_stock",
            "updated": updated,
            "sent": len(items),
            "skipped_component_parents": skipped,
        })
    except Exception as e:
        logger.warning(f"[scheduler] RMS在庫取得エラー: {e}")
        _sync_logs.appendleft({
            "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            "type": "rms_stock",
            "error": str(e),
        })
    finally:
        db.close()


async def _scheduler_loop():
    """1分ごとに受注差分の在庫同期＋RMS在庫取得、1時間ごとに販売数同期を実行"""
    # 起動直後にRMS在庫を1回取得しておく（デプロイ/再起動後すぐ最新にする）
    await _pull_rms_stock()
    tick = 0
    while True:
        await asyncio.sleep(60)
        tick += 1
        await _sync_rakuten_stock()
        await _pull_rms_stock()  # 1分ごと: RMSから最新在庫を取得
        if tick % 60 == 0:  # 60分ごと: 販売数同期（60日分の受注取得で重いため低頻度）
            await _sync_rakuten_sales()


@asynccontextmanager
async def lifespan(app):
    _migrate()
    task = asyncio.create_task(_scheduler_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="中国輸入管理ツール", version="0.1.0", lifespan=lifespan)

import os
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000,https://misa-sep13.github.io").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(fba.router, prefix="/api")
app.include_router(invoices.router, prefix="/api")
app.include_router(price_adjustments.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(rakuten.router, prefix="/api")
app.include_router(shipment_orders.router, prefix="/api")

@app.get("/")
def root():
    return {"message": "中国輸入管理ツール API"}

@app.get("/api/sync-logs")
def get_sync_logs():
    """在庫同期ログ履歴（直近100件）"""
    return {"logs": list(_sync_logs)}


