from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from app.core.database import get_db
from app.models.shipment_order import ShipmentOrder, ShipmentOrderItem
from app.models.product import Product
from app.models.rakuten_product import RakutenProduct
from app.models.rakuten_order import RakutenOrderHistory
from app.models.inventory_reflection_log import InventoryReflectionLog
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
import asyncio
import io, uuid

router = APIRouter(prefix="/shipment-orders", tags=["shipment_orders"])


def _url_match_key(url: str) -> str:
    value = (url or "").strip().lower()
    if not value:
        return ""
    import re
    m = re.search(r"offer/(\d+)\.html", value)
    if m:
        return f"1688:{m.group(1)}"
    m = re.search(r"[?&]id=(\d+)", value)
    if m:
        return f"id:{m.group(1)}"
    return value.split("?")[0].rstrip("/")


def _norm_text(value: str) -> str:
    return (value or "").strip().replace(" ", "").replace("　", "")


class ShipmentOrderItemPatch(BaseModel):
    product_id: int


@router.post("/parse-excel")
async def parse_excel(file: UploadFile = File(...)):
    content = await file.read()
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel読み込みエラー: {str(e)}")

    ws = wb.active

    # ヘッダー情報の取得（行/列は固定レイアウトに依存）
    def find_cell(keyword, max_row=10):
        for row in ws.iter_rows(min_row=1, max_row=max_row, values_only=True):
            for i, cell in enumerate(row):
                if cell and keyword in str(cell):
                    return row, i
        return None, -1

    shipped_date = ""
    tracking_no = ""
    order_no = ""
    box_count = 0
    total_weight_kg = 0.0

    # 固定位置から値を取得（send-order-listのレイアウト）
    for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
        row_vals = [str(c) if c is not None else "" for c in row]
        joined = "".join(row_vals)
        if "出荷日" in joined:
            # 出荷日は同じ行の次のセルにある
            for i, c in enumerate(row):
                if c and "出荷日" in str(c) and i + 1 < len(row):
                    shipped_date = str(row[i + 1] or "")[:10]
        if "配送依赖No" in joined or "配送依頼No" in joined:
            for i, c in enumerate(row):
                if c and ("配送依赖No" in str(c) or "配送依頼No" in str(c)) and i + 1 < len(row):
                    order_no = str(row[i + 1] or "")
        if "追跡番号" in joined:
            for i, c in enumerate(row):
                if c and "追跡番号" in str(c) and i + 1 < len(row):
                    tracking_no = str(row[i + 1] or "")
        if "実際重量" in joined:
            for i, c in enumerate(row):
                if c and "実際重量" in str(c) and i + 1 < len(row):
                    try:
                        total_weight_kg = float(row[i + 1] or 0)
                    except Exception:
                        pass
        if "箱数" in joined:
            for i, c in enumerate(row):
                if c and "箱数" in str(c) and i + 1 < len(row):
                    try:
                        box_count = int(row[i + 1] or 0)
                    except Exception:
                        pass

    # 商品行のヘッダーを探す（発注時間・商品名・色・サイズ・URL・単価・数量）
    header_row_idx = None
    col_map = {}
    for i, row in enumerate(ws.iter_rows(values_only=True), 1):
        row_strs = [str(c) if c else "" for c in row]
        if "商品名" in row_strs and "数量" in row_strs:
            header_row_idx = i
            for ci, c in enumerate(row_strs):
                col_map[c] = ci
            break

    if header_row_idx is None:
        raise HTTPException(status_code=400, detail="商品データ行が見つかりません")

    col_name = col_map.get("商品名", -1)
    col_color = col_map.get("色", -1)
    col_size = col_map.get("サイズ", -1)
    col_url = col_map.get("商品URL", -1)
    col_price = col_map.get("単価", -1)
    col_qty = col_map.get("数量", -1)

    items_raw = []
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if all(c is None for c in row):
            continue
        name_cn = str(row[col_name] or "") if col_name >= 0 else ""
        if not name_cn:
            continue
        buy_url = str(row[col_url] or "") if col_url >= 0 else ""
        items_raw.append({
            "name_cn": name_cn,
            "color": str(row[col_color] or "") if col_color >= 0 else "",
            "size": str(row[col_size] or "") if col_size >= 0 else "",
            "buy_url": buy_url,
            "unit_price_cny": float(row[col_price] or 0) if col_price >= 0 else 0,
            "qty": int(row[col_qty] or 0) if col_qty >= 0 else 0,
        })

    return {
        "shipped_date": shipped_date,
        "tracking_no": tracking_no,
        "order_no": order_no,
        "box_count": box_count,
        "total_weight_kg": total_weight_kg,
        "items": items_raw,
    }


