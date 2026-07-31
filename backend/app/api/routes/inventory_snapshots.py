"""月末（期末）在庫金額のスナップショット。

在庫数はマスタに現在値しか持たないため、月次・決算で必要になる期末在庫金額を
後から算出できるよう、確定時点のSKU別在庫数と原価を保存する。
楽天とAmazonは別々に管理する（在庫の持ち方も原価の持ち方も異なるため）。
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.inventory_snapshot import InventorySnapshot
from app.models.product import Product
from app.models.rakuten_product import RakutenProduct

router = APIRouter(prefix="/inventory-snapshots", tags=["inventory-snapshots"])

PLATFORMS = ("rakuten", "amazon")
CATEGORY_LABEL = {"china": "中国輸入", "manufacturer": "日本メーカー品"}


def _prev_month(today: date | None = None) -> str:
    d = today or date.today()
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return f"{y:04d}-{m:02d}"


def _validate_period(period: str | None) -> str:
    p = (period or "").strip() or _prev_month()
    parts = p.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or not parts[0].isdigit() or not parts[1].isdigit():
        raise HTTPException(400, "periodは YYYY-MM 形式で指定してください")
    if not 1 <= int(parts[1]) <= 12:
        raise HTTPException(400, "periodの月が不正です")
    return f"{int(parts[0]):04d}-{int(parts[1]):02d}"


def _collect_rakuten(db: Session) -> list[dict]:
    """楽天の実在庫スナップショット。

    セット販売ページの在庫は構成単品在庫から算出した見かけの数なので、
    二重計上を避けるため set_components を持つ商品は対象外にする。
    """
    from app.api.routes.rakuten import _is_manufacturer_product

    rows = []
    products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
    for p in products:
        if p.set_components:
            continue
        stock = p.stock or 0
        if stock <= 0:
            continue
        cost = p.cost_jpy or 0
        rows.append({
            "category": "manufacturer" if _is_manufacturer_product(p) else "china",
            "sku": p.sku or "",
            "name": p.name or "",
            "supplier": p.supplier or "",
            "stock": stock,
            "cost_jpy": cost,
            "amount": round(stock * cost),
        })
    return rows


def _collect_amazon(db: Session) -> list[dict]:
    """Amazon(FBA)の実在庫スナップショット。

    在庫はDBに持たずSP-APIから都度取得しているため、確定時にAPIを叩いて取得する。
    原価は商品マスタの price（円・1個あたり）を使う（分析画面と同じ扱い）。
    """
    from app.services.amazon_api import fetch_inventory

    try:
        inventory = fetch_inventory()
    except Exception as e:
        raise HTTPException(502, f"SP-APIから在庫を取得できませんでした: {e}")

    stock_by_sku: dict[str, int] = {}
    name_by_sku: dict[str, str] = {}
    for item in inventory.values():
        sku = item.get("sku") or item.get("fnsku") or ""
        if not sku:
            continue
        stock_by_sku[sku] = stock_by_sku.get(sku, 0) + (item.get("available") or 0)
        if item.get("name"):
            name_by_sku.setdefault(sku, item["name"])

    products = {p.sku: p for p in db.query(Product).filter(Product.is_active == True).all() if p.sku}
    rows = []
    for sku, stock in stock_by_sku.items():
        if stock <= 0:
            continue
        p = products.get(sku)
        supplier = (p.supplier or "") if p else ""
        is_manu = bool(supplier) and "タオタロウ" not in supplier
        cost = (p.price or 0) if p else 0
        rows.append({
            "category": "manufacturer" if is_manu else "china",
            "sku": sku,
            "name": (p.name if p and p.name else name_by_sku.get(sku, "")),
            "supplier": supplier,
            "stock": stock,
            "cost_jpy": cost,
            "amount": round(stock * cost),
            "note": None if p else "商品マスタ未登録（原価0で計上）",
        })
    return rows


def _save(db: Session, period: str, platform: str, rows: list[dict]) -> dict:
    # 同じ月・同じプラットフォームの確定分は入れ替える（何度実行しても二重にならない）
    db.query(InventorySnapshot).filter(
        InventorySnapshot.period == period,
        InventorySnapshot.platform == platform,
    ).delete(synchronize_session=False)
    for r in rows:
        db.add(InventorySnapshot(
            period=period, platform=platform,
            category=r.get("category") or "china",
            sku=r.get("sku") or "", name=r.get("name") or "",
            supplier=r.get("supplier") or "",
            stock=int(r.get("stock") or 0),
            cost_jpy=float(r.get("cost_jpy") or 0),
            amount=float(r.get("amount") or round((r.get("stock") or 0) * (r.get("cost_jpy") or 0))),
            note=r.get("note"),
        ))
    db.commit()
    total = sum(float(r.get("amount") or 0) for r in rows)
    by_cat: dict[str, float] = {}
    for r in rows:
        by_cat[r.get("category") or "china"] = by_cat.get(r.get("category") or "china", 0) + float(r.get("amount") or 0)
    no_cost = [r["sku"] for r in rows if not r.get("cost_jpy")]
    return {
        "period": period, "platform": platform,
        "items": len(rows), "total_amount": round(total),
        "by_category": {k: round(v) for k, v in by_cat.items()},
        "no_cost_skus": no_cost,
    }


class CaptureIn(BaseModel):
    period: str | None = None      # 未指定なら前月
    platform: str = "rakuten"


@router.post("/capture")
def capture_snapshot(data: CaptureIn, db: Session = Depends(get_db)):
    """現在の在庫を、指定した月の期末在庫として確定する。"""
    period = _validate_period(data.period)
    platform = (data.platform or "rakuten").strip()
    if platform not in PLATFORMS:
        raise HTTPException(400, f"platformは {' / '.join(PLATFORMS)} のいずれかです")
    rows = _collect_rakuten(db) if platform == "rakuten" else _collect_amazon(db)
    if not rows:
        raise HTTPException(400, "在庫のある商品がありません")
    return _save(db, period, platform, rows)


class ImportItem(BaseModel):
    sku: str
    name: str = ""
    supplier: str = ""
    category: str = "china"
    stock: int = 0
    cost_jpy: float = 0


class ImportIn(BaseModel):
    period: str
    platform: str = "rakuten"
    items: list[ImportItem]


@router.post("/import")
def import_snapshot(data: ImportIn, db: Session = Depends(get_db)):
    """過去分をバックアップ等から取り込む（遡って登録する用）。"""
    period = _validate_period(data.period)
    platform = (data.platform or "rakuten").strip()
    if platform not in PLATFORMS:
        raise HTTPException(400, f"platformは {' / '.join(PLATFORMS)} のいずれかです")
    rows = [{**i.model_dump(), "amount": round(i.stock * i.cost_jpy)} for i in data.items]
    return _save(db, period, platform, rows)


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    """月別・プラットフォーム別の期末在庫金額。"""
    rows = (
        db.query(
            InventorySnapshot.period, InventorySnapshot.platform, InventorySnapshot.category,
            func.sum(InventorySnapshot.amount), func.sum(InventorySnapshot.stock), func.count(),
        )
        .group_by(InventorySnapshot.period, InventorySnapshot.platform, InventorySnapshot.category)
        .all()
    )
    periods: dict[str, dict] = {}
    for period, platform, category, amount, stock, cnt in rows:
        p = periods.setdefault(period, {"period": period, "platforms": {}, "total_amount": 0})
        pf = p["platforms"].setdefault(platform, {"total_amount": 0, "categories": {}})
        pf["categories"][category] = {
            "label": CATEGORY_LABEL.get(category, category),
            "amount": round(amount or 0), "stock": int(stock or 0), "sku_count": cnt,
        }
        pf["total_amount"] += round(amount or 0)
        p["total_amount"] += round(amount or 0)
    return {"periods": sorted(periods.values(), key=lambda x: x["period"], reverse=True)}


@router.get("/detail")
def detail(period: str = Query(...), platform: str = Query("rakuten"), db: Session = Depends(get_db)):
    rows = (
        db.query(InventorySnapshot)
        .filter(InventorySnapshot.period == _validate_period(period), InventorySnapshot.platform == platform)
        .order_by(InventorySnapshot.amount.desc())
        .all()
    )
    return {
        "period": period, "platform": platform,
        "items": [{
            "sku": r.sku, "name": r.name, "supplier": r.supplier,
            "category": r.category, "category_label": CATEGORY_LABEL.get(r.category, r.category),
            "stock": r.stock, "cost_jpy": r.cost_jpy, "amount": round(r.amount or 0),
            "note": r.note,
        } for r in rows],
    }


@router.delete("/{period}")
def delete_snapshot(period: str, platform: str = Query("rakuten"), db: Session = Depends(get_db)):
    n = db.query(InventorySnapshot).filter(
        InventorySnapshot.period == _validate_period(period),
        InventorySnapshot.platform == platform,
    ).delete(synchronize_session=False)
    db.commit()
    return {"deleted": n}
