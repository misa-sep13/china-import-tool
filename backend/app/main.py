from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import Base, engine
from app.api.routes import products, orders, settings, fba, invoices, price_adjustments, analytics, shipment_orders, fba_plan
from app.api.routes import inventory_snapshots
from app.api.routes import material_costs
from app.api.routes import cost_histories
from app.api.routes import amazon_research
from app.api.routes import scout
from app.api.routes import welfare
from app.api.routes import wholesale
from app.api.routes import rakuten
from app.api.routes import ads
from app.api.routes import review as review_routes
from app.api.routes import keyword_analysis as keyword_analysis_routes
from app.api.routes import seo as seo_routes
from app.api.routes import auth as auth_routes
from app.api.routes import activity_log as activity_log_routes
from app.api.routes import research as research_routes
from app.api.routes import product_drafts as product_draft_routes
from app.models import invoice as invoice_models
from app.models import order_history as order_history_models
from app.models import price_log as price_log_models
from app.models import rakuten_product as rakuten_product_models
from app.models import rakuten_order as rakuten_order_models
from app.models import rakuten_settings as rakuten_settings_models
from app.models import shipment_order as shipment_order_models
from app.models import inventory_reflection_log as inventory_reflection_log_models
from app.models import rakuten_ss_sales as rakuten_ss_sales_models
from app.models import rakuten_sales as rakuten_sales_models
from app.models import processed_order as processed_order_models
from app.models import welfare as welfare_models
from app.models import ads as ads_models
from app.models import review as review_models
from app.models import keyword_analysis as keyword_analysis_models
from app.models import seo as seo_models
from app.models import rakuten_daily_sales as rakuten_daily_sales_models
from app.models import rms_push_failure as rms_push_failure_models
from app.models import inventory_snapshot as inventory_snapshot_models
from app.models import material_cost as material_cost_models
from app.models import cost_history as cost_history_models
from app.models import amazon_research as amazon_research_models
from app.models import scout as scout_models
from app.models import activity_log as activity_log_models
from app.models import research as research_models
from app.models import wholesale as wholesale_models
from app.models import product_draft as product_draft_models

