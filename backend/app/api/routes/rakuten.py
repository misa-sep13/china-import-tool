from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from datetime import date, datetime
import csv, io, json
from pydantic import BaseModel
import asyncio
from app.core.database import get_db
from app.models.rakuten_product import RakutenProduct
from app.models.rakuten_order import RakutenOrderHistory
from app.models.rakuten_settings import RakutenSettings
from app.services.rakuten_calc import calc_rakuten_order, RakutenCalcSettings

router = APIRouter(prefix="/rakuten", tags=["rakuten"])


# ============================================================
# Settings
# ============================================================

class RakutenSettingsSchema(BaseModel):
    lead_days:          int   = 20
    target_days:        int   = 30
    safety_stock_rate:  float = 0.10
    threshold_days:     int   = 60
    super_sale_enabled: bool  = False
    super_sale_mode:    str   = 'A'
    super_sale_start:   Optional[date] = None
    super_sale_end:     Optional[date] = None
    commission_rate:    float = 0.09
    rms_service_secret: Optional[str] = None
    rms_license_key:    Optional[str] = None
    rms_key_expires_at: Optional[date] = None

    class Config:
        from_attributes = True

def _get_or_create_settings(db: Session) -> RakutenSettings:
    row = db.query(RakutenSettings).first()
    if not row:
        row = RakutenSettings()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row

@router.get("/settings", response_model=RakutenSettingsSchema)
def get_settings(db: Session = Depends(get_db)):
    return _get_or_create_settings(db)

@router.put("/settings", response_model=RakutenSettingsSchema)
def update_settings(data: RakutenSettingsSchema, db: Session = Depends(get_db)):
    row = _get_or_create_settings(db)
    for k, v in data.model_dump().items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


# ============================================================
# Products (商品マスタ)
# ============================================================

class RakutenProductIn(BaseModel):
    sku:              str
    name:             Optional[str] = None
    jan_code:         Optional[str] = None
    buy_url:          Optional[str] = None
    price:            Optional[float] = None
    spec:             Optional[str] = None
    set_size:         int = 1
    rakuten_item_url: Optional[str] = None
    rakuten_sku_id:   Optional[str] = None
    supplier:         Optional[str] = None
    standard_stock:   int = 0
    stock:            int = 0
    inbound:          int = 0
    sales_30_recent:  int = 0
    sales_30_prev:    int = 0
    cost_jpy:         Optional[float] = None
    selling_price:    Optional[float] = None
    customer_memo:    Optional[str] = None
    notes:            Optional[str] = None
    memo:             Optional[str] = None
    set_components:   Optional[str] = None  # JSON文字列
    is_component:     bool = False          # 単品（セット構成用内部管理）フラグ
    is_active:        bool = True

class RakutenProductOut(RakutenProductIn):
    id:               int
    sales_updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

