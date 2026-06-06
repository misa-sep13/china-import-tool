"""
利益計算用カラムをproductsとorder_settingsに追加するマイグレーション
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./china_import.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})

migrations = [
    ("products.selling_price",   "ALTER TABLE products ADD COLUMN selling_price FLOAT"),
    ("products.fba_fee",         "ALTER TABLE products ADD COLUMN fba_fee FLOAT"),
    ("products.amazon_fee_rate", "ALTER TABLE products ADD COLUMN amazon_fee_rate FLOAT DEFAULT 0.1"),
    ("products.fees_updated_at", "ALTER TABLE products ADD COLUMN fees_updated_at TIMESTAMP"),
    ("order_settings.exchange_rate", "ALTER TABLE order_settings ADD COLUMN exchange_rate FLOAT DEFAULT 21.0"),
]

with engine.connect() as conn:
    for name, sql in migrations:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"OK: {name}")
        except Exception as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print(f"SKIP (already exists): {name}")
            else:
                print(f"ERROR: {name} -> {e}")

print("Done.")
