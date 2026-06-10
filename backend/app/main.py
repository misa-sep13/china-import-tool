from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import Base, engine
from app.api.routes import products, orders, settings, fba, invoices, price_adjustments, analytics
from app.api.routes import rakuten
from app.models import invoice as invoice_models
from app.models import order_history as order_history_models
from app.models import price_log as price_log_models
from app.models import rakuten_product as rakuten_product_models
from app.models import rakuten_order as rakuten_order_models
from app.models import rakuten_settings as rakuten_settings_models

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
        ("rakuten_settings","rms_key_expires_at", "ALTER TABLE rakuten_settings ADD COLUMN rms_key_expires_at DATE"),
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

@asynccontextmanager
async def lifespan(app):
    _migrate()
    yield

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

@app.get("/")
def root():
    return {"message": "中国輸入管理ツール API"}