@router.get("/products", response_model=List[RakutenProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.query(RakutenProduct).filter(RakutenProduct.is_active == True).order_by(RakutenProduct.sku.asc()).all()

@router.get("/stock")
def list_stock(db: Session = Depends(get_db)):
    """在庫・損益一覧（バリエーション商品のみ、is_component=Falseを対象）"""
    settings = _get_or_create_settings(db)
    commission_rate = settings.commission_rate or 0.09
    products = (
        db.query(RakutenProduct)
        .filter(RakutenProduct.is_active == True, RakutenProduct.is_component == False)
        .order_by(RakutenProduct.sku.asc())
        .all()
    )
    result = []
    for p in products:
        selling_price = p.selling_price
        cost_jpy = p.cost_jpy
        commission = round(selling_price * commission_rate, 0) if selling_price else None
        profit = round(selling_price - (cost_jpy or 0) - (commission or 0), 0) if selling_price else None
        profit_rate = round(profit / selling_price * 100, 1) if (selling_price and profit is not None) else None
        result.append({
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "spec": p.spec,
            "customer_memo": p.customer_memo,
            "stock": p.stock,
            "inbound": p.inbound,
            "standard_stock": p.standard_stock,
            "sales_30_recent": p.sales_30_recent,
            "sales_30_prev": p.sales_30_prev,
            "selling_price": selling_price,
            "cost_jpy": cost_jpy,
            "commission": commission,
            "commission_rate": commission_rate,
            "profit": profit,
            "profit_rate": profit_rate,
            "notes": p.notes,
        })
    return result

@router.post("/products", response_model=RakutenProductOut)
def create_product(data: RakutenProductIn, db: Session = Depends(get_db)):
    existing = db.query(RakutenProduct).filter(RakutenProduct.sku == data.sku).first()
    if existing:
        if existing.is_active:
            raise HTTPException(400, "SKUが既に存在します")
        # 論理削除済みの場合は復活させて更新
        for k, v in data.model_dump().items():
            setattr(existing, k, v)
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return existing
    p = RakutenProduct(**data.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p

@router.put("/products/{product_id}", response_model=RakutenProductOut)
def update_product(product_id: int, data: RakutenProductIn, db: Session = Depends(get_db)):
    p = db.query(RakutenProduct).filter(RakutenProduct.id == product_id).first()
    if not p:
        raise HTTPException(404, "商品が見つかりません")
    dup = db.query(RakutenProduct).filter(
        RakutenProduct.sku == data.sku, RakutenProduct.id != product_id
    ).first()
    if dup:
        raise HTTPException(400, "SKUが既に存在します")
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p

@router.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    p = db.query(RakutenProduct).filter(RakutenProduct.id == product_id).first()
    if not p:
        raise HTTPException(404)
    p.is_active = False
    db.commit()
    return {"ok": True}

@router.patch("/products/{product_id}/stock")
def update_stock(product_id: int, body: dict, db: Session = Depends(get_db)):
    p = db.query(RakutenProduct).filter(RakutenProduct.id == product_id).first()
    if not p:
        raise HTTPException(404)
    if "stock" in body:
        p.stock = body["stock"]
    if "inbound" in body:
        p.inbound = body["inbound"]
    if "sales_30_recent" in body:
        p.sales_30_recent = body["sales_30_recent"]
    if "sales_30_prev" in body:
        p.sales_30_prev = body["sales_30_prev"]
        p.sales_updated_at = datetime.now()
    db.commit()
    return {"ok": True}


# ============================================================
# Order Recommendations（発注推奨リスト）
# ============================================================

@router.get("/orders/recommendations")
def get_recommendations(db: Session = Depends(get_db)):
    settings_row = _get_or_create_settings(db)
    s = RakutenCalcSettings(
        lead_days=settings_row.lead_days,
        target_days=settings_row.target_days,
        safety_stock_rate=settings_row.safety_stock_rate,
        threshold_days=settings_row.threshold_days,
    )

    # 発注済み（未納品）の数量をSKUごとに集計
    ordered_by_sku = dict(
        db.query(RakutenOrderHistory.sku, func.sum(RakutenOrderHistory.qty))
        .filter(RakutenOrderHistory.is_delivered == False, RakutenOrderHistory.is_deleted == False)
        .group_by(RakutenOrderHistory.sku)
        .all()
    )

    # 全商品を取得
    all_products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()

    # セット商品（is_component=False かつ set_components あり）の販売実績を
    # 構成単品SKUへ按分して集計する
    # result: {単品SKU: {"recent": N, "prev": N}}
    unit_sales: dict[str, dict] = {}

    for p in all_products:
        if p.is_component or not p.set_components:
            continue
        try:
            comps = json.loads(p.set_components or "[]")
        except Exception:
            comps = []
        for c in comps:
            unit_sku = c.get("sku", "")
            qty = c.get("qty", 1) or 1
            if not unit_sku:
                continue
            if unit_sku not in unit_sales:
                unit_sales[unit_sku] = {"recent": 0, "prev": 0}
            unit_sales[unit_sku]["recent"] += (p.sales_30_recent or 0) * qty
            unit_sales[unit_sku]["prev"]   += (p.sales_30_prev   or 0) * qty

    # 単品（is_component=True）ごとに発注計算
    singles = [p for p in all_products if p.is_component]
    items = []
    for p in singles:
        ordered = ordered_by_sku.get(p.sku, 0) or 0
        agg = unit_sales.get(p.sku, {})
        sales_recent = agg.get("recent", 0)
        sales_prev   = agg.get("prev",   0)
        calc = calc_rakuten_order(
            stock=p.stock or 0,
            inbound=p.inbound or 0,
            ordered=ordered,
            sales_30_recent=sales_recent,
            sales_30_prev=sales_prev,
            super_sale_qty=0,
            sales_90=p.sales_90 or 0,
            stockout_days_90=p.stockout_days_90 or 0,
            s=s,
        )
        items.append({
            "product_id":      p.id,
            "sku":             p.sku or "",
            "name":            p.name or "",
            "jan_code":        p.jan_code or "",
            "buy_url":         p.buy_url or "",
            "set_size":        p.set_size or 1,
            "stock":           p.stock or 0,
            "inbound":         p.inbound or 0,
            "ordered":         ordered,
            "total_stock":     calc.total_stock,
            "daily_avg":       calc.daily_avg,
            "days_left":       calc.days_left,
            "growth_rate":     calc.growth_rate,
            "predicted_30":    calc.predicted_30,
            "lead_sales":      calc.lead_sales,
            "safety_stock":    calc.safety_stock,
            "order_qty":       calc.order_qty,
            "needs_order":     calc.needs_order,
            "sales_30_recent": sales_recent,
            "sales_30_prev":   sales_prev,
        })

    return {"items": items, "settings": RakutenSettingsSchema.model_validate(settings_row)}


# ============================================================
# Order History（発注済みリスト）
# ============================================================

class RakutenOrderIn(BaseModel):
    sku:       str
    name:      Optional[str] = None
    qty:       int
    ordered_at: Optional[date] = None
    memo:      Optional[str] = None

class RakutenOrderOut(BaseModel):
    id:          int
    sku:         str
    name:        Optional[str] = None
    qty:         int
    ordered_at:  Optional[date] = None
    is_delivered: bool
    memo:        Optional[str] = None

    class Config:
        from_attributes = True

@router.get("/orders/history", response_model=List[RakutenOrderOut])
def list_orders(db: Session = Depends(get_db)):
    return (
        db.query(RakutenOrderHistory)
        .filter(
            RakutenOrderHistory.is_deleted == False,
            RakutenOrderHistory.is_delivered == False,
        )
        .order_by(RakutenOrderHistory.ordered_at.desc())
        .all()
    )

@router.post("/orders/history", response_model=RakutenOrderOut)
def create_order(data: RakutenOrderIn, db: Session = Depends(get_db)):
    o = RakutenOrderHistory(
        sku=data.sku,
        name=data.name,
        qty=data.qty,
        ordered_at=data.ordered_at or date.today(),
        memo=data.memo,
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o

@router.patch("/orders/history/{order_id}/deliver")
def mark_delivered(order_id: int, db: Session = Depends(get_db)):
    o = db.query(RakutenOrderHistory).filter(RakutenOrderHistory.id == order_id).first()
    if not o:
        raise HTTPException(404)
    o.is_delivered = True
    db.commit()
    return {"ok": True}

@router.delete("/orders/history/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db)):
    o = db.query(RakutenOrderHistory).filter(RakutenOrderHistory.id == order_id).first()
    if not o:
        raise HTTPException(404)
    o.is_deleted = True
    db.commit()
    return {"ok": True}


# ============================================================
# Excel発注書ダウンロード（TAO太郎形式）
# ============================================================

@router.post("/orders/excel")
def download_order_excel(body: dict, db: Session = Depends(get_db)):
    """発注リストをTAO太郎形式Excelで出力"""
    from app.services.excel_export import build_rakuten_taotaro_excel
    order_items = body.get("items", [])  # [{sku, qty}, ...]

    excel_items = []
    for oi in order_items:
        sku = oi.get("sku")
        qty = oi.get("qty", 0)
        if not sku or not qty:
            continue
        p = db.query(RakutenProduct).filter(RakutenProduct.sku == sku).first()
        if not p:
            continue
        excel_items.append({
            "buy_url":       p.buy_url or "",
            "spec":          p.spec or "",
            "qty":           qty,
            "price":         p.price or 0,
            "customer_memo": p.customer_memo or "",
            "notes":         p.notes or "",
        })

    xls = build_rakuten_taotaro_excel(excel_items)
    return StreamingResponse(
        io.BytesIO(xls),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=rakuten_order.xlsx"},
    )


# ============================================================
# CSV インポート / テンプレートDL
# ============================================================

CSV_COLUMNS = [
    "sku", "name", "jan_code", "spec", "buy_url", "price",
    "set_size", "rakuten_item_url", "rakuten_sku_id", "supplier", "standard_stock",
    "stock", "inbound", "sales_30_recent", "sales_30_prev",
    "customer_memo", "notes", "memo", "set_components", "is_component",
]

CSV_COLUMN_LABELS = {
    "sku":              "商品管理番号(URL)※必須",
    "name":             "商品名",
    "jan_code":         "JANコード",
    "spec":             "システム連携用SKU番号",
    "buy_url":          "仕入れURL",
    "price":            "仕入れ値(元)",
    "set_size":         "セット入数",
    "rakuten_item_url": "在庫管理番号",
    "rakuten_sku_id":   "楽天SKU管理番号",
    "supplier":         "仕入先",
    "standard_stock":   "規定在庫数",
    "stock":            "実在庫(手持ち)",
    "inbound":          "輸送中",
    "sales_30_recent":  "直近30日販売数",
    "sales_30_prev":    "60日前〜31日前の販売数",
    "customer_memo":    "お客様専用メモ",
    "notes":            "備考",
    "memo":             "内部メモ",
    "set_components":   "セット構成JSON",
    "is_component":     "単品フラグ(TRUE/FALSE)",
}

@router.get("/products/csv/template")
def download_csv_template():
    """CSVテンプレートをダウンロード"""
    output = io.StringIO()
    writer = csv.writer(output)
    # ヘッダー行（日本語ラベル）
    writer.writerow([CSV_COLUMN_LABELS[c] for c in CSV_COLUMNS])
    # サンプル行
    writer.writerow([
        "ITEM-001", "サンプル商品A", "4900000000001", "レッド",
        "https://item.taobao.com/xxx", "12.5",
        "1", "https://item.rakuten.co.jp/shop/xxx/", "12345678-A", "タオタロウ", "50",
        "100", "0", "45", "40",
        "お客様専用メモ例", "備考例", "内部メモ例",
    ])
    output.seek(0)
    # BOM付きUTF-8でExcelで文字化けしないように
    content = "﻿" + output.getvalue()
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=rakuten_products_template.csv"},
    )

@router.get("/products/csv/export")
def export_products_csv(db: Session = Depends(get_db)):
    """現在の商品マスタをCSVエクスポート"""
    products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).order_by(RakutenProduct.id).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([CSV_COLUMN_LABELS[c] for c in CSV_COLUMNS])
    for p in products:
        writer.writerow([
            p.sku or "", p.name or "", p.jan_code or "", p.spec or "",
            p.buy_url or "", p.price if p.price is not None else "",
            p.set_size or 1,
            getattr(p, 'rakuten_item_url', '') or "",
            getattr(p, 'rakuten_sku_id', '') or "",
            getattr(p, 'supplier', '') or "",
            getattr(p, 'standard_stock', 0) or 0,
            p.stock or 0, p.inbound or 0,
            p.sales_30_recent or 0, p.sales_30_prev or 0,
            getattr(p, 'customer_memo', '') or "",
            getattr(p, 'notes', '') or "",
            p.memo or "",
        ])
    output.seek(0)
    content = "﻿" + output.getvalue()
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=rakuten_products.csv"},
    )

@router.post("/products/csv/import")
def import_products_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """CSVをアップロードして商品を一括登録・更新"""
    try:
        raw = file.file.read()
        # BOM除去 + デコード（UTF-8 / Shift-JIS 両対応）
        for enc in ("utf-8-sig", "shift_jis", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        else:
            raise HTTPException(400, "文字コードの読み取りに失敗しました（UTF-8またはShift-JISで保存してください）")
    except Exception as e:
        raise HTTPException(400, f"ファイル読み込みエラー: {e}")

    reader = csv.DictReader(io.StringIO(text))

    # ヘッダーを内部キー名にマッピング（日本語ラベル or 英語キー どちらでも受け付ける）
    label_to_key = {v: k for k, v in CSV_COLUMN_LABELS.items()}
    label_to_key.update({k: k for k in CSV_COLUMNS})  # 英語キーもOK

    created = updated = skipped = 0
    errors = []

    for i, row in enumerate(reader, start=2):  # 2行目から（1行目はヘッダー）
        # ヘッダーを正規化
        normalized = {}
        for col, val in row.items():
            key = label_to_key.get((col or "").strip())
            if key:
                normalized[key] = (val or "").strip()

        sku = normalized.get("sku", "")
        if not sku:
            errors.append(f"{i}行目: SKUが空のためスキップ")
            skipped += 1
            continue

        def to_int(v, default=0):
            try: return int(float(v)) if v else default
            except: return default

        def to_float(v, default=None):
            try: return float(v) if v else default
            except: return default

        is_comp_raw = normalized.get("is_component", "").upper()
        is_component = is_comp_raw in ("TRUE", "1", "YES", "はい")
        data = {
            "name":             normalized.get("name") or None,
            "jan_code":         normalized.get("jan_code") or None,
            "spec":             normalized.get("spec") or None,
            "buy_url":          normalized.get("buy_url") or None,
            "price":            to_float(normalized.get("price")),
            "set_size":         to_int(normalized.get("set_size"), 1),
            "rakuten_item_url": normalized.get("rakuten_item_url") or None,
            "rakuten_sku_id":   normalized.get("rakuten_sku_id") or None,
            "supplier":         normalized.get("supplier") or None,
            "standard_stock":   to_int(normalized.get("standard_stock"), 0),
            "stock":            to_int(normalized.get("stock"), 0),
            "inbound":          to_int(normalized.get("inbound"), 0),
            "sales_30_recent":  to_int(normalized.get("sales_30_recent"), 0),
            "sales_30_prev":    to_int(normalized.get("sales_30_prev"), 0),
            "customer_memo":    normalized.get("customer_memo") or None,
            "notes":            normalized.get("notes") or None,
            "memo":             normalized.get("memo") or None,
            "set_components":   normalized.get("set_components") or None,
            "is_component":     is_component,
        }

        existing = db.query(RakutenProduct).filter(RakutenProduct.sku == sku).first()
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            updated += 1
        else:
            p = RakutenProduct(sku=sku, **data)
            db.add(p)
            created += 1

    db.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


# ============================================================
# 仕入れ管理（インボイスExcel読み込み）
# ============================================================

class RakutenInvoiceItemIn(BaseModel):
    sku: str
    name_jp: str = ""
    qty: int
    unit_price_cny: float

class RakutenInvoiceIn(BaseModel):
    invoice_no: str = ""
    invoice_date: str = ""
    exchange_rate: float
    domestic_freight: float = 0
    international_freight: float = 0
    items: List[RakutenInvoiceItemIn]

@router.post("/invoices/parse-excel")
async def rakuten_parse_excel(file: UploadFile = File(...)):
    """タオタロウ形式ExcelをパースしてSKU・単価を返す"""
    import openpyxl
    content = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(400, f"Excel読み込みエラー: {str(e)}")

    ws = wb.active
    invoice_no = ""
    for row in ws.iter_rows(min_row=1, max_row=15, values_only=True):
        for cell in row:
            if cell and str(cell).startswith("VIP"):
                invoice_no = str(cell)
                break

    header_row = None
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), 1):
        if row[0] == "10) Name of Commodity":
            header_row = i + 1
            break

    if not header_row:
        raise HTTPException(400, "商品データが見つかりません")

    items = []
    domestic_freight = international_freight = 0
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
            sku = str(int(row[12])) if row[12] and isinstance(row[12], (int, float)) else str(row[12] or "")
            items.append({
                "sku": sku,
                "name_jp": str(row[2] or ""),
                "qty": int(row[6]) if row[6] else 0,
                "unit_price_cny": float(row[7]) if row[7] else 0,
                "total_price_cny": float(row[8]) if row[8] else 0,
            })

    return {
        "invoice_no": invoice_no,
        "domestic_freight": domestic_freight,
        "international_freight": international_freight,
        "items": items,
    }

@router.post("/invoices/calculate")
def rakuten_calculate_cost(data: RakutenInvoiceIn):
    total_cny = sum(i.qty * i.unit_price_cny for i in data.items)
    total_freight = data.domestic_freight + data.international_freight
    result = []
    for item in data.items:
        item_total = item.qty * item.unit_price_cny
        freight_alloc = (item_total / total_cny * total_freight) if total_cny > 0 else 0
        cost_jpy = ((item_total + freight_alloc) / item.qty * data.exchange_rate) if item.qty > 0 else 0
        result.append({**item.model_dump(), "total_price_cny": round(item_total, 2),
                        "freight_alloc_cny": round(freight_alloc, 2), "cost_jpy": round(cost_jpy, 1)})
    return {"items": result, "total_cny": round(total_cny, 2),
            "total_freight_cny": round(total_freight, 2),
            "grand_total_jpy": round((total_cny + total_freight) * data.exchange_rate, 0)}

@router.post("/invoices/save")
def rakuten_save_invoice(data: RakutenInvoiceIn, db: Session = Depends(get_db)):
    total_cny = sum(i.qty * i.unit_price_cny for i in data.items)
    total_freight = data.domestic_freight + data.international_freight
    updated = 0
    for item in data.items:
        item_total = item.qty * item.unit_price_cny
        freight_alloc = (item_total / total_cny * total_freight) if total_cny > 0 else 0
        cost_jpy = round(((item_total + freight_alloc) / item.qty * data.exchange_rate), 1) if item.qty > 0 else 0
        product = db.query(RakutenProduct).filter(RakutenProduct.sku == item.sku, RakutenProduct.is_active == True).first()
        if product:
            product.cost_jpy = cost_jpy
            updated += 1
    db.commit()
    return {"updated": updated}


# ============================================================
# RMS API 連携
# ============================================================

@router.get("/rms/debug-orders")
async def debug_rms_orders(db: Session = Depends(get_db)):
    """デバッグ用: searchOrderの生レスポンスを返す（直近3日）"""
    import json, base64, httpx
    from datetime import datetime, timedelta
    settings = _get_or_create_settings(db)
    if not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "APIキーが設定されていません")
    token = base64.b64encode(f"{settings.rms_service_secret}:{settings.rms_license_key}".encode()).decode()
    headers = {"Authorization": f"ESA {token}", "Content-Type": "application/json; charset=utf-8"}
    now = datetime.now()
    body = {
        "dateType": 1,
        "startDatetime": (now - timedelta(days=3)).strftime("%Y-%m-%dT00:00:00+0900"),
        "endDatetime": now.strftime("%Y-%m-%dT23:59:59+0900"),
        "PaginationRequestModel": {"requestRecordsAmount": 10, "requestPage": 1},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.rms.rakuten.co.jp/es/2.0/order/searchOrder",
            headers=headers,
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
    return {"status": res.status_code, "body": res.json()}


@router.post("/rms/test")
async def test_rms_connection(db: Session = Depends(get_db)):
    """RMS API 接続テスト"""
    from app.services.rakuten_rms import test_connection
    settings = _get_or_create_settings(db)
    if not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "APIキーが設定されていません")
    result = await test_connection(settings.rms_service_secret, settings.rms_license_key)
    if not result["ok"]:
        raise HTTPException(502, f"接続失敗 (HTTP {result.get('status')}): {result.get('detail', '')}")
    return {"ok": True}


