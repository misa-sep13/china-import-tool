"""
rakuten_products に shipping_fee カラムを追加するマイグレーション
デフォルト: 180円（ネコポス税込）
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./china_import.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})

migrations = [
    ("rakuten_products.shipping_fee", "ALTER TABLE rakuten_products ADD COLUMN shipping_fee INTEGER DEFAULT 180"),
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