@router.post("/match")
def match_products(items: List[dict], db: Session = Depends(get_db)):
    """配送依頼明細を楽天商品マスタと照合して照合結果を返す"""
    rakuten_products = db.query(RakutenProduct).filter(RakutenProduct.buy_url.isnot(None)).all()
    pending_rows = (
        db.query(RakutenOrderHistory.sku, sqlfunc.sum(RakutenOrderHistory.qty))
        .filter(RakutenOrderHistory.is_deleted == False, RakutenOrderHistory.is_delivered == False)
        .group_by(RakutenOrderHistory.sku)
        .all()
    )
    pending_by_sku = {sku: qty or 0 for sku, qty in pending_rows}

    url_key_counts = {}
    for p in rakuten_products:
        key = _url_match_key(p.buy_url or "")
        if key:
            url_key_counts[key] = url_key_counts.get(key, 0) + 1

    def score_product(item: dict, product: RakutenProduct) -> int:
        score = 0
        item_key = _url_match_key(item.get("buy_url", ""))
        product_key = _url_match_key(product.buy_url or "")
        if item_key and product_key and item_key == product_key:
            score += 45
            if url_key_counts.get(product_key, 0) == 1:
                score += 10

        color = _norm_text(item.get("color", ""))
        size = _norm_text(item.get("size", ""))
        spec = _norm_text(product.supplier_spec or "")
        if spec and color and spec == color:
            score += 35
        elif spec and color and size and spec in {
            _norm_text(f"{item.get('color', '')}、{item.get('size', '')}"),
            _norm_text(f"{item.get('color', '')} {item.get('size', '')}"),
        }:
            score += 35
        elif spec and color and (spec in color or color in spec):
            score += 18

        try:
            item_price = float(item.get("unit_price_cny") or 0)
            product_price = float(product.price or 0)
            if item_price > 0 and abs(item_price - product_price) < 0.011:
                score += 15
        except Exception:
            pass
        try:
            set_size = product.set_size or 1
            received_qty = int(item.get("qty") or 0) // set_size if set_size > 1 else int(item.get("qty") or 0)
            pending_qty = (pending_by_sku.get(product.sku, 0) or 0) + (product.inbound or 0) + (product.standard_stock or 0)
            if received_qty > 0 and pending_qty == received_qty:
                score += 25
        except Exception:
            pass
        return score

    matched = []
    unmatched = []
    for item in items:
        candidates = sorted(
            ((score_product(item, p), p) for p in rakuten_products),
            key=lambda x: x[0],
            reverse=True,
        )
        best_score, product = candidates[0] if candidates else (0, None)
        second_score = candidates[1][0] if len(candidates) > 1 else 0
        if product and best_score >= 50 and best_score > second_score:
            matched.append({**item, "product_id": product.id, "sku": product.sku, "name_jp": product.name})
        else:
            unmatched.append(item)

    return {"matched": matched, "unmatched": unmatched}


class ShipmentOrderSaveIn(BaseModel):
    shipped_date: str
    tracking_no: str
    order_no: str
    box_count: int = 0
    total_weight_kg: float = 0
    note: str = ""
    matched: List[dict]
    unmatched: List[dict]


@router.post("/save")
def save_shipment_order(data: ShipmentOrderSaveIn, db: Session = Depends(get_db)):
    order = ShipmentOrder(
        tracking_no=data.tracking_no,
        order_no=data.order_no,
        shipped_date=data.shipped_date,
        box_count=data.box_count,
        total_weight_kg=data.total_weight_kg,
        note=data.note,
        status="pending",
    )
    db.add(order)
    db.flush()

    for item in data.matched:
        db.add(ShipmentOrderItem(
            shipment_order_id=order.id,
            product_id=item.get("product_id"),
            name_cn=item.get("name_cn", ""),
            color=item.get("color", ""),
            size=item.get("size", ""),
            buy_url=item.get("buy_url", ""),
            unit_price_cny=item.get("unit_price_cny", 0),
            qty=item.get("qty", 0),
            is_matched=True,
        ))

    for item in data.unmatched:
        db.add(ShipmentOrderItem(
            shipment_order_id=order.id,
            product_id=item.get("product_id"),  # 手動照合後はセット済み
            name_cn=item.get("name_cn", ""),
            color=item.get("color", ""),
            size=item.get("size", ""),
            buy_url=item.get("buy_url", ""),
            unit_price_cny=item.get("unit_price_cny", 0),
            qty=item.get("qty", 0),
            is_matched=bool(item.get("product_id")),
        ))

    db.commit()
    return {"shipment_order_id": order.id}


