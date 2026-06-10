from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from datetime import date, datetime
import csv, io, codecs
from pydantic import BaseModel
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
    lead_days:         int   = 20
    target_days:       int   = 30
    safety_stock_rate: float = 0.10
    threshold_days:    int   = 60
    super_sale_enabled: bool = False
    super_sale_mode:   str   = 'A'
    super_sale_start:  Optional[date] = None
    super_sale_end:    Optional[date] = None

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
    sku:             str
    name:            Optional[str] = None
    jan_code:        Optional[str] = None
    buy_url:         Optional[str] = None
    price:           Optional[float] = None
    set_size:        int = 1
    stock:           int = 0
    inbound:         int = 0
    sales_30_recent: int = 0
    sales_30_prev:   int = 0
    memo:            Optional[str] = None
    is_active:       bool = True

class RakutenProductOut(RakutenProductIn):
    id:               int
    sales_updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

@router.get("/products", response_model=List[RakutenProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.query(RakutenProduct).filter(RakutenProduct.is_active == True).order_by(RakutenProduct.id).all()

@router.post("/products", response_model=RakutenProductOut)
def create_product(data: RakutenProductIn, db: Session = Depends(get_db)):
    if db.query(RakutenProduct).filter(RakutenProduct.sku == data.sku).first():
        raise HTTPException(400, "SKUが既に存在します")
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

    # スーパーセールmodeB: 前回のセール販売数（簡易: super_sale_qty は未来の実装）
    super_sale_qty = 0  # TODO: 実装時に商品ごとのセール数を参照

    products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
    items = []
    for p in products:
        ordered = ordered_by_sku.get(p.sku, 0) or 0
        calc = calc_rakuten_order(
            stock=p.stock or 0,
            inbound=p.inbound or 0,
            ordered=ordered,
            sales_30_recent=p.sales_30_recent or 0,
            sales_30_prev=p.sales_30_prev or 0,
            super_sale_qty=super_sale_qty,
            s=s,
        )
        items.append({
            "product_id":     p.id,
            "sku":            p.sku or "",
            "name":           p.name or "",
            "jan_code":       p.jan_code or "",
            "buy_url":        p.buy_url or "",
            "set_size":       p.set_size or 1,
            "stock":          p.stock or 0,
            "inbound":        p.inbound or 0,
            "ordered":        ordered,
            "total_stock":    calc.total_stock,
            "daily_avg":      calc.daily_avg,
            "days_left":      calc.days_left,
            "growth_rate":    calc.growth_rate,
            "predicted_30":   calc.predicted_30,
            "lead_sales":     calc.lead_sales,
            "safety_stock":   calc.safety_stock,
            "order_qty":      calc.order_qty,
            "needs_order":    calc.needs_order,
            "sales_30_recent": p.sales_30_recent or 0,
            "sales_30_prev":   p.sales_30_prev or 0,
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
        .filter(RakutenOrderHistory.is_deleted == False)
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
# CSV インポート / テンプレートDL
# ============================================================

CSV_COLUMNS = [
    "sku", "name", "jan_code", "buy_url", "price",
    "set_size", "stock", "inbound",
    "sales_30_recent", "sales_30_prev", "memo",
]

CSV_COLUMN_LABELS = {
    "sku":             "商品管理番号(SKU)※必須",
    "name":            "商品名",
    "jan_code":        "JANコード",
    "buy_url":         "仕入れURL",
    "price":           "仕入れ値(元)",
    "set_size":        "セット入数",
    "stock":           "実在庫(手持ち)",
    "inbound":         "輸送中",
    "sales_30_recent": "直近30日販売数",
    "sales_30_prev":   "60日前〜31日前の販売数",
    "memo":            "メモ",
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
        "ITEM-001", "サンプル商品A", "4900000000001",
        "https://item.taobao.com/xxx", "12.5",
        "1", "100", "0", "45", "40", "メモ例",
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
            p.sku or "", p.name or "", p.jan_code or "",
            p.buy_url or "", p.price if p.price is not None else "",
            p.set_size or 1, p.stock or 0, p.inbound or 0,
            p.sales_30_recent or 0, p.sales_30_prev or 0, p.memo or "",
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

        data = {
            "name":            normalized.get("name") or None,
            "jan_code":        normalized.get("jan_code") or None,
            "buy_url":         normalized.get("buy_url") or None,
            "price":           to_float(normalized.get("price")),
            "set_size":        to_int(normalized.get("set_size"), 1),
            "stock":           to_int(normalized.get("stock"), 0),
            "inbound":         to_int(normalized.get("inbound"), 0),
            "sales_30_recent": to_int(normalized.get("sales_30_recent"), 0),
            "sales_30_prev":   to_int(normalized.get("sales_30_prev"), 0),
            "memo":            normalized.get("memo") or None,
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