def _migrate():
    from sqlalchemy import text, inspect
    import logging
    logger = logging.getLogger("migrate")

    import app.models.inventory_event  # noqa: F401
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
        ("rakuten_products","purchase_components", "ALTER TABLE rakuten_products ADD COLUMN purchase_components TEXT"),
        ("rakuten_order_history","stage",          "ALTER TABLE rakuten_order_history ADD COLUMN stage INTEGER DEFAULT 1"),
        # 就労支援在庫 追加フィールド
        ("welfare_inventory_items","product_id",             "ALTER TABLE welfare_inventory_items ADD COLUMN product_id INTEGER"),
        ("welfare_inventory_items","sku",                    "ALTER TABLE welfare_inventory_items ADD COLUMN sku VARCHAR"),
        ("welfare_inventory_items","name_jp",                "ALTER TABLE welfare_inventory_items ADD COLUMN name_jp VARCHAR"),
        ("welfare_inventory_items","name_cn",                "ALTER TABLE welfare_inventory_items ADD COLUMN name_cn TEXT"),
        ("welfare_inventory_items","supplier_spec",          "ALTER TABLE welfare_inventory_items ADD COLUMN supplier_spec VARCHAR"),
        ("welfare_inventory_items","buy_url",                "ALTER TABLE welfare_inventory_items ADD COLUMN buy_url TEXT"),
        ("welfare_inventory_items","image_data_url",         "ALTER TABLE welfare_inventory_items ADD COLUMN image_data_url TEXT"),
        ("welfare_inventory_items","unit_per_set",           "ALTER TABLE welfare_inventory_items ADD COLUMN unit_per_set INTEGER DEFAULT 1"),
        ("welfare_inventory_items","total_received_units",   "ALTER TABLE welfare_inventory_items ADD COLUMN total_received_units INTEGER DEFAULT 0"),
        ("welfare_inventory_items","total_received_qty",     "ALTER TABLE welfare_inventory_items ADD COLUMN total_received_qty INTEGER DEFAULT 0"),
        ("welfare_inventory_items","withdrawn_qty",          "ALTER TABLE welfare_inventory_items ADD COLUMN withdrawn_qty INTEGER DEFAULT 0"),
        ("welfare_inventory_items","remaining_qty",          "ALTER TABLE welfare_inventory_items ADD COLUMN remaining_qty INTEGER DEFAULT 0"),
        ("welfare_inventory_items","instruction",            "ALTER TABLE welfare_inventory_items ADD COLUMN instruction TEXT"),
        ("welfare_inventory_items","note",                   "ALTER TABLE welfare_inventory_items ADD COLUMN note TEXT"),
        ("welfare_inventory_items","last_received_at",       "ALTER TABLE welfare_inventory_items ADD COLUMN last_received_at TIMESTAMP"),
        ("welfare_inventory_items","created_at",             "ALTER TABLE welfare_inventory_items ADD COLUMN created_at TIMESTAMP"),
        ("welfare_inventory_items","updated_at",             "ALTER TABLE welfare_inventory_items ADD COLUMN updated_at TIMESTAMP"),
        ("welfare_inventory_movements","item_id",            "ALTER TABLE welfare_inventory_movements ADD COLUMN item_id INTEGER"),
        ("welfare_inventory_movements","product_id",         "ALTER TABLE welfare_inventory_movements ADD COLUMN product_id INTEGER"),
        ("welfare_inventory_movements","sku",                "ALTER TABLE welfare_inventory_movements ADD COLUMN sku VARCHAR"),
        ("welfare_inventory_movements","movement_type",      "ALTER TABLE welfare_inventory_movements ADD COLUMN movement_type VARCHAR"),
        ("welfare_inventory_movements","source_file",        "ALTER TABLE welfare_inventory_movements ADD COLUMN source_file VARCHAR"),
        ("welfare_inventory_movements","source_sheet",       "ALTER TABLE welfare_inventory_movements ADD COLUMN source_sheet VARCHAR"),
        ("welfare_inventory_movements","source_order_no",    "ALTER TABLE welfare_inventory_movements ADD COLUMN source_order_no VARCHAR"),
        ("welfare_inventory_movements","name_cn",            "ALTER TABLE welfare_inventory_movements ADD COLUMN name_cn TEXT"),
        ("welfare_inventory_movements","supplier_spec",      "ALTER TABLE welfare_inventory_movements ADD COLUMN supplier_spec VARCHAR"),
        ("welfare_inventory_movements","buy_url",            "ALTER TABLE welfare_inventory_movements ADD COLUMN buy_url TEXT"),
        ("welfare_inventory_movements","units",              "ALTER TABLE welfare_inventory_movements ADD COLUMN units INTEGER DEFAULT 0"),
        ("welfare_inventory_movements","qty",                "ALTER TABLE welfare_inventory_movements ADD COLUMN qty INTEGER DEFAULT 0"),
        ("welfare_inventory_movements","note",               "ALTER TABLE welfare_inventory_movements ADD COLUMN note TEXT"),
        ("welfare_inventory_movements","created_at",         "ALTER TABLE welfare_inventory_movements ADD COLUMN created_at TIMESTAMP"),
        ("welfare_work_instructions","product_id",           "ALTER TABLE welfare_work_instructions ADD COLUMN product_id INTEGER"),
        ("welfare_work_instructions","sku",                  "ALTER TABLE welfare_work_instructions ADD COLUMN sku VARCHAR"),
        ("welfare_work_instructions","order_date",           "ALTER TABLE welfare_work_instructions ADD COLUMN order_date VARCHAR"),
        ("welfare_work_instructions","source_file",          "ALTER TABLE welfare_work_instructions ADD COLUMN source_file VARCHAR"),
        ("welfare_work_instructions","source_sheet",         "ALTER TABLE welfare_work_instructions ADD COLUMN source_sheet VARCHAR"),
        ("welfare_work_instructions","source_order_no",      "ALTER TABLE welfare_work_instructions ADD COLUMN source_order_no VARCHAR"),
        ("welfare_work_instructions","name_jp",              "ALTER TABLE welfare_work_instructions ADD COLUMN name_jp VARCHAR"),
        ("welfare_work_instructions","source_product_name",  "ALTER TABLE welfare_work_instructions ADD COLUMN source_product_name TEXT"),
        ("welfare_work_instructions","color",                "ALTER TABLE welfare_work_instructions ADD COLUMN color VARCHAR"),
        ("welfare_work_instructions","size",                 "ALTER TABLE welfare_work_instructions ADD COLUMN size VARCHAR"),
        ("welfare_work_instructions","supplier_spec",        "ALTER TABLE welfare_work_instructions ADD COLUMN supplier_spec VARCHAR"),
        ("welfare_work_instructions","buy_url",              "ALTER TABLE welfare_work_instructions ADD COLUMN buy_url TEXT"),
        ("welfare_work_instructions","image_data_url",       "ALTER TABLE welfare_work_instructions ADD COLUMN image_data_url TEXT"),
        ("welfare_work_instructions","unit_price",           "ALTER TABLE welfare_work_instructions ADD COLUMN unit_price VARCHAR"),
        ("welfare_work_instructions","units",                "ALTER TABLE welfare_work_instructions ADD COLUMN units INTEGER DEFAULT 0"),
        ("welfare_work_instructions","unit_per_set",         "ALTER TABLE welfare_work_instructions ADD COLUMN unit_per_set INTEGER DEFAULT 1"),
        ("welfare_work_instructions","qty",                  "ALTER TABLE welfare_work_instructions ADD COLUMN qty INTEGER DEFAULT 0"),
        ("welfare_work_instructions","instruction",          "ALTER TABLE welfare_work_instructions ADD COLUMN instruction TEXT"),
        ("welfare_work_instructions","remaining_units",      "ALTER TABLE welfare_work_instructions ADD COLUMN remaining_units INTEGER DEFAULT 0"),
        ("welfare_work_instructions","remaining_qty",        "ALTER TABLE welfare_work_instructions ADD COLUMN remaining_qty INTEGER DEFAULT 0"),
        ("welfare_work_instructions","note",                 "ALTER TABLE welfare_work_instructions ADD COLUMN note TEXT"),
        ("welfare_work_instructions","created_at",           "ALTER TABLE welfare_work_instructions ADD COLUMN created_at TIMESTAMP"),
        ("welfare_work_instructions","updated_at",           "ALTER TABLE welfare_work_instructions ADD COLUMN updated_at TIMESTAMP"),
        # インボイス：輸入許可書情報
        # Amazon商品マスタ：区分
        ("products",      "category",            "ALTER TABLE products ADD COLUMN category VARCHAR DEFAULT '標準'"),
        ("invoices","customs_duty",          "ALTER TABLE invoices ADD COLUMN customs_duty INTEGER DEFAULT 0"),
        ("invoices","consumption_tax",       "ALTER TABLE invoices ADD COLUMN consumption_tax INTEGER DEFAULT 0"),
        ("invoices","local_consumption_tax", "ALTER TABLE invoices ADD COLUMN local_consumption_tax INTEGER DEFAULT 0"),
        ("invoices","total_tax",             "ALTER TABLE invoices ADD COLUMN total_tax INTEGER DEFAULT 0"),
        ("invoices","bl_number",             "ALTER TABLE invoices ADD COLUMN bl_number VARCHAR"),
        ("invoices","declaration_no",        "ALTER TABLE invoices ADD COLUMN declaration_no VARCHAR"),
        ("invoices","import_tax_jpy",        "ALTER TABLE invoices ADD COLUMN import_tax_jpy FLOAT DEFAULT 0"),
        # インボイス明細：申告欄ごとの税率で計算した内訳
        ("invoice_items","tax_alloc_jpy",    "ALTER TABLE invoice_items ADD COLUMN tax_alloc_jpy FLOAT DEFAULT 0"),
        ("invoice_items","duty_jpy",         "ALTER TABLE invoice_items ADD COLUMN duty_jpy FLOAT DEFAULT 0"),
        ("invoice_items","col_no",           "ALTER TABLE invoice_items ADD COLUMN col_no INTEGER"),
        ("invoice_items","tariff_rate",      "ALTER TABLE invoice_items ADD COLUMN tariff_rate FLOAT DEFAULT 0"),
        # Amazon商品マスタ：円建て原価（priceは元単価のまま残す）
        ("products","cost_jpy",              "ALTER TABLE products ADD COLUMN cost_jpy FLOAT"),
        # Amazon商品マスタ：発注用付属品（楽天のpurchase_componentsと同じ役割）
        ("products","purchase_components",   "ALTER TABLE products ADD COLUMN purchase_components TEXT"),
        ("products","is_component",          "ALTER TABLE products ADD COLUMN is_component BOOLEAN DEFAULT FALSE"),
        # 発送用の梱包資材フラグ（宅配袋等）。商品原価には計上せず資材費として集計する
        ("products","is_material",           "ALTER TABLE products ADD COLUMN is_material BOOLEAN DEFAULT FALSE"),
        ("rakuten_products","is_material",   "ALTER TABLE rakuten_products ADD COLUMN is_material BOOLEAN DEFAULT FALSE"),
        # 前回スーパーセールの販売数（反映モードで発注数に上乗せする）
        ("rakuten_products","super_sale_qty", "ALTER TABLE rakuten_products ADD COLUMN super_sale_qty INTEGER DEFAULT 0"),
        # 通関料（船便のみ一律2000円）。輸入許可書には載らないので別枠で持つ
        ("material_costs","customs_fee_alloc_jpy",
         "ALTER TABLE material_costs ADD COLUMN customs_fee_alloc_jpy FLOAT DEFAULT 0"),
        ("invoice_items","customs_fee_alloc_jpy",
         "ALTER TABLE invoice_items ADD COLUMN customs_fee_alloc_jpy FLOAT DEFAULT 0"),
        ("invoices","customs_fee_jpy",
         "ALTER TABLE invoices ADD COLUMN customs_fee_jpy FLOAT DEFAULT 0"),
        # 売上管理：広告比率カラム
        ("rakuten_sales_summaries","ad_rate", "ALTER TABLE rakuten_sales_summaries ADD COLUMN ad_rate FLOAT"),
        # 売上管理：原価率（原価÷売上高）
        ("rakuten_sales_summaries","cost_rate", "ALTER TABLE rakuten_sales_summaries ADD COLUMN cost_rate FLOAT"),
        # レビューキャンペーン：判定キーワード
        ("review_campaigns","keywords", "ALTER TABLE review_campaigns ADD COLUMN keywords TEXT"),
        # キーワード分析：商品管理番号
        ("title_optimizations","manage_number", "ALTER TABLE title_optimizations ADD COLUMN manage_number VARCHAR"),
        # まとめ買い除外キャップ
        ("rakuten_settings","order_qty_cap", "ALTER TABLE rakuten_settings ADD COLUMN order_qty_cap INTEGER DEFAULT 3"),
        # 在庫切れフラグ
        ("rakuten_daily_sales","is_stockout", "ALTER TABLE rakuten_daily_sales ADD COLUMN is_stockout BOOLEAN DEFAULT FALSE"),
        ("order_settings","order_qty_cap", "ALTER TABLE order_settings ADD COLUMN order_qty_cap INTEGER DEFAULT 3"),
        # リサーチ候補：前回バッチ時点のレビュー数（伸びを出すために引き継ぐ）
        ("research_candidates","prev_review_count",
         "ALTER TABLE research_candidates ADD COLUMN prev_review_count INTEGER"),
        ("research_candidates","prev_fetched_at",
         "ALTER TABLE research_candidates ADD COLUMN prev_fetched_at TIMESTAMP"),
        # Nintの売上データと突き合わせるキー（商品URL由来の "ショップ名/商品コード"）
        ("research_candidates","url_key",
         "ALTER TABLE research_candidates ADD COLUMN url_key VARCHAR"),
        ("research_watchlist_items","url_key",
         "ALTER TABLE research_watchlist_items ADD COLUMN url_key VARCHAR"),
        # FBA納品プラン用リードタイム詳細
        ("order_settings","lt_order_to_warehouse", "ALTER TABLE order_settings ADD COLUMN lt_order_to_warehouse INTEGER DEFAULT 7"),
        ("order_settings","lt_shipping_request", "ALTER TABLE order_settings ADD COLUMN lt_shipping_request INTEGER DEFAULT 7"),
        ("order_settings","lt_sea_to_fba", "ALTER TABLE order_settings ADD COLUMN lt_sea_to_fba INTEGER DEFAULT 18"),
        ("order_settings","lt_air_to_fba", "ALTER TABLE order_settings ADD COLUMN lt_air_to_fba INTEGER DEFAULT 10"),
        ("order_settings","free_storage_days", "ALTER TABLE order_settings ADD COLUMN free_storage_days INTEGER DEFAULT 90"),
        ("order_settings","air_threshold_days", "ALTER TABLE order_settings ADD COLUMN air_threshold_days INTEGER DEFAULT 18"),
        ("order_settings","hold_daily_threshold", "ALTER TABLE order_settings ADD COLUMN hold_daily_threshold FLOAT DEFAULT 0.1"),
        # 配送依頼明細の在庫反映済みフラグ（未反映分だけ再取込するため）
        ("shipment_order_items","is_reflected", "ALTER TABLE shipment_order_items ADD COLUMN is_reflected BOOLEAN DEFAULT FALSE"),
        # 配送依頼明細の対象外フラグ（梱包材など在庫に入れる必要がない行を未反映カウントから除外）
        ("shipment_order_items","is_excluded", "ALTER TABLE shipment_order_items ADD COLUMN is_excluded BOOLEAN DEFAULT FALSE"),
        # 発注履歴ステータス管理
        ("order_history","status",            "ALTER TABLE order_history ADD COLUMN status VARCHAR DEFAULT 'ordered'"),
        ("order_history","arrived_at",        "ALTER TABLE order_history ADD COLUMN arrived_at TIMESTAMP"),
        ("order_history","taotaro_order_id",  "ALTER TABLE order_history ADD COLUMN taotaro_order_id VARCHAR"),
        # 就労支援荷受けの在庫反映済みフラグ（荷受け処理後に残の数量だけ在庫化するため）
        ("welfare_work_instructions","is_reflected", "ALTER TABLE welfare_work_instructions ADD COLUMN is_reflected BOOLEAN DEFAULT FALSE"),
        ("welfare_work_instructions","reflected_at", "ALTER TABLE welfare_work_instructions ADD COLUMN reflected_at TIMESTAMP WITH TIME ZONE"),
        ("welfare_work_instructions","shipment_no", "ALTER TABLE welfare_work_instructions ADD COLUMN shipment_no VARCHAR"),
        ("welfare_inventory_movements","shipment_no", "ALTER TABLE welfare_inventory_movements ADD COLUMN shipment_no VARCHAR"),
        ("scout_baskets","register_requested_at", "ALTER TABLE scout_baskets ADD COLUMN register_requested_at TIMESTAMP WITH TIME ZONE"),
        ("scout_crawl_requests","kind", "ALTER TABLE scout_crawl_requests ADD COLUMN kind VARCHAR DEFAULT 'crawl'"),
        ("amazon_research_settings","gs1_prefix", "ALTER TABLE amazon_research_settings ADD COLUMN gs1_prefix VARCHAR"),
        ("amazon_research_settings","brand_name", "ALTER TABLE amazon_research_settings ADD COLUMN brand_name VARCHAR"),
        # 販促品／レビュー特典フラグ。楽天に出品していないのでRMS push・発注推奨・
        # 在庫一覧の対象外にするが、就労支援在庫の数量把握のためマスタ登録は可能にする
        ("rakuten_products","is_promo", "ALTER TABLE rakuten_products ADD COLUMN is_promo BOOLEAN DEFAULT FALSE"),
        # 再梱包の作業依頼が、どの作業マスタから作られたか
        ("welfare_packing_orders","task_id",
         "ALTER TABLE welfare_packing_orders ADD COLUMN task_id INTEGER"),
        # 作業マスタの出所（seed=一括取り込み / manual=手で追加）
        ("welfare_packing_tasks","source",
         "ALTER TABLE welfare_packing_tasks ADD COLUMN source VARCHAR DEFAULT 'manual'"),
        # どの便の荷受けから作った依頼か（同じ便からの二重作成を防ぐ）
        ("welfare_packing_orders","source_batch",
         "ALTER TABLE welfare_packing_orders ADD COLUMN source_batch VARCHAR"),

        # 卸発注の入荷。create_all は既にある表に列を足さないので、ここで足す
        ("wholesale_orders","received_at",
         "ALTER TABLE wholesale_orders ADD COLUMN received_at TIMESTAMP"),
        ("wholesale_orders","received_mode",
         "ALTER TABLE wholesale_orders ADD COLUMN received_mode VARCHAR"),
        ("wholesale_orders","inbound_applied",
         "ALTER TABLE wholesale_orders ADD COLUMN inbound_applied BOOLEAN DEFAULT FALSE"),
        ("wholesale_order_items","received_qty",
         "ALTER TABLE wholesale_order_items ADD COLUMN received_qty INTEGER DEFAULT 0"),
        ("wholesale_suppliers","order_method",
         "ALTER TABLE wholesale_suppliers ADD COLUMN order_method VARCHAR DEFAULT 'excel_mail'"),
        ("wholesale_orders","message_text",
         "ALTER TABLE wholesale_orders ADD COLUMN message_text TEXT"),
        ("product_drafts","registered_at",
         "ALTER TABLE product_drafts ADD COLUMN registered_at TIMESTAMP"),
        ("product_drafts","register_error",
         "ALTER TABLE product_drafts ADD COLUMN register_error TEXT"),
        ("product_drafts","register_log",
         "ALTER TABLE product_drafts ADD COLUMN register_log TEXT"),
        ("product_drafts","variant_axis",
         "ALTER TABLE product_drafts ADD COLUMN variant_axis VARCHAR"),
        ("product_drafts","variants",
         "ALTER TABLE product_drafts ADD COLUMN variants TEXT"),
        ("product_drafts","image_urls",
         "ALTER TABLE product_drafts ADD COLUMN image_urls TEXT"),
        ("product_drafts","features",
         "ALTER TABLE product_drafts ADD COLUMN features TEXT"),
        ("product_drafts","spec_rows",
         "ALTER TABLE product_drafts ADD COLUMN spec_rows TEXT"),
        ("product_drafts","seo_words",
         "ALTER TABLE product_drafts ADD COLUMN seo_words TEXT"),
        ("product_drafts","product_notes",
         "ALTER TABLE product_drafts ADD COLUMN product_notes TEXT"),
        ("product_drafts","template_sku",
         "ALTER TABLE product_drafts ADD COLUMN template_sku VARCHAR"),
        ("product_drafts","variant_axis2",
         "ALTER TABLE product_drafts ADD COLUMN variant_axis2 VARCHAR"),
        ("product_drafts","series_name",
         "ALTER TABLE product_drafts ADD COLUMN series_name VARCHAR"),
        ("product_drafts","item_specs",
         "ALTER TABLE product_drafts ADD COLUMN item_specs TEXT"),
        ("product_drafts","shipping_set",
         "ALTER TABLE product_drafts ADD COLUMN shipping_set VARCHAR"),
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
                # 既存の入荷済み配送依頼は反映済みとして埋める。
                # （どの行が実際に反映されたかは遡れないため、二重加算しない側に倒す）
                # 既存の荷受け行は取込時に在庫加算済みなので反映済みとして埋める
                # （新しい取込分だけが「未反映」になり、反映ボタンの対象になる）
                if table == "welfare_work_instructions" and col == "is_reflected":
                    with engine.begin() as conn:
                        conn.execute(text("UPDATE welfare_work_instructions SET is_reflected = TRUE"))
                    logger.info("migrate: backfilled welfare_work_instructions.is_reflected")
                if table == "shipment_order_items" and col == "is_reflected":
                    with engine.begin() as conn:
                        conn.execute(text(
                            "UPDATE shipment_order_items SET is_reflected = TRUE "
                            "WHERE product_id IS NOT NULL AND shipment_order_id IN "
                            "(SELECT id FROM shipment_orders WHERE status = 'received')"
                        ))
                    logger.info("migrate: backfilled shipment_order_items.is_reflected for received orders")
            except Exception as e:
                logger.warning(f"migrate: {table}.{col} -> {e}")

    # 配送依頼明細のproduct_idは楽天商品マスタ(rakuten_products.id)を指す。
    # 初期実装でAmazon商品マスタ(products.id)へのFKとして作られたDBでは、
    # 入荷反映時に楽天product_idを保存できず500になるため、PostgreSQLでは制約を修正する。
    try:
        fks = inspector.get_foreign_keys("shipment_order_items")
        wrong_fks = [
            fk for fk in fks
            if "product_id" in (fk.get("constrained_columns") or [])
            and fk.get("referred_table") == "products"
        ]
        has_rakuten_fk = any(
            "product_id" in (fk.get("constrained_columns") or [])
            and fk.get("referred_table") == "rakuten_products"
            for fk in fks
        )
        if wrong_fks and engine.dialect.name == "postgresql":
            preparer = engine.dialect.identifier_preparer
            with engine.begin() as conn:
                for fk in wrong_fks:
                    name = fk.get("name")
                    if name:
                        conn.execute(text(
                            f"ALTER TABLE shipment_order_items DROP CONSTRAINT IF EXISTS {preparer.quote(name)}"
                        ))
                if not has_rakuten_fk:
                    conn.execute(text(
                        "ALTER TABLE shipment_order_items "
                        "ADD CONSTRAINT shipment_order_items_product_id_rakuten_fkey "
                        "FOREIGN KEY (product_id) REFERENCES rakuten_products(id)"
                    ))
            logger.info("migrate: fixed shipment_order_items.product_id FK to rakuten_products.id")
    except Exception as e:
        logger.warning(f"migrate: shipment_order_items.product_id FK fix -> {e}")

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


