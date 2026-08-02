"""
Amazon仕入管理（インボイス）を楽天と同等にするためのカラム追加マイグレーション。

- invoices        : 輸入許可書の税額情報。save_invoice がこれらを渡していたのに
                    テーブルに列が無く、保存すると TypeError になっていた
- invoice_items   : 申告欄ごとの税率で計算した結果（按分税・関税・欄番号）
- products        : cost_jpy（円建て原価）。従来は price（元単価）に円原価を
                    上書きしていたため、発注管理の単価表示が壊れる恐れがあった
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./china_import.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})

migrations = [
    # 輸入許可書から取得する税額（save_invoice が渡していたが列が無かった）
    ("invoices.customs_duty",          "ALTER TABLE invoices ADD COLUMN customs_duty INTEGER DEFAULT 0"),
    ("invoices.consumption_tax",       "ALTER TABLE invoices ADD COLUMN consumption_tax INTEGER DEFAULT 0"),
    ("invoices.local_consumption_tax", "ALTER TABLE invoices ADD COLUMN local_consumption_tax INTEGER DEFAULT 0"),
    ("invoices.total_tax",             "ALTER TABLE invoices ADD COLUMN total_tax INTEGER DEFAULT 0"),
    ("invoices.bl_number",             "ALTER TABLE invoices ADD COLUMN bl_number VARCHAR"),
    ("invoices.declaration_no",        "ALTER TABLE invoices ADD COLUMN declaration_no VARCHAR"),
    ("invoices.import_tax_jpy",        "ALTER TABLE invoices ADD COLUMN import_tax_jpy FLOAT DEFAULT 0"),

    # 明細ごとの税額内訳（税率別計算の結果）
    ("invoice_items.tax_alloc_jpy",    "ALTER TABLE invoice_items ADD COLUMN tax_alloc_jpy FLOAT DEFAULT 0"),
    ("invoice_items.duty_jpy",         "ALTER TABLE invoice_items ADD COLUMN duty_jpy FLOAT DEFAULT 0"),
    ("invoice_items.col_no",           "ALTER TABLE invoice_items ADD COLUMN col_no INTEGER"),
    ("invoice_items.tariff_rate",      "ALTER TABLE invoice_items ADD COLUMN tariff_rate FLOAT DEFAULT 0"),

    # 円建て原価（楽天のrakuten_products.cost_jpyと同じ役割）
    ("products.cost_jpy",              "ALTER TABLE products ADD COLUMN cost_jpy FLOAT"),
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
