from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.invoice import Invoice, InvoiceItem
from app.models.product import Product
from pydantic import BaseModel
from typing import List, Optional
import io

router = APIRouter(prefix="/invoices", tags=["invoices"])


class InvoiceItemIn(BaseModel):
    sku: str
    name_cn: str = ""
    name_jp: str = ""
    qty: int
    unit_price_cny: float
    buy_url: str = ""

class InvoiceIn(BaseModel):
    invoice_no: str
    invoice_date: str
    exchange_rate: float
    domestic_freight: float = 0
    international_freight: float = 0
    total_weight: float = 0
    total_volume: float = 0
    note: str = ""
    items: List[InvoiceItemIn]


@router.post("/parse-excel")
async def parse_excel(file: UploadFile = File(...)):
    content = await file.read()
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel読み込みエラー: {str(e)}")

    ws = wb.active

    # インボイス番号を探す（VIP...の行）
    invoice_no = ""
    for row in ws.iter_rows(min_row=1, max_row=15, values_only=True):
        for cell in row:
            if cell and str(cell).startswith("VIP"):
                invoice_no = str(cell)
                break

    # 商品行を解析（ヘッダー行を探す）
    header_row = None
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), 1):
        if row[0] == "10) Name of Commodity":
            header_row = i + 1  # 次の行がデータ開始
            break

    if not header_row:
        raise HTTPException(status_code=400, detail="商品データが見つかりません")

    items = []
    domestic_freight = 0
    international_freight = 0

    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if row[0] and str(row[0]).startswith("Domestic"):
            domestic_freight = row[8] or 0
            continue
        if row[0] and str(row[0]).startswith("International"):
            international_freight = row[8] or 0
            continue
        if row[0] and str(row[0]).startswith("MADE IN"):
            break
        if row[0] is None and row[6] and row[7]:
            items.append({
                "sku": str(int(row[12])) if row[12] else "",
                "name_cn": str(row[1] or ""),
                "name_jp": str(row[2] or ""),
                "qty": int(row[6]) if row[6] else 0,
                "unit_price_cny": float(row[7]) if row[7] else 0,
                "total_price_cny": float(row[8]) if row[8] else 0,
                "buy_url": str(row[11] or ""),
            })

    # 箱規シートから重量・容積を取得
    total_weight = 0
    total_volume = 0
    if "箱规" in wb.sheetnames:
        ws2 = wb["箱规"]
        for row in ws2.iter_rows(min_row=2, values_only=True):
            if row[0] and isinstance(row[0], (int, float)):
                total_weight += float(row[7] or 0)
                total_volume += float(row[6] or 0)

    return {
        "invoice_no": invoice_no,
        "domestic_freight": domestic_freight,
        "international_freight": international_freight,
        "total_weight": round(total_weight, 2),
        "total_volume": round(total_volume, 4),
        "items": items,
    }


@router.post("/calculate")
def calculate_cost(data: InvoiceIn):
    total_qty = sum(item.qty for item in data.items)
    total_cny = sum(item.qty * item.unit_price_cny for item in data.items)
    total_freight_cny = data.domestic_freight + data.international_freight

    result = []
    for item in data.items:
        item_total_cny = item.qty * item.unit_price_cny
        # 金額比で送料を按分
        freight_alloc = (item_total_cny / total_cny * total_freight_cny) if total_cny > 0 else 0
        cost_per_unit_jpy = ((item_total_cny + freight_alloc) / item.qty * data.exchange_rate) if item.qty > 0 else 0
        result.append({
            **item.model_dump(),
            "total_price_cny": round(item_total_cny, 2),
            "freight_alloc_cny": round(freight_alloc, 2),
            "cost_per_unit_jpy": round(cost_per_unit_jpy, 1),
        })

    return {
        "items": result,
        "total_qty": total_qty,
        "total_cny": round(total_cny, 2),
        "total_freight_cny": round(total_freight_cny, 2),
        "grand_total_jpy": round((total_cny + total_freight_cny) * data.exchange_rate, 0),
    }


@router.post("/save")
def save_invoice(data: InvoiceIn, db: Session = Depends(get_db)):
    total_cny = sum(item.qty * item.unit_price_cny for item in data.items)
    total_freight_cny = data.domestic_freight + data.international_freight

    invoice = Invoice(
        invoice_no=data.invoice_no,
        invoice_date=data.invoice_date,
        exchange_rate=data.exchange_rate,
        domestic_freight=data.domestic_freight,
        international_freight=data.international_freight,
        total_weight=data.total_weight,
        total_volume=data.total_volume,
        note=data.note,
    )
    db.add(invoice)
    db.flush()

    updated_products = 0
    for item in data.items:
        item_total_cny = item.qty * item.unit_price_cny
        freight_alloc = (item_total_cny / total_cny * total_freight_cny) if total_cny > 0 else 0
        cost_per_unit_jpy = ((item_total_cny + freight_alloc) / item.qty * data.exchange_rate) if item.qty > 0 else 0

        # 商品マスタとSKUで紐付け
        product = db.query(Product).filter(Product.sku == item.sku).first()
        product_id = product.id if product else None

        inv_item = InvoiceItem(
            invoice_id=invoice.id,
            sku=item.sku,
            product_id=product_id,
            name_cn=item.name_cn,
            name_jp=item.name_jp,
            qty=item.qty,
            unit_price_cny=item.unit_price_cny,
            total_price_cny=round(item_total_cny, 2),
            freight_alloc_cny=round(freight_alloc, 2),
            cost_per_unit_jpy=round(cost_per_unit_jpy, 1),
            buy_url=item.buy_url,
        )
        db.add(inv_item)

        # 商品マスタの単価を更新
        if product:
            product.price = round(cost_per_unit_jpy, 1)
            updated_products += 1

    db.commit()
    return {"invoice_id": invoice.id, "updated_products": updated_products}


@router.get("/")
def list_invoices(db: Session = Depends(get_db)):
    invoices = db.query(Invoice).order_by(Invoice.created_at.desc()).all()
    return invoices


@router.get("/{invoice_id}/items")
def get_invoice_items(invoice_id: int, db: Session = Depends(get_db)):
    items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).all()
    return items