def _save_inventory_event(db, *, event_type: str, event_time,
                          order_numbers=None, sold=None, changed=None,
                          recalculated=None, pushed=None, push_ok=None,
                          push_fail=None, errors=None,
                          stock_before=None, stock_after=None):
    import json as _j
    from app.models.inventory_event import InventoryEvent
    try:
        if hasattr(event_time, 'tzinfo') and event_time.tzinfo is not None:
            event_time = event_time.replace(tzinfo=None)
        db.add(InventoryEvent(
            event_time=event_time,
            event_type=event_type,
            order_numbers=_j.dumps(order_numbers, ensure_ascii=False) if order_numbers else None,
            sold=_j.dumps(sold, ensure_ascii=False) if sold else None,
            changed=_j.dumps(changed, ensure_ascii=False) if changed else None,
            recalculated=_j.dumps(recalculated, ensure_ascii=False) if recalculated else None,
            pushed=_j.dumps(pushed, ensure_ascii=False) if pushed else None,
            push_ok=push_ok,
            push_fail=push_fail,
            errors=_j.dumps(errors, ensure_ascii=False) if errors else None,
            stock_before=_j.dumps(stock_before, ensure_ascii=False) if stock_before else None,
            stock_after=_j.dumps(stock_after, ensure_ascii=False) if stock_after else None,
        ))
        db.commit()
    except Exception as e:
        logger.warning(f"[inventory_event] DB保存失敗: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def _load_processed_orders(db) -> dict[str, str]:
    """DBから処理済み注文を読み込む"""
    from app.models.processed_order import ProcessedOrder
    rows = db.query(ProcessedOrder).all()
    return {r.order_number: r.state for r in rows}


def _save_processed_order(db, order_number: str, state: str):
    """DBに処理済み注文を保存/更新"""
    from app.models.processed_order import ProcessedOrder
    existing = db.query(ProcessedOrder).filter(ProcessedOrder.order_number == order_number).first()
    if existing:
        existing.state = state
    else:
        db.add(ProcessedOrder(order_number=order_number, state=state))


def _cleanup_old_processed_orders(db, keep_days=7):
    """古い処理済み注文を削除。active注文はkeep_days日間保持、cancelledは30日超で削除"""
    from app.models.processed_order import ProcessedOrder
    cutoff_cancelled = dt.now(JST) - timedelta(days=30)
    cutoff_active = dt.now(JST) - timedelta(days=keep_days)
    db.query(ProcessedOrder).filter(
        ProcessedOrder.state == "cancelled",
        ProcessedOrder.updated_at < cutoff_cancelled,
    ).delete(synchronize_session=False)
    db.query(ProcessedOrder).filter(
        ProcessedOrder.state == "active",
        ProcessedOrder.updated_at < cutoff_active,
    ).delete(synchronize_session=False)

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
    処理済み注文はDBに永続化（再起動時の二重減算を防止）。
    RMS_PUSH_ENABLED=trueの場合、在庫変更をRMSにpushする。"""
    from app.core.database import SessionLocal
    from app.models.rakuten_settings import RakutenSettings
    from app.models.rakuten_product import RakutenProduct
    from app.services.rakuten_rms import fetch_recent_orders, push_inventory_to_rms, calc_set_avail, build_component_share_counts
    import json as _json

    db = SessionLocal()
    try:
        settings = db.query(RakutenSettings).first()
        if not settings or not settings.rms_service_secret or not settings.rms_license_key:
            return

        orders_by_num, order_nums, cancelled_nums = await fetch_recent_orders(
            settings.rms_service_secret, settings.rms_license_key, minutes=15
        )
        if not order_nums:
            return

        processed_orders = _load_processed_orders(db)

        new_sold: dict[str, int] = {}
        new_cancelled: dict[str, int] = {}
        processed_new = 0
        skipped_processed = 0

        for n in order_nums:
            prev_state = processed_orders.get(n)
            is_cancelled = n in cancelled_nums
            cur_state = "cancelled" if is_cancelled else "active"

            if prev_state == cur_state:
                skipped_processed += 1
                continue

            skus = orders_by_num.get(n) or {}
            if not skus:
                continue

            if prev_state is None and cur_state == "active":
                for sku, qty in skus.items():
                    new_sold[sku] = new_sold.get(sku, 0) + qty
            elif prev_state is None and cur_state == "cancelled":
                pass
            elif prev_state == "active" and cur_state == "cancelled":
                for sku, qty in skus.items():
                    new_cancelled[sku] = new_cancelled.get(sku, 0) + qty

            _save_processed_order(db, n, cur_state)
            processed_new += 1

        _cleanup_old_processed_orders(db)

        if not new_sold and not new_cancelled:
            if processed_new > 0:
                db.commit()
            _sync_logs.appendleft({
                "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
                "type": "sync",
                "searched_orders": len(order_nums),
                "skipped_processed": skipped_processed,
                "processed_new": processed_new,
                "note": "在庫変動なし" if processed_new == 0 else f"受注{processed_new}件処理（在庫変動なし）",
            })
            return

        all_products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
        sku_to_product = {p.sku: p for p in all_products}
        sku_stock = {p.sku: (p.stock or 0) for p in all_products}
        sku_stock_before = dict(sku_stock)

        def parse_comps(p):
            try:
                return _json.loads(p.set_components or "[]")
            except Exception:
                return []

        updated_skus = set()
        oversold: dict[str, int] = {}  # 在庫が足りず0で頭打ちになった不足数（売り越し）
        for sku, qty in new_sold.items():
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
                        if cp.stock < c_qty:
                            oversold[c_sku] = oversold.get(c_sku, 0) + (c_qty - cp.stock)
                        cp.stock = max(0, cp.stock - c_qty)
                        sku_stock[c_sku] = cp.stock
                        updated_skus.add(c_sku)
            else:
                if p.stock is not None:
                    if p.stock < qty:
                        oversold[sku] = oversold.get(sku, 0) + (qty - p.stock)
                    p.stock = max(0, p.stock - qty)
                    sku_stock[sku] = p.stock
                    updated_skus.add(sku)

        cancel_skipped = {}
        for sku, qty in new_cancelled.items():
            p = sku_to_product.get(sku)
            if not p:
                continue
            comps = parse_comps(p)
            if comps:
                all_zero = all(
                    (sku_to_product.get(c.get("sku")) or p).stock in (None, 0)
                    for c in comps
                )
                if all_zero:
                    cancel_skipped[sku] = qty
                    continue
                for c in comps:
                    c_sku = c.get("sku")
                    c_qty = (c.get("qty") or 1) * qty
                    cp = sku_to_product.get(c_sku)
                    if cp and cp.stock is not None:
                        if cp.stock == 0:
                            cancel_skipped[c_sku] = cancel_skipped.get(c_sku, 0) + c_qty
                            continue
                        cp.stock = cp.stock + c_qty
                        sku_stock[c_sku] = cp.stock
                        updated_skus.add(c_sku)
            else:
                if p.stock is not None:
                    if p.stock == 0:
                        cancel_skipped[sku] = qty
                        continue
                    p.stock = p.stock + qty
                    sku_stock[sku] = p.stock
                    updated_skus.add(sku)
        if cancel_skipped:
            logger.info(f"[scheduler] キャンセル戻しスキップ(在庫0): {cancel_skipped}")

        share_counts = build_component_share_counts(all_products)
        updated_set_skus = set()
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
                avail = calc_set_avail(sku_stock.get(c_sku, 0), c_qty, share_counts.get(c_sku, 0))
                set_qty = avail if set_qty is None else min(set_qty, avail)
            if set_qty is not None:
                p.stock = set_qty
                sku_stock[p.sku] = set_qty
                updated_set_skus.add(p.sku)

        db.commit()

        # RMS_PUSH_ENABLED=trueの場合、変更されたSKUの在庫をRMSにpush
        push_result = None
        all_changed = updated_skus | updated_set_skus
        if all_changed:
            import re as _re
            push_items = []
            for sku in all_changed:
                p = sku_to_product.get(sku)
                if not p:
                    continue
                if p.is_component and not p.rakuten_item_url:
                    continue
                s = (p.sku or "").strip()
                if not s or not _re.match(r'^[a-zA-Z0-9_\-]+$', s):
                    continue
                manage_number = (p.rakuten_item_url or s.split("_")[0]).strip()
                if not manage_number:
                    continue
                push_items.append({
                    "manage_number": manage_number,
                    "variant_id": s,
                    "quantity": p.stock or 0,
                })
            if push_items:
                try:
                    push_result = await push_inventory_to_rms(
                        settings.rms_service_secret, settings.rms_license_key, push_items
                    )
                    logger.info(f"[scheduler] push結果: {push_result}")
                except Exception as pe:
                    push_result = {"ok": 0, "fail": len(push_items), "errors": [{"sku": "all", "detail": str(pe)}], "details": []}
                    logger.warning(f"[scheduler] push失敗: {pe}")

        log_entry = {
            "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            "type": "sync",
            "searched_orders": len(order_nums),
            "skipped_processed": skipped_processed,
            "processed_new": processed_new,
            "sold": new_sold if new_sold else None,
            "cancelled": new_cancelled if new_cancelled else None,
            "updated_skus": list(updated_skus),
            "updated_sets": list(updated_set_skus),
        }
        if oversold:
            log_entry["oversold"] = oversold
            logger.warning(f"[scheduler] 売り越し検知: 在庫不足のまま受注 {oversold}")
        if push_result:
            log_entry["push"] = {
                "ok": push_result.get("ok", 0),
                "fail": push_result.get("fail", 0),
                "targets": push_result.get("details", []),
                "errors": push_result.get("errors", []),
            }
        if not new_sold and not new_cancelled and not updated_skus:
            log_entry["note"] = "在庫変動なし"
        _sync_logs.appendleft(log_entry)
        logger.info(f"[scheduler] 在庫更新: sold={new_sold} cancelled={new_cancelled} updated={updated_skus} sets={updated_set_skus}")

        if new_sold or new_cancelled:
            ev_time = dt.now(JST)
            sold_order_nums = [n for n in order_nums if n not in cancelled_nums and processed_orders.get(n) is None]
            cancel_order_nums = [n for n in order_nums if n in cancelled_nums and processed_orders.get(n) == "active"]
            order_nums_list = sold_order_nums + cancel_order_nums
            changed = {}
            if new_sold:
                for s, q in new_sold.items():
                    changed[s] = changed.get(s, 0) - q
            if new_cancelled:
                for s, q in new_cancelled.items():
                    changed[s] = changed.get(s, 0) + q
            recalc = {s: sku_stock.get(s, 0) for s in updated_set_skus} if updated_set_skus else None
            pushed_list = None
            push_errors = None
            p_ok = None
            p_fail = None
            if push_result:
                pushed_list = push_result.get("details", [])
                push_errors = push_result.get("errors", []) or None
                p_ok = push_result.get("ok", 0)
                p_fail = push_result.get("fail", 0)
            if oversold:
                push_errors = (push_errors or []) + [
                    {"sku": s, "detail": f"売り越し: 在庫不足{q}個分の受注（0で頭打ち）"}
                    for s, q in oversold.items()
                ]
            sb = {s: sku_stock_before[s] for s in all_changed if s in sku_stock_before}
            sa = {s: sku_stock.get(s, 0) for s in all_changed}
            evt = "order_sold" if new_sold else "cancel_restore"
            _save_inventory_event(
                db, event_type=evt, event_time=ev_time,
                order_numbers=order_nums_list or None,
                sold=new_sold or None, changed=changed or None,
                recalculated=recalc, pushed=pushed_list,
                push_ok=p_ok, push_fail=p_fail, errors=push_errors,
                stock_before=sb or None, stock_after=sa or None,
            )
    except Exception as e:
        _sync_logs.appendleft({"time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"), "error": str(e)})
        logger.warning(f"[scheduler] 在庫同期エラー: {e}")
    finally:
        db.close()


async def _check_delayed_cancellations():
    """30分ごと: DB内のactive注文をRMSで再確認し、遅延キャンセルを検出して在庫を戻す"""
    from app.core.database import SessionLocal
    from app.models.rakuten_settings import RakutenSettings
    from app.models.rakuten_product import RakutenProduct
    from app.models.processed_order import ProcessedOrder
    from app.services.rakuten_rms import push_inventory_to_rms, calc_set_avail, build_component_share_counts
    import json as _json
    import httpx

    db = SessionLocal()
    try:
        settings = db.query(RakutenSettings).first()
        if not settings or not settings.rms_service_secret or not settings.rms_license_key:
            return

        active_orders = db.query(ProcessedOrder).filter(ProcessedOrder.state == "active").all()
        if not active_orders:
            return

        from app.services.rakuten_rms import _auth_header, RMS_BASE
        import json
        headers = {**_auth_header(settings.rms_service_secret, settings.rms_license_key),
                   "Content-Type": "application/json; charset=utf-8"}

        order_numbers = [o.order_number for o in active_orders]
        BATCH = 100
        newly_cancelled: dict[str, dict[str, int]] = {}

        for i in range(0, len(order_numbers), BATCH):
            batch = order_numbers[i:i + BATCH]
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    res = await client.post(
                        f"{RMS_BASE}/2.0/order/getOrder",
                        headers=headers,
                        content=json.dumps({"orderNumberList": batch, "version": 10}, ensure_ascii=False).encode("utf-8"),
                    )
                    if not res.is_success:
                        continue
                    detail = res.json()
                for order in detail.get("OrderModelList", []):
                    order_num = str(order.get("orderNumber") or "")
                    if order.get("orderProgress", 0) != 900:
                        continue
                    sku_map: dict[str, int] = {}
                    for package in order.get("PackageModelList", []):
                        for item in package.get("ItemModelList", []):
                            qty = item.get("units", 1) or 1
                            sku_list = item.get("SkuModelList") or []
                            skus = [s.get("variantId", "") for s in sku_list if s.get("variantId")]
                            if not skus:
                                skus = [item.get("manageNumber", "") or item.get("itemNumber", "")]
                            for sku in skus:
                                if sku:
                                    sku_map[sku] = sku_map.get(sku, 0) + qty
                    if order_num and sku_map:
                        newly_cancelled[order_num] = sku_map
            except Exception as e:
                logger.warning(f"[scheduler] キャンセル再チェックAPI失敗: {e}")
                continue

        if not newly_cancelled:
            return

        all_products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
        sku_to_product = {p.sku: p for p in all_products}
        sku_stock = {p.sku: (p.stock or 0) for p in all_products}
        sku_stock_before = dict(sku_stock)

        def parse_comps(p):
            try:
                return _json.loads(p.set_components or "[]")
            except Exception:
                return []

        updated_skus = set()
        cancel_skipped = {}
        for order_num, sku_map in newly_cancelled.items():
            for sku, qty in sku_map.items():
                p = sku_to_product.get(sku)
                if not p:
                    continue
                comps = parse_comps(p)
                if comps:
                    all_zero = all(
                        (sku_to_product.get(c.get("sku")) or p).stock in (None, 0)
                        for c in comps
                    )
                    if all_zero:
                        cancel_skipped[sku] = cancel_skipped.get(sku, 0) + qty
                    else:
                        for c in comps:
                            c_sku = c.get("sku")
                            c_qty = (c.get("qty") or 1) * qty
                            cp = sku_to_product.get(c_sku)
                            if cp and cp.stock is not None:
                                if cp.stock == 0:
                                    cancel_skipped[c_sku] = cancel_skipped.get(c_sku, 0) + c_qty
                                    continue
                                cp.stock = cp.stock + c_qty
                                sku_stock[c_sku] = cp.stock
                                updated_skus.add(c_sku)
                else:
                    if p.stock is not None:
                        if p.stock == 0:
                            cancel_skipped[sku] = cancel_skipped.get(sku, 0) + qty
                        else:
                            p.stock = p.stock + qty
                            sku_stock[sku] = p.stock
                            updated_skus.add(sku)

            _save_processed_order(db, order_num, "cancelled")
        if cancel_skipped:
            logger.info(f"[scheduler] 遅延キャンセル戻しスキップ(在庫0): {cancel_skipped}")

        share_counts = build_component_share_counts(all_products)
        updated_set_skus = set()
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
                avail = calc_set_avail(sku_stock.get(c_sku, 0), c_qty, share_counts.get(c_sku, 0))
                set_qty = avail if set_qty is None else min(set_qty, avail)
            if set_qty is not None:
                p.stock = set_qty
                sku_stock[p.sku] = set_qty
                updated_set_skus.add(p.sku)

        db.commit()

        push_result = None
        all_changed = updated_skus | updated_set_skus
        if all_changed:
            import re as _re
            push_items = []
            for sku in all_changed:
                p = sku_to_product.get(sku)
                if not p:
                    continue
                if p.is_component and not p.rakuten_item_url:
                    continue
                s = (p.sku or "").strip()
                if not s or not _re.match(r'^[a-zA-Z0-9_\-]+$', s):
                    continue
                manage_number = (p.rakuten_item_url or s.split("_")[0]).strip()
                if not manage_number:
                    continue
                push_items.append({
                    "manage_number": manage_number,
                    "variant_id": s,
                    "quantity": p.stock or 0,
                })
            if push_items:
                try:
                    push_result = await push_inventory_to_rms(
                        settings.rms_service_secret, settings.rms_license_key, push_items
                    )
                    logger.info(f"[scheduler] キャンセル戻しpush結果: {push_result}")
                except Exception as pe:
                    push_result = {"ok": 0, "fail": len(push_items), "errors": [{"sku": "all", "detail": str(pe)}], "details": []}
                    logger.warning(f"[scheduler] キャンセル戻しpush失敗: {pe}")

        cancelled_nums = list(newly_cancelled.keys())
        log_entry = {
            "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            "type": "delayed_cancellation",
            "cancelled_orders": cancelled_nums,
            "updated_skus": list(updated_skus),
        }
        if push_result:
            log_entry["push"] = {
                "ok": push_result.get("ok", 0),
                "fail": push_result.get("fail", 0),
                "targets": push_result.get("details", []),
                "errors": push_result.get("errors", []),
            }
        _sync_logs.appendleft(log_entry)
        logger.info(f"[scheduler] 遅延キャンセル検出: {len(cancelled_nums)}件 updated={updated_skus}")

        cancel_changed = {}
        for order_num, sku_map in newly_cancelled.items():
            for sku, qty in sku_map.items():
                cancel_changed[sku] = cancel_changed.get(sku, 0) + qty
        recalc = {s: sku_stock.get(s, 0) for s in updated_set_skus} if updated_set_skus else None
        pushed_list = None
        push_errors = None
        p_ok = None
        p_fail = None
        if push_result:
            pushed_list = push_result.get("details", [])
            push_errors = push_result.get("errors", []) or None
            p_ok = push_result.get("ok", 0)
            p_fail = push_result.get("fail", 0)
        sb = {s: sku_stock_before[s] for s in all_changed if s in sku_stock_before}
        sa = {s: sku_stock.get(s, 0) for s in all_changed}
        _save_inventory_event(
            db, event_type="cancel_restore", event_time=dt.now(JST),
            order_numbers=cancelled_nums,
            changed=cancel_changed or None,
            recalculated=recalc, pushed=pushed_list,
            push_ok=p_ok, push_fail=p_fail, errors=push_errors,
            stock_before=sb or None, stock_after=sa or None,
        )
    except Exception as e:
        logger.warning(f"[scheduler] キャンセル再チェックエラー: {e}")
    finally:
        db.close()


async def _pull_rms_stock():
    """RMSから在庫数を取得してDBに上書き。
    ただし「セットの構成品になっている単品SKU」はpullで上書きしない。
    単品在庫はツールが受注減算で管理し、セット在庫は楽天から取得する。"""
    from app.core.database import SessionLocal
    from app.models.rakuten_settings import RakutenSettings
    from app.models.rakuten_product import RakutenProduct
    from app.services.rakuten_rms import fetch_inventory_from_rms, calc_set_avail, build_component_share_counts

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

        # セット商品ごとに「単品プール在庫から計算した上限値」を求める。
        # push失敗(429等)でRMSに古い大きな在庫が残ると、その分だけ実在庫以上に
        # 売れてしまう（売り越し）。pullのたびに上限超過を検出して矯正pushする。
        import json as _json2
        share_counts = build_component_share_counts(products)
        pool_expected: dict[str, int] = {}
        for p in products:
            try:
                comps = _json2.loads(p.set_components or "[]")
            except Exception:
                comps = []
            if not comps:
                continue
            req: dict[str, int] = {}
            for c in comps:
                c_sku = c.get("sku")
                c_qty = c.get("qty") or 1
                if c_sku:
                    req[c_sku] = req.get(c_sku, 0) + c_qty
            expected = None
            for c_sku, c_qty in req.items():
                cp = sku_to_product.get(c_sku)
                if cp is None:
                    expected = None
                    break
                avail = calc_set_avail(cp.stock or 0, c_qty, share_counts.get(c_sku, 0))
                expected = avail if expected is None else min(expected, avail)
            if expected is not None:
                pool_expected[p.sku] = expected

        updated = 0
        skipped = 0
        corrections: dict[str, dict] = {}
        for sku, qty in rms_stock.items():
            p = sku_to_product.get(sku)
            if not p:
                continue
            # セットの構成品になっている単品はpullで上書きしない（受注減算で管理）
            if sku in component_parent_skus:
                skipped += 1
                continue
            expected = pool_expected.get(sku)
            if expected is not None and qty > expected:
                # RMSが単品プールの上限を超えている → DBは上限値にし、RMSへ矯正push
                p.stock = expected
                corrections[sku] = {"rms": qty, "corrected_to": expected}
            else:
                p.stock = qty
            updated += 1

        db.commit()

        push_result = None
        if corrections:
            from app.services.rakuten_rms import push_inventory_to_rms
            push_items = []
            for sku in corrections:
                p = sku_to_product.get(sku)
                manage_number = (p.rakuten_item_url or sku.split("_")[0]).strip()
                push_items.append({
                    "manage_number": manage_number,
                    "variant_id": sku,
                    "quantity": p.stock or 0,
                })
            try:
                push_result = await push_inventory_to_rms(
                    settings.rms_service_secret, settings.rms_license_key, push_items
                )
                logger.warning(f"[scheduler] RMS在庫の上限超過を矯正push: {corrections} 結果={push_result}")
            except Exception as pe:
                push_result = {"ok": 0, "fail": len(push_items), "errors": [{"sku": "all", "detail": str(pe)}]}
                logger.warning(f"[scheduler] 矯正push失敗: {pe}")
            _save_inventory_event(
                db, event_type="reconcile_push", event_time=dt.now(JST),
                changed={s: v["corrected_to"] - v["rms"] for s, v in corrections.items()},
                recalculated={s: v["corrected_to"] for s, v in corrections.items()},
                pushed=push_result.get("details") if push_result else None,
                push_ok=push_result.get("ok") if push_result else None,
                push_fail=push_result.get("fail") if push_result else None,
                errors=push_result.get("errors") or None if push_result else None,
                stock_before={s: v["rms"] for s, v in corrections.items()},
                stock_after={s: v["corrected_to"] for s, v in corrections.items()},
            )

        logger.info(f"[scheduler] RMS在庫取得完了: {updated}件更新, {skipped}件スキップ(単品管理)")
        log_entry = {
            "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            "type": "rms_stock",
            "updated": updated,
            "sent": len(items),
            "skipped_component_parents": skipped,
        }
        if corrections:
            log_entry["reconciled"] = corrections
            if push_result:
                log_entry["push"] = {"ok": push_result.get("ok", 0), "fail": push_result.get("fail", 0)}
        _sync_logs.appendleft(log_entry)
    except Exception as e:
        logger.warning(f"[scheduler] RMS在庫取得エラー: {e}")
        _sync_logs.appendleft({
            "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            "type": "rms_stock",
            "error": str(e),
        })
    finally:
        db.close()


async def _seed_processed_orders():
    """初回起動時: processed_ordersが空なら過去7日分の注文を在庫操作なしでseedする。
    これにより既に旧プロセスで処理済みの注文を二重減算しない。"""
    from app.core.database import SessionLocal
    from app.models.rakuten_settings import RakutenSettings
    from app.models.processed_order import ProcessedOrder
    from app.services.rakuten_rms import _auth_header, RMS_BASE
    import httpx, json

    db = SessionLocal()
    try:
        existing_count = db.query(ProcessedOrder).count()
        if existing_count > 0:
            logger.info(f"[scheduler] seed不要: processed_orders={existing_count}件")
            return

        settings = db.query(RakutenSettings).first()
        if not settings or not settings.rms_service_secret or not settings.rms_license_key:
            return

        headers = {**_auth_header(settings.rms_service_secret, settings.rms_license_key),
                   "Content-Type": "application/json; charset=utf-8"}
        now = dt.now(JST)
        seed_end = now - timedelta(minutes=5)

        seen: set[str] = set()
        all_order_numbers: list[str] = []
        for days_ago in range(7):
            start = (now - timedelta(days=days_ago + 1)).replace(hour=0, minute=0, second=0, microsecond=0)
            if days_ago == 0:
                end = seed_end
            else:
                end = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)

            if start >= end:
                continue

            page = 1
            while True:
                body = {
                    "dateType": 1,
                    "startDatetime": start.strftime("%Y-%m-%dT%H:%M:%S+0900"),
                    "endDatetime": end.strftime("%Y-%m-%dT%H:%M:%S+0900"),
                    "PaginationRequestModel": {"requestRecordsAmount": 100, "requestPage": page},
                }
                try:
                    async with httpx.AsyncClient(timeout=30) as client:
                        res = await client.post(
                            f"{RMS_BASE}/2.0/order/searchOrder",
                            headers=headers,
                            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                        )
                        if not res.is_success:
                            break
                        data = res.json()
                except Exception:
                    break

                page_orders = []
                for item in (data.get("orderNumberList") or []):
                    num = item if isinstance(item, str) else (
                        item.get("orderNumber") or item.get("order_number") or ""
                    )
                    if num and str(num) not in seen:
                        seen.add(str(num))
                        page_orders.append(str(num))

                all_order_numbers.extend(page_orders)
                if len(page_orders) < 100 or page >= 10:
                    break
                page += 1

        if not all_order_numbers:
            logger.info("[scheduler] seed: 過去7日の注文なし")
            return

        BATCH = 100
        seeded = 0
        for i in range(0, len(all_order_numbers), BATCH):
            batch = all_order_numbers[i:i + BATCH]
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    res = await client.post(
                        f"{RMS_BASE}/2.0/order/getOrder",
                        headers=headers,
                        content=json.dumps({"orderNumberList": batch, "version": 10}, ensure_ascii=False).encode("utf-8"),
                    )
                    if not res.is_success:
                        continue
                    detail = res.json()
                for order in detail.get("OrderModelList", []):
                    order_num = str(order.get("orderNumber") or "")
                    if not order_num:
                        continue
                    is_cancelled = order.get("orderProgress", 0) == 900
                    state = "cancelled" if is_cancelled else "active"
                    _save_processed_order(db, order_num, state)
                    seeded += 1
            except Exception as e:
                logger.warning(f"[scheduler] seed getOrder失敗: {e}")
                continue

        db.commit()
        _sync_logs.appendleft({
            "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            "type": "seed",
            "seeded": seeded,
            "total_searched": len(all_order_numbers),
        })
        logger.info(f"[scheduler] 初回seed完了: {seeded}件（在庫操作なし）")
    except Exception as e:
        logger.warning(f"[scheduler] seedエラー: {e}")
    finally:
        db.close()


async def _scheduler_loop():
    """1分ごとに受注差分の在庫同期＋RMS在庫取得、30分ごとにキャンセル再チェックを実行。

    販売数同期（60日分の受注取得）はメモリを大量に使いRender(512MB)がOOMするため、
    ここでは実行しない。GitHub Actionsの日次ワークフロー(rakuten-sales-sync.yml)が
    毎日JST3:00に実行し、集計結果だけを /rms/sales/apply で受け取る。"""
    await _seed_processed_orders()
    await _pull_rms_stock()
    tick = 0
    while True:
        await asyncio.sleep(60)
        tick += 1
        await _sync_rakuten_stock()
        await _pull_rms_stock()
        if tick % 30 == 0:
            await _check_delayed_cancellations()


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


# ============================================================
# 簡易ログイン（オーナー／外注さん1名）
# ============================================================
# AUTH_OWNER_PASSWORD が未設定の間は何もしない（今までどおり無認証で動く）。
# 設定して初めて有効になるので、コードのデプロイだけでは誰もロックアウトされない。
from starlette.requests import Request as _StarletteRequest
from starlette.responses import JSONResponse as _JSONResponse
from app.core.auth import auth_enabled, verify_token, check_service_token

# ログイン不要で通す経路。
# ・/api/auth/* はログイン自体に使うので当然除外
# ・就労支援の公開ページ（work-public）が使う一覧取得は、施設の作業者が
#   ログインなしで見るためのものなので除外
_AUTH_EXEMPT_PREFIXES = ("/api/auth/", "/docs", "/openapi.json", "/redoc")
# 就労支援さん用の公開ページ(/welfare/work-public)はログイン不要で開くので、
# そこが読むGETだけを公開する。書き込み(POST/PATCH/DELETE)は対象外なので、
# 公開ページから依頼を作ったり金額を変えたりはできない。
# 作業マスタ(packing-tasks)は公開ページで使わないため、あえて入れていない。
_AUTH_PUBLIC_GET_PATHS = {
    "/api/welfare/work-instructions",
    "/api/welfare/inventory",
    "/api/welfare/packing-orders",
    "/api/welfare/packing-orders/months",
}
# 外注さんには見せない（APIキー等が見える設定画面）
_AUTH_OWNER_ONLY_PREFIXES = ("/api/settings", "/api/rakuten/settings")


def _cors_headers_for(request: _StarletteRequest) -> dict:
    origin = request.headers.get("origin")
    if origin and origin in ALLOWED_ORIGINS:
        return {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true"}
    return {}


@app.middleware("http")
async def auth_middleware(request: _StarletteRequest, call_next):
    if request.method == "OPTIONS" or not auth_enabled():
        return await call_next(request)

    path = request.url.path
    if not path.startswith("/api/") or path.startswith(_AUTH_EXEMPT_PREFIXES):
        return await call_next(request)
    if request.method == "GET" and path in _AUTH_PUBLIC_GET_PATHS:
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    token = auth_header[7:] if auth_header.lower().startswith("bearer ") else ""

    role = None
    if token and check_service_token(token):
        role = "service"
    elif token:
        payload = verify_token(token)
        if payload:
            role = payload.get("role")

    if not role:
        return _JSONResponse(status_code=401, content={"detail": "ログインが必要です"}, headers=_cors_headers_for(request))
    # 設定の「変更」は外注さんにはさせない。「閲覧」は手数料率など他画面の計算に
    # 使う値もあるため一律には止めず、APIキーなど本当に機密な項目だけ
    # ルート側（get_rakuten_settings）でマスクする。
    if role == "contractor" and request.method != "GET" and path.startswith(_AUTH_OWNER_ONLY_PREFIXES):
        return _JSONResponse(status_code=403, content={"detail": "この機能は利用できません"}, headers=_cors_headers_for(request))

    request.state.actor_role = role
    return await call_next(request)


app.include_router(auth_routes.router, prefix="/api")
app.include_router(activity_log_routes.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(fba.router, prefix="/api")
app.include_router(invoices.router, prefix="/api")
app.include_router(price_adjustments.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(rakuten.router, prefix="/api")
app.include_router(shipment_orders.router, prefix="/api")
app.include_router(welfare.router, prefix="/api")
app.include_router(ads.router, prefix="/api")
app.include_router(review_routes.router, prefix="/api")
app.include_router(keyword_analysis_routes.router, prefix="/api")
app.include_router(seo_routes.router, prefix="/api")
app.include_router(fba_plan.router, prefix="/api")
app.include_router(inventory_snapshots.router, prefix="/api")
app.include_router(material_costs.router, prefix="/api")
app.include_router(cost_histories.router, prefix="/api")
app.include_router(amazon_research.router, prefix="/api")
app.include_router(scout.router, prefix="/api")
app.include_router(research_routes.router, prefix="/api")
app.include_router(wholesale.router, prefix="/api")
app.include_router(product_draft_routes.router, prefix="/api")

@app.get("/")
def root():
    return {"message": "中国輸入管理ツール API"}

@app.get("/api/sync-logs")
def get_sync_logs():
    """在庫同期ログ履歴（直近100件）"""
    return {"logs": list(_sync_logs)}


@app.get("/api/inventory-events")
def get_inventory_events(sku: str = None, limit: int = 100):
    """inventory_events テーブルから最新limit件を返す。sku指定でそのSKUを含むイベントのみ"""
    import json as _j
    from app.core.database import SessionLocal
    from app.models.inventory_event import InventoryEvent
    limit = max(1, min(limit, 1000))
    db = SessionLocal()
    try:
        q = db.query(InventoryEvent).order_by(InventoryEvent.id.desc())
        if sku:
            like = f'%"{sku}%'
            q = q.filter(
                InventoryEvent.sold.like(like)
                | InventoryEvent.changed.like(like)
                | InventoryEvent.recalculated.like(like)
                | InventoryEvent.stock_before.like(like)
            )
        rows = q.limit(limit).all()
        def _parse(v):
            if v is None:
                return None
            try:
                return _j.loads(v)
            except Exception:
                return v
        result = []
        for r in rows:
            result.append({
                "id": r.id,
                "event_time": r.event_time.strftime("%Y-%m-%d %H:%M:%S") if r.event_time else None,
                "event_type": r.event_type,
                "order_numbers": _parse(r.order_numbers),
                "sold": _parse(r.sold),
                "changed": _parse(r.changed),
                "recalculated": _parse(r.recalculated),
                "pushed": _parse(r.pushed),
                "push_ok": r.push_ok,
                "push_fail": r.push_fail,
                "errors": _parse(r.errors),
                "stock_before": _parse(r.stock_before),
                "stock_after": _parse(r.stock_after),
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
            })
        return {"events": result}
    finally:
        db.close()


