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
from app.models import rakuten_ss_sales as rakuten_ss_sales_models
from app.models import processed_order as processed_order_models

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
from datetime import datetime as dt, timezone, timedelta

JST = timezone(timedelta(hours=9))
from collections import deque

logger = logging.getLogger("scheduler")

# 在庫同期ログ履歴（直近100件）
_sync_logs: deque = deque(maxlen=100)

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
    from app.services.rakuten_rms import fetch_recent_orders, push_inventory_to_rms
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

        def parse_comps(p):
            try:
                return _json.loads(p.set_components or "[]")
            except Exception:
                return []

        updated_skus = set()
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
                        cp.stock = max(0, cp.stock - c_qty)
                        sku_stock[c_sku] = cp.stock
                        updated_skus.add(c_sku)
            else:
                if p.stock is not None:
                    p.stock = max(0, p.stock - qty)
                    sku_stock[sku] = p.stock
                    updated_skus.add(sku)

        for sku, qty in new_cancelled.items():
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
                        cp.stock = cp.stock + c_qty
                        sku_stock[c_sku] = cp.stock
                        updated_skus.add(c_sku)
            else:
                if p.stock is not None:
                    p.stock = p.stock + qty
                    sku_stock[sku] = p.stock
                    updated_skus.add(sku)

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
                avail = sku_stock.get(c_sku, 0) // c_qty
                set_qty = avail if set_qty is None else min(set_qty, avail)
            if set_qty is not None:
                p.stock = set_qty
                sku_stock[p.sku] = set_qty
                updated_set_skus.add(p.sku)

        db.commit()

        # RMS_PUSH_ENABLED=trueの場合、変更されたSKUの在庫をRMSにpush
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
                    result = await push_inventory_to_rms(
                        settings.rms_service_secret, settings.rms_license_key, push_items
                    )
                    logger.info(f"[scheduler] push結果: {result}")
                except Exception as pe:
                    logger.warning(f"[scheduler] push失敗: {pe}")

        _sync_logs.appendleft({
            "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            "type": "sync",
            "searched_orders": len(order_nums),
            "skipped_processed": skipped_processed,
            "processed_new": processed_new,
            "sold": new_sold if new_sold else None,
            "cancelled": new_cancelled if new_cancelled else None,
            "updated_skus": list(updated_skus),
            "updated_sets": list(updated_set_skus),
        })
        logger.info(f"[scheduler] 在庫更新: sold={new_sold} cancelled={new_cancelled} updated={updated_skus} sets={updated_set_skus}")
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
    from app.services.rakuten_rms import push_inventory_to_rms
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

        def parse_comps(p):
            try:
                return _json.loads(p.set_components or "[]")
            except Exception:
                return []

        updated_skus = set()
        for order_num, sku_map in newly_cancelled.items():
            for sku, qty in sku_map.items():
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
                            cp.stock = cp.stock + c_qty
                            sku_stock[c_sku] = cp.stock
                            updated_skus.add(c_sku)
                else:
                    if p.stock is not None:
                        p.stock = p.stock + qty
                        sku_stock[sku] = p.stock
                        updated_skus.add(sku)

            _save_processed_order(db, order_num, "cancelled")

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
                avail = sku_stock.get(c_sku, 0) // c_qty
                set_qty = avail if set_qty is None else min(set_qty, avail)
            if set_qty is not None:
                p.stock = set_qty
                sku_stock[p.sku] = set_qty
                updated_set_skus.add(p.sku)

        db.commit()

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
                    result = await push_inventory_to_rms(
                        settings.rms_service_secret, settings.rms_license_key, push_items
                    )
                    logger.info(f"[scheduler] キャンセル戻しpush結果: {result}")
                except Exception as pe:
                    logger.warning(f"[scheduler] キャンセル戻しpush失敗: {pe}")

        cancelled_nums = list(newly_cancelled.keys())
        _sync_logs.appendleft({
            "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            "type": "delayed_cancellation",
            "cancelled_orders": cancelled_nums,
            "updated_skus": list(updated_skus),
        })
        logger.info(f"[scheduler] 遅延キャンセル検出: {len(cancelled_nums)}件 updated={updated_skus}")
    except Exception as e:
        logger.warning(f"[scheduler] キャンセル再チェックエラー: {e}")
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


async def _pull_rms_stock():
    """RMSから在庫数を取得してDBに上書き。
    ただし「セットの構成品になっている単品SKU」はpullで上書きしない。
    単品在庫はツールが受注減算で管理し、セット在庫は楽天から取得する。"""
    from app.core.database import SessionLocal
    from app.models.rakuten_settings import RakutenSettings
    from app.models.rakuten_product import RakutenProduct
    from app.services.rakuten_rms import fetch_inventory_from_rms

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

        updated = 0
        skipped = 0
        for sku, qty in rms_stock.items():
            p = sku_to_product.get(sku)
            if not p:
                continue
            # セットの構成品になっている単品はpullで上書きしない（受注減算で管理）
            if sku in component_parent_skus:
                skipped += 1
                continue
            p.stock = qty
            updated += 1

        db.commit()
        logger.info(f"[scheduler] RMS在庫取得完了: {updated}件更新, {skipped}件スキップ(単品管理)")
        _sync_logs.appendleft({
            "time": dt.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
            "type": "rms_stock",
            "updated": updated,
            "sent": len(items),
            "skipped_component_parents": skipped,
        })
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
    """1分ごとに受注差分の在庫同期＋RMS在庫取得、30分ごとにキャンセル再チェック、1時間ごとに販売数同期を実行"""
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
        if tick % 60 == 0:
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

@app.get("/api/sync-logs")
def get_sync_logs():
    """在庫同期ログ履歴（直近100件）"""
    return {"logs": list(_sync_logs)}


