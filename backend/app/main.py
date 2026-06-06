from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import Base, engine
from app.api.routes import products, orders, settings, fba, invoices
from app.models import invoice as invoice_models
from app.models import order_history as order_history_models

Base.metadata.create_all(bind=engine)

# カラム追加マイグレーション（既存DBへの安全な追加）
def _migrate():
    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        migrations = [
            ("products",      "selling_price",   "ALTER TABLE products ADD COLUMN selling_price FLOAT"),
            ("products",      "fba_fee",         "ALTER TABLE products ADD COLUMN fba_fee FLOAT"),
            ("products",      "amazon_fee_rate", "ALTER TABLE products ADD COLUMN amazon_fee_rate FLOAT DEFAULT 0.1"),
            ("products",      "fees_updated_at", "ALTER TABLE products ADD COLUMN fees_updated_at TIMESTAMP"),
            ("order_settings","exchange_rate",   "ALTER TABLE order_settings ADD COLUMN exchange_rate FLOAT DEFAULT 21.0"),
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

@app.get("/")
def root():
    return {"message": "中国輸入管理ツール API"}


