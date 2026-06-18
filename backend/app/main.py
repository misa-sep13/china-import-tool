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

logger = logging.getLogger("scheduler")

async def _sync_rakuten_stock():
    """1分ごと: 直近2分の受注差分で在庫を減算する（全商品取得不要でメモリ節約）"""
    from app.core.database import SessionLocal
    from app.models.rakuten_settings import RakutenSettings
    from app.models.rakuten_product import RakutenProduct
    from app.services.rakuten_rms import fetch_recent_orders

    db = SessionLocal()
    try:
        settings = db.query(RakutenSettings).first()
        if not settings or not settings.rms_service_secret or not settings.rms_license_key:
            return

        sold = await fetch_recent_orders(settings.rms_service_secret, settings.rms_license_key, minutes=2)
        if not sold:
            return

        updated = 0
        for sku, qty in sold.items():
            p = db.query(RakutenProduct).filter(RakutenProduct.sku == sku).first()
            if p and p.stock is not None:
                p.stock = max(0, p.stock - qty)
                updated += 1
        db.commit()
        if updated:
            logger.info(f"[scheduler] 在庫差分更新: {updated}件 sold={sold}")
    except Exception as e:
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


async def _scheduler_loop():
    """1分ごとに在庫同期、1時間ごとに販売数同期を実行"""
    tick = 0
    while True:
        await asyncio.sleep(60)
        tick += 1
        logger.warning(f"[scheduler] tick={tick} 在庫同期開始")
        await _sync_rakuten_stock()
        if tick % 60 == 0:  # 60分ごと
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