@router.get("/")
def list_shipment_orders(db: Session = Depends(get_db)):
    orders = db.query(ShipmentOrder).order_by(ShipmentOrder.created_at.desc()).all()
    result = []
    for o in orders:
        items = db.query(ShipmentOrderItem).filter(ShipmentOrderItem.shipment_order_id == o.id).all()
        unmatched_count = sum(1 for i in items if not i.is_matched)
        result.append({
            "id": o.id,
            "tracking_no": o.tracking_no,
            "order_no": o.order_no,
            "shipped_date": o.shipped_date,
            "box_count": o.box_count,
            "total_weight_kg": o.total_weight_kg,
            "status": o.status,
            "received_at": o.received_at,
            "note": o.note,
            "item_count": len(items),
            "unmatched_count": unmatched_count,
        })
    return result


@router.get("/{order_id}/items")
def get_shipment_order_items(order_id: int, db: Session = Depends(get_db)):
    items = db.query(ShipmentOrderItem).filter(ShipmentOrderItem.shipment_order_id == order_id).all()
    result = []
    for item in items:
        product = db.query(RakutenProduct).filter(RakutenProduct.id == item.product_id).first() if item.product_id else None
        result.append({
            "id": item.id,
            "product_id": item.product_id,
            "sku": product.sku if product else None,
            "name_jp": product.name if product else None,
            "name_cn": item.name_cn,
            "color": item.color,
            "size": item.size,
            "buy_url": item.buy_url,
            "unit_price_cny": item.unit_price_cny,
            "qty": item.qty,
            "is_matched": item.is_matched,
        })
    return result


@router.patch("/{order_id}/items/{item_id}/match")
def match_item(order_id: int, item_id: int, data: ShipmentOrderItemPatch, db: Session = Depends(get_db)):
    """未照合アイテムに手動でSKUを紐付ける"""
    item = db.query(ShipmentOrderItem).filter(
        ShipmentOrderItem.id == item_id,
        ShipmentOrderItem.shipment_order_id == order_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="アイテムが見つかりません")
    product = db.query(RakutenProduct).filter(RakutenProduct.id == data.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="商品が見つかりません")
    item.product_id = data.product_id
    item.is_matched = True
    db.commit()
    return {"ok": True}


