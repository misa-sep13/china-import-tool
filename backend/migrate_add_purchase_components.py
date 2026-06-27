"""
rakuten_products に purchase_components カラムを追加するマイグレーション
発注・仕入れ用の付属品情報（在庫連動には使わない）
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./china_import.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})

migrations = [
    ("rakuten_products.purchase_components", "ALTER TABLE rakuten_products ADD COLUMN purchase_components TEXT"),
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
