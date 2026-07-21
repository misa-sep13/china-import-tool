"""
rakuten_products に show_in_orders カラムを追加するマイグレーション
発注管理（推奨リスト・全商品タブ）に表示するかどうかを is_component と独立して管理する。
既存データの初期値: is_component=True のSKUは show_in_orders=False、それ以外は True。
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./china_import.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE rakuten_products ADD COLUMN show_in_orders BOOLEAN DEFAULT TRUE"))
        conn.commit()
        print("OK: rakuten_products.show_in_orders added")
    except Exception as e:
        if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
            print("SKIP (already exists): rakuten_products.show_in_orders")
        else:
            raise

    result = conn.execute(text("SELECT COUNT(*) FROM rakuten_products WHERE is_component = TRUE"))
    count = result.scalar()
    print(f"is_component=True の対象件数: {count}")

    conn.execute(text("UPDATE rakuten_products SET show_in_orders = FALSE WHERE is_component = TRUE"))
    conn.commit()
    print(f"OK: show_in_orders = FALSE を {count} 件に設定")

print("Done.")