@router.post("/{order_id}/receive")
async def receive_shipment(order_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """入荷済みにして在庫を加算する"""
    order = db.query(ShipmentOrder).filter(ShipmentOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="配送依頼が見つかりません")
    if order.status == "received":
        raise HTTPException(status_code=400, detail="すでに入荷済みです")

    items = db.query(ShipmentOrderItem).filter(ShipmentOrderItem.shipment_order_id == order_id).all()
    updated = 0
    skipped = 0
    order_consumed = 0  # 発注済みリストから消化した件数
    consumed_skus = set()  # 消化が発生したSKU（発注済2→1の繰り上げ判定用）
    updated_skus = set()   # 在庫を加算したSKU（セット再計算・RMS反映用）
    reflection_rows = []

    for item in items:
        if not item.product_id:
            skipped += 1
            continue
        product = db.query(RakutenProduct).filter(RakutenProduct.id == item.product_id).first()
        if not product:
            skipped += 1
            continue

        # 配送依頼の数量は仕入れ単位。販売在庫はset_sizeで割った単位で管理する。
        set_size = product.set_size or 1
        received_qty = item.qty // set_size if set_size > 1 else item.qty
        if received_qty <= 0:
            skipped += 1
            continue

        before = {
            "stock": product.stock or 0,
            "inbound": product.inbound or 0,
            "standard_stock": product.standard_stock or 0,
        }

        # 在庫加算
        product.stock = (product.stock or 0) + received_qty
        updated += 1
        updated_skus.add(product.sku)

        # 発注済みリストをSKU・古い順に消化
        remaining = received_qty
        orders = db.query(RakutenOrderHistory).filter(
            RakutenOrderHistory.sku == product.sku,
            RakutenOrderHistory.is_deleted == False,
        ).order_by(RakutenOrderHistory.created_at.asc()).all()

        for o in orders:
            if remaining <= 0:
                break
            if remaining >= o.qty:
                remaining -= o.qty
                o.is_deleted = True
                order_consumed += 1
            else:
                o.qty -= remaining
                remaining = 0
                order_consumed += 1

        # 旧方式で商品マスタに残っている発注済1/2も、移行漏れ対策として消化する。
        if remaining > 0:
            consume_legacy = min(remaining, product.inbound or 0)
            product.inbound = (product.inbound or 0) - consume_legacy
            remaining -= consume_legacy
        if remaining > 0:
            consume_legacy2 = min(remaining, product.standard_stock or 0)
            product.standard_stock = (product.standard_stock or 0) - consume_legacy2
            remaining -= consume_legacy2
        consumed_skus.add(product.sku)

        reflection_rows.append({
            "sku": product.sku,
            "name": product.name,
            "supplier": product.supplier,
            "received_qty": received_qty,
            "stock_before": before["stock"],
            "stock_after": product.stock or 0,
            "inbound_before": before["inbound"],
            "inbound_after": product.inbound or 0,
            "standard_stock_before": before["standard_stock"],
            "standard_stock_after": product.standard_stock or 0,
        })

    # 発注済1が空になったSKUは、残っている発注済2を発注済1へ繰り上げる
    promoted = 0
    for sku in consumed_skus:
        remaining_orders = db.query(RakutenOrderHistory).filter(
            RakutenOrderHistory.sku == sku,
            RakutenOrderHistory.is_deleted == False,
            RakutenOrderHistory.is_delivered == False,
        ).all()
        if any((o.stage or 1) == 1 for o in remaining_orders):
            continue
        for o in remaining_orders:
            if o.stage == 2:
                o.stage = 1
                promoted += 1

    # セット在庫を再計算し、RMSへ反映するitemsを組み立てる。
    # pushしないと毎分のRMS在庫取得(pull)で楽天側の古い在庫に巻き戻ってしまうため必須。
    rms_items = []
    if updated_skus:
        from app.api.routes.rakuten import _recalc_dependent_set_stock, _build_rms_stock_items
        all_products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
        sku_stock = {p.sku: (p.stock or 0) for p in all_products}
        _recalc_dependent_set_stock(all_products, sku_stock, updated_skus)
        rms_items = _build_rms_stock_items(all_products, sku_stock, updated_skus)

    order.status = "received"
    order.received_at = datetime.now(timezone.utc)
    event_id = str(uuid.uuid4())
    source_ref = order.tracking_no or order.order_no or f"配送依頼#{order.id}"
    for row in reflection_rows:
        db.add(InventoryReflectionLog(
            event_id=event_id,
            source="shipment_order",
            source_label="配送依頼",
            source_id=order.id,
            source_ref=source_ref,
            note=f"未照合スキップ: {skipped}件 / 発注済消化: {order_consumed}件",
            rms_push_items=0,
            **row,
        ))
    db.commit()

    push_items = 0
    push_result = {"ok": 0, "fail": 0, "errors": [], "details": []}
    if rms_items:
        from app.api.routes.rakuten import _get_or_create_settings
        settings = _get_or_create_settings(db)
        if settings.rms_service_secret and settings.rms_license_key:
            from app.services.rakuten_rms import push_inventory_to_rms
            push_items = len(rms_items)
            for attempt in range(3):
                push_result = await push_inventory_to_rms(
                    settings.rms_service_secret,
                    settings.rms_license_key,
                    rms_items,
                )
                if push_result.get("fail", 0) == 0:
                    break
                await asyncio.sleep(2 * (attempt + 1))
            note_suffix = (
                f" / RMS push ok:{push_result.get('ok', 0)}"
                f" fail:{push_result.get('fail', 0)}"
            )
            db.query(InventoryReflectionLog).filter(
                InventoryReflectionLog.event_id == event_id,
            ).update({
                "rms_push_items": push_items,
                "note": f"未照合スキップ: {skipped}件 / 発注済消化: {order_consumed}件{note_suffix}",
            })
            db.commit()

    return {"updated": updated, "skipped": skipped, "order_consumed": order_consumed,
            "stage_promoted": promoted, "rms_push_items": push_items,
            "rms_push_ok": push_result.get("ok", 0),
            "rms_push_fail": push_result.get("fail", 0),
            "rms_push_errors": push_result.get("errors", []),
            "rms_push_details": push_result.get("details", [])}
