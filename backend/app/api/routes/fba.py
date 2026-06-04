from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.product import Product
import time

router = APIRouter(prefix="/fba", tags=["fba"])

@router.post("/import")
def import_from_fba(db: Session = Depends(get_db)):
    try:
        from app.services.amazon_api import fetch_inventory
        inventory = fetch_inventory()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SP-APIエラー: {str(e)}")

    added = 0
    skipped = 0
    seen_skus = set()
    for fnsku, item in inventory.items():
        asin = item.get("asin", "")
        sku = asin or fnsku
        if sku in seen_skus:
            skipped += 1
            continue
        existing = db.query(Product).filter(
            (Product.fnsku == fnsku) | (Product.asin == asin) | (Product.sku == sku)
        ).first()
        if existing:
            skipped += 1
            continue
        max_no = db.query(Product).count() + added
        p = Product(sku=sku, fnsku=fnsku, asin=asin, name="", no=max_no + 1)
        db.add(p)
        seen_skus.add(sku)
        added += 1

    db.commit()
    return {"added": added, "skipped": skipped}


@router.post("/fetch-names")
def fetch_product_names(db: Session = Depends(get_db)):
    from app.services.amazon_api import fetch_item_name

    products = db.query(Product).filter(
        (Product.name == "") | (Product.name == None),
        Product.asin != "",
        Product.asin != None,
    ).all()

    updated = 0
    failed = 0
    for p in products:
        try:
            name = fetch_item_name(p.asin)
            if name:
                p.name = name
                updated += 1
            time.sleep(0.5)
        except Exception:
            failed += 1

    db.commit()
    return {"updated": updated, "failed": failed, "total": len(products)}
