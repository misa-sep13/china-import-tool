from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone
from app.core.database import get_db
from app.models.product import Product

router = APIRouter(prefix="/products", tags=["products"])

class ProductCreate(BaseModel):
    sku: str
    fnsku: Optional[str] = ""
    asin: Optional[str] = ""
    name: Optional[str] = ""
    amazon_url: Optional[str] = ""
    buy_url: Optional[str] = ""
    photo_url: Optional[str] = ""
    color: Optional[str] = ""
    size: Optional[str] = ""
    price: Optional[float] = 0
    repack: Optional[str] = ""
    note: Optional[str] = ""
    set_size: Optional[int] = 1
    extra_stock: Optional[int] = 0
    amazon_fee_rate: Optional[float] = 0.1

class ProductUpdate(ProductCreate):
    sku: Optional[str] = None

class ProductOut(ProductCreate):
    id: int
    no: Optional[int] = None
    order_qty: int = 0
    is_active: bool = True
    selling_price: Optional[float] = None
    fba_fee: Optional[float] = None
    fees_updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

@router.get("/", response_model=List[ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.query(Product).filter(Product.is_active == True).order_by(Product.no).all()

@router.post("/fba-import", response_model=dict)
def import_from_fba(db: Session = Depends(get_db)):
    try:
        from app.services.amazon_api import fetch_inventory
        inventory = fetch_inventory()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SP-APIエラー: {str(e)}")

    added = 0
    skipped = 0
    fixed = 0
    for fnsku, item in inventory.items():
        asin = item.get("asin", "")
        api_sku = item.get("sku", "")

        # SKUで既存商品を検索してFNSKUを修正
        if api_sku:
            by_sku = db.query(Product).filter(Product.sku == api_sku).first()
            if by_sku:
                if by_sku.fnsku != fnsku:
                    by_sku.fnsku = fnsku
                    fixed += 1
                else:
                    skipped += 1
                continue

        # FNSKUで既存商品があればスキップ
        if db.query(Product).filter(Product.fnsku == fnsku).first():
            skipped += 1
            continue

        # 新規追加（SKUはSP-APIのSKUを使用）
        sku = api_sku or fnsku
        if db.query(Product).filter(Product.sku == sku).first():
            skipped += 1
            continue
        max_no = db.query(Product).count()
        p = Product(sku=sku, fnsku=fnsku, asin=asin, name="", no=max_no + 1)
        db.add(p)
        added += 1

    db.commit()
    return {"added": added, "skipped": skipped, "fixed": fixed}

@router.post("/", response_model=ProductOut)
def create_product(data: ProductCreate, db: Session = Depends(get_db)):
    existing = db.query(Product).filter(Product.sku == data.sku).first()
    if existing:
        raise HTTPException(status_code=400, detail="SKUが既に存在します")
    max_no = db.query(Product).count()
    p = Product(**data.model_dump(), no=max_no + 1)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p

@router.put("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, data: ProductUpdate, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="商品が見つかりません")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p

@router.post("/refresh-fees")
def refresh_fees(db: Session = Depends(get_db)):
    """全商品の販売価格・FBA手数料をSP-APIから取得してDBに保存"""
    from app.core.config import settings as app_settings
    if not app_settings.SP_API_REFRESH_TOKEN:
        raise HTTPException(status_code=400, detail="SP-API未設定")

    products = db.query(Product).filter(Product.is_active == True, Product.sku != None).all()
    sku_list = [p.sku for p in products if p.sku]
    if not sku_list:
        return {"updated": 0}

    from app.services.amazon_api import fetch_prices_and_fees
    fees_map = fetch_prices_and_fees(sku_list)

    now = datetime.now(timezone.utc)
    updated = 0
    for p in products:
        info = fees_map.get(p.sku)
        if not info:
            continue
        if info["selling_price"] is not None:
            p.selling_price = info["selling_price"]
        if info["fba_fee"] is not None:
            p.fba_fee = info["fba_fee"]
        p.fees_updated_at = now
        updated += 1

    db.commit()
    return {"updated": updated}


@router.delete("/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="商品が見つかりません")
    p.is_active = False
    db.commit()
    return {"ok": True}
