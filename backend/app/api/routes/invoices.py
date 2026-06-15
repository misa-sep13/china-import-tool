from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.invoice import Invoice, InvoiceItem
from app.models.product import Product
from pydantic import BaseModel
from typing import List, Optional
import io, re

router = APIRouter(prefix="/invoices", tags=["invoices"])


class InvoiceItemIn(BaseModel):
    sku: str
    asin: str = ""
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
    # 輸入許可書から取得
    customs_duty: int = 0
    consumption_tax: int = 0
    local_consumption_tax: int = 0
    total_tax: int = 0
    bl_number: str = ""
    declaration_no: str = ""
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
    col_asin = None  # ASIN列インデックス
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), 1):
        if row[0] == "10) Name of Commodity":
            header_row = i + 1  # 次の行がデータ開始
            # ヘッダー行からASIN列を探す
            for ci, cell in enumerate(row):
                if cell and "ASIN" in str(cell).upper():
                    col_asin = ci
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
            asin_val = str(row[col_asin] or "") if col_asin is not None and col_asin < len(row) else ""
            items.append({
                "sku": str(int(row[12])) if row[12] else "",
                "asin": asin_val,
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


@router.post("/parse-import-permit")
async def parse_import_permit(file: UploadFile = File(...)):
    """輸入許可書PDFを解析して為替レート・税額等を返す"""
    content = await file.read()
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF読み込みエラー: {str(e)}")

    def find_value(pattern, text, cast=str, default=None):
        m = re.search(pattern, text)
        if m:
            try:
                return cast(m.group(1).replace(",", "").strip())
            except Exception:
                pass
        return default

    exchange_rate = find_value(r'通貨レート\s+CNY\s*-\s*([\d,\.]+)', text, float, 0.0)
    customs_duty = find_value(r'関税\s*\\([\d,]+)', text, lambda x: int(x.replace(",", "")), 0)
    consumption_tax = find_value(r'消費税\s*\\([\d,]+)', text, lambda x: int(x.replace(",", "")), 0)
    local_consumption_tax = find_value(r'地方消費税\s*\\([\d,]+)', text, lambda x: int(x.replace(",", "")), 0)
    total_tax = find_value(r'納税額合計\s*\\([\d,]+)', text, lambda x: int(x.replace(",", "")), 0)
    invoice_cny = find_value(r'仕入書価格\s+[A-Z]\s+-\s+CIF\s+-\s+CNY\s+-\s+([\d,\.]+)', text, float, 0.0)
    bl_number = find_value(r'Ｂ／Ｌ番号\(1\)(\S+)', text, str, "")
    declaration_no = find_value(r'申告番号\s+([\d\s]+)', text, lambda x: x.replace(" ", ""), "")

    return {
        "bl_number": bl_number,
        "declaration_no": declaration_no,
        "exchange_rate": exchange_rate,
        "customs_duty": customs_duty,
        "consumption_tax": consumption_tax,
        "local_consumption_tax": local_consumption_tax,
        "total_tax": total_tax,
        "invoice_cny": invoice_cny,
    }


@router.post("/validate-pair")
async def validate_pair(
    invoice_file: UploadFile = File(...),
    permit_file: UploadFile = File(...),
):
    """インボイスXLSと輸入許可書PDFのCNY合計が一致するか検証する"""
    # インボイスのCNY合計を計算
    inv_content = await invoice_file.read()
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(inv_content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"インボイス読み込みエラー: {str(e)}")

    ws = wb.active
    header_row = None
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), 1):
        if row[0] == "10) Name of Commodity":
            header_row = i + 1
            break
    if not header_row:
        raise HTTPException(status_code=400, detail="インボイスの商品データが見つかりません")

    total_cny = 0.0
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if row[0] and str(row[0]).startswith("MADE IN"):
            break
        if row[0] is None and row[6] and row[7]:
            qty = float(row[6]) if row[6] else 0
            price = float(row[7]) if row[7] else 0
            total_cny += qty * price

    # 輸入許可書のCNYを取得
    permit_content = await permit_file.read()
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(permit_content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"輸入許可書読み込みエラー: {str(e)}")

    m = re.search(r'仕入書価格\s+[A-Z]\s+-\s+CIF\s+-\s+CNY\s+-\s+([\d,\.]+)', text)
    permit_cny = float(m.group(1).replace(",", "")) if m else 0.0

    total_cny = round(total_cny, 2)
    diff = abs(total_cny - permit_cny)
    ok = diff <= 1.0  # 1元以内の誤差は許容

    return {
        "ok": ok,
        "invoice_cny": total_cny,
        "permit_cny": permit_cny,
        "diff": round(diff, 2),
        "message": "照合OK" if ok else f"金額不一致（インボイス: {total_cny}元、輸入許可書: {permit_cny}元、差額: {round(diff,2)}元）",
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
        customs_duty=data.customs_duty,
        consumption_tax=data.consumption_tax,
        local_consumption_tax=data.local_consumption_tax,
        total_tax=data.total_tax,
        bl_number=data.bl_number,
        declaration_no=data.declaration_no,
    )
    db.add(invoice)
    db.flush()

    updated_products = 0
    for item in data.items:
        item_total_cny = item.qty * item.unit_price_cny
        freight_alloc = (item_total_cny / total_cny * total_freight_cny) if total_cny > 0 else 0
        cost_per_unit_jpy = ((item_total_cny + freight_alloc) / item.qty * data.exchange_rate) if item.qty > 0 else 0

        # 商品マスタとSKU→ASINの順で紐付け
        product = db.query(Product).filter(Product.sku == item.sku).first()
        if not product and item.asin:
            product = db.query(Product).filter(Product.asin == item.asin).first()
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