_price_sync_status = {"running": False, "result": None}

@router.get("/rms/sync-prices/status")
def get_price_sync_status():
    return _price_sync_status

@router.post("/rms/sync-prices")
async def sync_prices_from_rms(db: Session = Depends(get_db)):
    """RMS Items Search APIから商品の売価をバックグラウンドで取得"""
    import base64, httpx, asyncio
    settings = _get_or_create_settings(db)
    if not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません。")

    if _price_sync_status["running"]:
        return {"ok": True, "message": "同期中です。しばらくお待ちください。", **_price_sync_status}

    token = base64.b64encode(
        f"{settings.rms_service_secret}:{settings.rms_license_key}".encode()
    ).decode()
    headers = {"Authorization": f"ESA {token}"}
    products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
    product_data = [(p.id, p.rakuten_sku_id or p.sku or "") for p in products]

    from app.core.database import SessionLocal

    async def do_sync():
        _price_sync_status["running"] = True
        _price_sync_status["result"] = None
        sku_price_map = {}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                offset = 0
                retry = 0
                while True:
                    res = await client.get(
                        "https://api.rms.rakuten.co.jp/es/2.0/items/search",
                        headers=headers,
                        params={"offset": offset},
                    )
                    if res.status_code == 429:
                        if retry >= 5:
                            break
                        await asyncio.sleep(2 ** retry)
                        retry += 1
                        continue
                    if res.status_code != 200:
                        break
                    retry = 0
                    data = res.json()
                    results = data.get("results", [])
                    if not results:
                        break
                    for entry in results:
                        item = entry.get("item", {})
                        for variant_key, variant_data in item.get("variants", {}).items():
                            price = variant_data.get("standardPrice")
                            if price is not None:
                                sku_price_map[variant_key] = float(price)
                    total = data.get("numFound", 0)
                    offset += len(results)
                    if offset >= total:
                        break
                    await asyncio.sleep(0.3)

            updated = 0
            with SessionLocal() as session:
                for pid, key in product_data:
                    if key and key in sku_price_map:
                        p = session.query(RakutenProduct).filter(RakutenProduct.id == pid).first()
                        if p:
                            p.selling_price = sku_price_map[key]
                            updated += 1
                session.commit()

            _price_sync_status["result"] = {"ok": True, "fetched_variants": len(sku_price_map), "updated_products": updated}
        except Exception as e:
            _price_sync_status["result"] = {"ok": False, "error": str(e)}
        finally:
            _price_sync_status["running"] = False

    asyncio.create_task(do_sync())
    return {"ok": True, "message": "バックグラウンドで売価取得を開始しました。/status で進捗確認できます。"}


