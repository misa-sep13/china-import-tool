from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import Base, engine
from app.api.routes import products, orders, settings, fba, invoices, price_adjustments
from app.models import invoice as invoice_models
from app.models import order_history as order_history_models
from app.models import price_log as price_log_models

Base.metadata.create_all(bind=engine)

# カラム追加マイグレーション（既存DBへの安全な追加）
def _migrate():
    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        migrations = [
            ("products",      "selling_price",       "ALTER TABLE products ADD COLUMN selling_price FLOAT"),
            ("products",      "fba_fee",             "ALTER TABLE products ADD COLUMN fba_fee FLOAT"),
            ("products",      "amazon_fee_rate",     "ALTER TABLE products ADD COLUMN amazon_fee_rate FLOAT DEFAULT 0.1"),
            ("products",      "fees_updated_at",     "ALTER TABLE products ADD COLUMN fees_updated_at TIMESTAMP"),
            ("products",      "price_auto_adjust",   "ALTER TABLE products ADD COLUMN price_auto_adjust BOOLEAN DEFAULT 1"),
            ("products",      "price_max",           "ALTER TABLE products ADD COLUMN price_max FLOAT"),
            ("order_settings","exchange_rate",        "ALTER TABLE order_settings ADD COLUMN exchange_rate FLOAT DEFAULT 21.0"),
            ("order_settings","price_adjust_enabled", "ALTER TABLE order_settings ADD COLUMN price_adjust_enabled BOOLEAN DEFAULT 0"),
            ("order_settings","price_drop_threshold", "ALTER TABLE order_settings ADD COLUMN price_drop_threshold FLOAT DEFAULT 0.20"),
            ("order_settings","price_change_pct",     "ALTER TABLE order_settings ADD COLUMN price_change_pct FLOAT DEFAULT 0.03"),
            ("order_settings","min_profit_rate",      "ALTER TABLE order_settings ADD COLUMN min_profit_rate FLOAT DEFAULT 0.10"),
        ]
        inspector = inspect(engine)
        for table, col, sql in migrations:
            existing = [c["name"] for c in inspector.get_columns(table)]
            if col not in existing:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                except Exception:
                    pass

_migrate()

app = FastAPI(title="中国輸入管理ツール", version="0.1.0")

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

@app.get("/")
def root():
    return {"message": "中国輸入管理ツール API"}


