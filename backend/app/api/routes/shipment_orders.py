from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from app.core.database import get_db
from app.models.shipment_order import ShipmentOrder, ShipmentOrderItem
from app.models.product import Product
from app.models.rakuten_product import RakutenProduct
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
import io

router = APIRouter(prefix="/shipment-orders", tags=["shipment_orders"])


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
        # URLはofferIDまでに正規化（?以降除去）
        if "?" in buy_url:
            buy_url = buy_url.split("?")[0]
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
    """URLで楽天商品マスタと照合して照合結果を返す"""
    rakuten_products = db.query(RakutenProduct).filter(RakutenProduct.buy_url.isnot(None)).all()

    def normalize_url(url: str) -> str:
        if not url:
            return ""
        url = url.split("?")[0].rstrip("/")
        return url.lower()

    url_map = {normalize_url(p.buy_url): p for p in rakuten_products if p.buy_url}

    matched = []
    unmatched = []
    for item in items:
        norm = normalize_url(item.get("buy_url", ""))
        product = url_map.get(norm)
        if product:
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
def receive_shipment(order_id: int, db: Session = Depends(get_db)):
    """入荷済みにして在庫を加算する"""
    order = db.query(ShipmentOrder).filter(ShipmentOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="配送依頼が見つかりません")
    if order.status == "received":
        raise HTTPException(status_code=400, detail="すでに入荷済みです")

    items = db.query(ShipmentOrderItem).filter(ShipmentOrderItem.shipment_order_id == order_id).all()
    updated = 0
    skipped = 0
    for item in items:
        if not item.product_id:
            skipped += 1
            continue
        product = db.query(RakutenProduct).filter(RakutenProduct.id == item.product_id).first()
        if product:
            product.stock = (product.stock or 0) + item.qty
            updated += 1

    order.status = "received"
    order.received_at = datetime.now(timezone.utc)
    db.commit()
    return {"updated": updated, "skipped": skipped}