@router.post("/rms/sync")
async def sync_sales_from_rms(db: Session = Depends(get_db)):
    """楽天RMS APIから受注データを取得し、バリエーション別30日販売数を更新"""
    from app.services.rakuten_rms import fetch_sales_by_sku
    settings = _get_or_create_settings(db)
    if not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません。楽天設定から登録してください。")

    try:
        sku_sales = await fetch_sales_by_sku(
            settings.rms_service_secret,
            settings.rms_license_key,
            days=60,
        )
    except Exception as e:
        raise HTTPException(502, f"楽天APIエラー: {str(e)}")

    # バリエーション商品(is_component=False, set_components あり)の販売数を更新
    updated = 0
    products = db.query(RakutenProduct).filter(
        RakutenProduct.is_active == True,
        RakutenProduct.is_component == False,
    ).all()

    for p in products:
        # 楽天SKU管理番号 または 商品管理番号(sku)で照合
        sales = sku_sales.get(p.rakuten_sku_id or "") or sku_sales.get(p.sku or "") or {}
        if sales:
            p.sales_30_recent  = sales.get("recent", 0)
            p.sales_30_prev    = sales.get("prev",   0)
            p.sales_90         = sales.get("total_90", 0)
            p.stockout_days_90 = sales.get("stockout_days", 0)
            p.sales_updated_at = datetime.now()
            updated += 1

    db.commit()
    return {
        "ok": True,
        "synced_skus": len(sku_sales),
        "updated_products": updated,
        "last_sync": datetime.now().isoformat(),
    }
