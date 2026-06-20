from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from datetime import date, datetime
import csv, io, json
import uuid, time, threading
from pydantic import BaseModel
import asyncio
from app.core.database import get_db, SessionLocal
from app.models.rakuten_product import RakutenProduct
from app.models.rakuten_order import RakutenOrderHistory
from app.models.rakuten_settings import RakutenSettings
from app.services.rakuten_calc import calc_rakuten_order, RakutenCalcSettings

router = APIRouter(prefix="/rakuten", tags=["rakuten"])


@router.post("/migrate-show-in-orders")
def migrate_show_in_orders(db: Session = Depends(get_db)):
    """一時マイグレーション: show_in_ordersカラム追加＋初期値設定（実行後に削除予定）"""
    from sqlalchemy import text
    try:
        db.execute(text("ALTER TABLE rakuten_products ADD COLUMN show_in_orders BOOLEAN DEFAULT TRUE"))
        db.commit()
        added = True
    except Exception as e:
        db.rollback()
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            added = False
        else:
            raise HTTPException(500, str(e))
    count = db.query(RakutenProduct).filter(RakutenProduct.is_component == True).count()
    db.execute(text("UPDATE rakuten_products SET show_in_orders = FALSE WHERE is_component = TRUE"))
    db.commit()
    return {"column_added": added, "updated_count": count}


def _clean_set_components(sc: Optional[str]) -> Optional[str]:
    """set_componentsのJSON文字列から空エントリ（sku/buy_url/supplier_specが全て空）を除去。全削除なら None を返す。"""
    if not sc:
        return sc
    try:
        items = json.loads(sc)
        filtered = [it for it in items if it.get("sku") or it.get("buy_url") or it.get("supplier_spec")]
        return json.dumps(filtered, ensure_ascii=False) if filtered else None
    except Exception:
        return sc



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
    default_shipping_fee: int = 180
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
    supplier_spec:    Optional[str] = None
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
    shipping_fee:     int = 180
    customer_memo:    Optional[str] = None
    notes:            Optional[str] = None
    memo:             Optional[str] = None
    set_components:   Optional[str] = None  # JSON文字列
    is_component:     bool = False          # 単品（セット構成用内部管理）フラグ
    is_active:        bool = True
    customer_memo:    Optional[str] = None

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
        shipping_fee = p.shipping_fee if p.shipping_fee is not None else 180
        commission = round(selling_price * commission_rate, 0) if selling_price else None
        profit = round(selling_price - (cost_jpy or 0) - (commission or 0) - shipping_fee, 0) if selling_price else None
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
            "shipping_fee": shipping_fee,
            "commission": commission,
            "commission_rate": commission_rate,
            "profit": profit,
            "profit_rate": profit_rate,
            "notes": p.notes,
            "supplier": p.supplier,
            "set_components": p.set_components,
        })
    return result

@router.post("/products", response_model=RakutenProductOut)
def create_product(data: RakutenProductIn, db: Session = Depends(get_db)):
    data.set_components = _clean_set_components(data.set_components)
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
async def update_product(product_id: int, data: RakutenProductIn, db: Session = Depends(get_db)):
    if "set_components" in data.model_fields_set:
        data.set_components = _clean_set_components(data.set_components)
    p = db.query(RakutenProduct).filter(RakutenProduct.id == product_id).first()
    if not p:
        raise HTTPException(404, "商品が見つかりません")
    dup = db.query(RakutenProduct).filter(
        RakutenProduct.sku == data.sku, RakutenProduct.id != product_id
    ).first()
    if dup:
        raise HTTPException(400, "SKUが既に存在します")

    old_stock = p.stock
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)

    # 在庫数が送信された場合はRMSにも反映（値が同じでもセット商品の再計算が必要なため）
    if "stock" in data.model_fields_set and p.sku:
        try:
            settings = db.query(RakutenSettings).first()
            if settings and settings.rms_service_secret and settings.rms_license_key:
                from app.services.rakuten_rms import push_inventory_to_rms
                rms_items = []

                # 自分自身をRMSに反映
                manage_number = p.rakuten_item_url or p.sku.split("_")[0]
                rms_items.append({"manage_number": manage_number, "variant_id": p.sku, "quantity": p.stock})

                # この商品を参照しているセット商品の在庫も自動計算して反映（is_component問わず）
                set_products = db.query(RakutenProduct).filter(
                    RakutenProduct.is_active == True,
                    RakutenProduct.set_components != None,
                ).all()

                # 全商品の現在在庫をまとめて取得
                all_skus = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
                sku_stock = {cp.sku: (cp.stock or 0) for cp in all_skus}
                sku_stock[p.sku] = p.stock  # 今回更新した値で上書き

                for sp in set_products:
                    if sp.id == p.id:
                        continue
                    try:
                        comps = json.loads(sp.set_components or "[]")
                    except Exception:
                        continue
                    if not comps:
                        continue
                    # このセット商品が今回更新した商品を含む場合のみ計算
                    if not any(c.get("sku") == p.sku for c in comps):
                        continue
                    # セット在庫 = min(構成品在庫 ÷ 使用数) の切り捨て
                    set_qty = None
                    for c in comps:
                        c_sku = c.get("sku")
                        c_qty = c.get("qty") or 1
                        if not c_sku:
                            continue
                        avail = sku_stock.get(c_sku, 0) // c_qty
                        set_qty = avail if set_qty is None else min(set_qty, avail)

                    if set_qty is not None:
                        sp.stock = set_qty
                        sp_manage = sp.rakuten_item_url or sp.sku.split("_")[0]
                        rms_items.append({"manage_number": sp_manage, "variant_id": sp.sku, "quantity": set_qty})

                db.commit()

                await push_inventory_to_rms(settings.rms_service_secret, settings.rms_license_key, rms_items)
        except Exception as e:
            import logging
            logging.getLogger("rakuten").warning(f"RMS在庫反映エラー ({p.sku}): {e}")

    return p

@router.post("/products/bulk-update-stock")
async def bulk_update_stock(body: dict, db: Session = Depends(get_db)):
    """複数商品の在庫をまとめて更新してRMSに一括反映
    body: {"updates": [{"id": 1, "stock": 10, "inbound": 0, "standard_stock": 5}, ...]}
    """
    updates = body.get("updates", [])
    if not updates:
        return {"ok": True, "updated": 0}

    settings = _get_or_create_settings(db)
    all_products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
    id_to_product = {p.id: p for p in all_products}
    sku_stock = {p.sku: (p.stock or 0) for p in all_products}

    # Step1: DB更新（全件まとめて）
    updated_skus = set()
    for u in updates:
        p = id_to_product.get(u.get("id"))
        if not p:
            continue
        if "stock" in u:
            p.stock = int(u["stock"])
            sku_stock[p.sku] = p.stock
            updated_skus.add(p.sku)
        if "inbound" in u:
            p.inbound = int(u["inbound"])
        if "standard_stock" in u:
            p.standard_stock = int(u["standard_stock"])

    # Step2: セット商品の在庫を構成品から再計算
    def _parse(p):
        try: return json.loads(p.set_components or "[]")
        except: return []

    rms_items = []
    for p in all_products:
        comps = _parse(p)
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

    db.commit()

    # Step3: RMSに一括反映（更新したSKU＋影響したセット商品）
    if settings and settings.rms_service_secret and settings.rms_license_key:
        from app.services.rakuten_rms import push_inventory_to_rms
        for p in all_products:
            if p.sku in updated_skus or (p.set_components and any(c.get("sku") in updated_skus for c in _parse(p))):
                manage_number = p.rakuten_item_url or p.sku.split("_")[0]
                rms_items.append({"manage_number": manage_number, "variant_id": p.sku, "quantity": sku_stock.get(p.sku, 0)})
        if rms_items:
            await push_inventory_to_rms(settings.rms_service_secret, settings.rms_license_key, rms_items)

    return {"ok": True, "updated": len(updated_skus), "rms_pushed": len(rms_items)}


@router.post("/products/bulk-set-components")
def bulk_set_components(body: dict, db: Session = Depends(get_db)):
    """SKUをキー、set_componentsをJSONとして受け取り一括更新"""
    # body: {"updates": [{"sku": "y76_b-b", "set_components": "[...]"}, ...]}
    updates = body.get("updates", [])
    ok = 0
    for item in updates:
        sku = item.get("sku")
        comps = item.get("set_components")
        if not sku or comps is None:
            continue
        p = db.query(RakutenProduct).filter(RakutenProduct.sku == sku, RakutenProduct.is_active == True).first()
        if p:
            p.set_components = comps
            ok += 1
    db.commit()
    return {"updated": ok}

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
    sku_to_product = {p.sku: p for p in all_products}

    # 「親発注品」= is_component=False かつ buy_url あり かつ set_components あり
    # （例: y34=3本セット、y15=天使の羽+風船セット）→ セットごと仕入れる商品
    parent_orders: dict[str, RakutenProduct] = {
        p.sku: p for p in all_products
        if not p.is_component
        and (p.buy_url or "").strip()
        and p.set_components
    }

    # 親発注品のset_components内SKU → 個別に推奨リストへ出さない
    parent_comp_skus: set[str] = set()
    for p in parent_orders.values():
        try:
            comps = json.loads(p.set_components or "[]")
            parent_comp_skus.update(c["sku"] for c in comps if c.get("sku"))
        except Exception:
            pass

    # セット商品の販売実績を構成単品SKUへ按分（親発注品は除く）
    # バリエーション（例: y76_b-w）が参照する単品（例: y76_black）は、
    # is_component=False（一覧に表示する単品）でも日販計算には合算する
    unit_sales: dict[str, dict] = {}
    referenced_skus: set[str] = set()

    for p in all_products:
        if p.is_component or not p.set_components:
            continue
        if p.sku in parent_orders:
            continue  # 親発注品は後で別処理
        try:
            comps = json.loads(p.set_components or "[]")
        except Exception:
            comps = []
        for c in comps:
            unit_sku = c.get("sku", "")
            qty = c.get("qty", 1) or 1
            if not unit_sku:
                continue
            referenced_skus.add(unit_sku)
            if unit_sku not in unit_sales:
                unit_sales[unit_sku] = {"recent": 0, "prev": 0}
            unit_sales[unit_sku]["recent"] += (p.sales_30_recent or 0) * qty
            unit_sales[unit_sku]["prev"]   += (p.sales_30_prev   or 0) * qty

    # 親発注品の販売数 = 親自身の直販 + コンポーネントSKUの直販合計
    for p_sku, p in parent_orders.items():
        try:
            comps = json.loads(p.set_components or "[]")
        except Exception:
            comps = []
        comp_recent = sum(
            (sku_to_product[c["sku"]].sales_30_recent or 0) * (c.get("qty", 1) or 1)
            for c in comps if c.get("sku") and c["sku"] in sku_to_product
        )
        comp_prev = sum(
            (sku_to_product[c["sku"]].sales_30_prev or 0) * (c.get("qty", 1) or 1)
            for c in comps if c.get("sku") and c["sku"] in sku_to_product
        )
        unit_sales[p_sku] = {
            "recent": (p.sales_30_recent or 0) + comp_recent,
            "prev":   (p.sales_30_prev   or 0) + comp_prev,
        }

    # buy_url あり + 親発注品のコンポーネントでない + (内部管理SKU or バリエーションから参照される単品)
    singles = [
        p for p in all_products
        if (p.is_component or p.sku in referenced_skus)
        and (p.buy_url or "").strip()
        and p.sku not in parent_comp_skus
    ]

    # 通常単品 + 親発注品を合わせて計算
    all_order_items = singles + list(parent_orders.values())

    items = []
    for p in all_order_items:
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
        try:
            sc_parsed = json.loads(p.set_components) if p.set_components else []
        except Exception:
            sc_parsed = []
        items.append({
            "product_id":      p.id,
            "sku":             p.sku or "",
            "name":            p.name or "",
            "jan_code":        p.jan_code or "",
            "buy_url":         p.buy_url or "",
            "set_size":        p.set_size or 1,
            "set_components":  sc_parsed,
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


@router.get("/orders/all-products")
def get_all_products_order(db: Session = Depends(get_db)):
    """全商品（is_component=False）を発注推奨リストと同じ形式で返す"""
    settings_row = _get_or_create_settings(db)
    s = RakutenCalcSettings(
        lead_days=settings_row.lead_days,
        target_days=settings_row.target_days,
        safety_stock_rate=settings_row.safety_stock_rate,
        threshold_days=settings_row.threshold_days,
    )
    ordered_by_sku = dict(
        db.query(RakutenOrderHistory.sku, func.sum(RakutenOrderHistory.qty))
        .filter(RakutenOrderHistory.is_delivered == False, RakutenOrderHistory.is_deleted == False)
        .group_by(RakutenOrderHistory.sku)
        .all()
    )
    all_products = db.query(RakutenProduct).filter(
        RakutenProduct.is_active == True,
    ).all()

    # is_component=False・buy_urlあり（内部SKUのみ除外、セット組・本体はすべて表示）
    targets = [
        p for p in all_products
        if not p.is_component
        and (p.buy_url or "").strip()
    ]
    items = []
    for p in targets:
        ordered = ordered_by_sku.get(p.sku, 0) or 0
        calc = calc_rakuten_order(
            stock=p.stock or 0,
            inbound=p.inbound or 0,
            ordered=ordered,
            sales_30_recent=p.sales_30_recent or 0,
            sales_30_prev=p.sales_30_prev or 0,
            super_sale_qty=0,
            sales_90=getattr(p, 'sales_90', None) or 0,
            stockout_days_90=getattr(p, 'stockout_days_90', None) or 0,
            s=s,
        )
        sc_parsed = []
        if p.set_components:
            try:
                sc_parsed = json.loads(p.set_components) if isinstance(p.set_components, str) else (p.set_components or [])
            except Exception:
                sc_parsed = []
        items.append({
            "product_id":      p.id,
            "sku":             p.sku or "",
            "name":            p.name or "",
            "buy_url":         p.buy_url or "",
            "set_components":  sc_parsed,
            "stock":           p.stock or 0,
            "inbound":         p.inbound or 0,
            "ordered":         ordered,
            "total_stock":     calc.total_stock,
            "daily_avg":       calc.daily_avg,
            "days_left":       calc.days_left,
            "growth_rate":     calc.growth_rate,
            "order_qty":       calc.order_qty,
            "needs_order":     calc.needs_order,
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
# Excel発注書ダウンロード（タオタロウ形式）
# ============================================================

@router.post("/orders/excel")
def download_order_excel(body: dict, db: Session = Depends(get_db)):
    """発注リストをタオタロウ形式Excelで出力"""
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
        # 本体行（set_componentsありかつspec空の場合はスキップ）
        if not (p.set_components and not (p.spec or "").strip()):
            excel_items.append({
                "buy_url":       p.buy_url or "",
                "supplier_spec": getattr(p, "supplier_spec", "") or "",
                "spec":          p.spec or "",
                "qty":           qty,
                "price":         p.price or 0,
                "customer_memo": p.customer_memo or "",
                "notes":         p.notes or "",
            })
        # set_componentsを展開して追加行として出力
        # set_components内のbuy_url/supplier_spec/priceを優先、なければ商品マスタから取得
        try:
            comps = json.loads(p.set_components or "[]")
        except Exception:
            comps = []
        for comp in comps:
            comp_sku = comp.get("sku")
            comp_qty = comp.get("qty", 1)
            # set_components内に直接情報がある場合はそちらを使う
            comp_url  = comp.get("buy_url", "")
            comp_spec = comp.get("supplier_spec", "")
            comp_price = comp.get("price", None)
            # なければ商品マスタから補完（is_componentのもののみ）
            if not comp_url or not comp_spec or comp_price is None:
                c = db.query(RakutenProduct).filter(RakutenProduct.sku == comp_sku).first() if comp_sku else None
                if c and c.is_component:
                    comp_url   = comp_url   or c.buy_url or ""
                    comp_spec  = comp_spec  or getattr(c, "supplier_spec", "") or ""
                    comp_price = comp_price if comp_price is not None else (c.price or 0)
                elif not comp_url:
                    continue  # URLも商品マスタもなければスキップ
            excel_items.append({
                "buy_url":       comp_url,
                "supplier_spec": comp_spec,
                "spec":          "",
                "qty":           qty * comp_qty,
                "price":         comp_price or 0,
                "customer_memo": comp.get("customer_memo", ""),
                "notes":         comp.get("notes", ""),
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
    "sku", "name", "jan_code", "spec", "buy_url", "supplier_spec", "price",
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
    "supplier_spec":    "仕入れ仕様(中国語)",
    "price":            "単価(元)",
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
            p.buy_url or "", getattr(p, "supplier_spec", "") or "",
            p.price if p.price is not None else "",
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
            p.set_components or "",
            "TRUE" if p.is_component else "FALSE",
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
            "supplier_spec":    normalized.get("supplier_spec") or None,
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
    asin_memo: str = ""  # J列（ASIN/商品番号）：商品内訳メモ

class RakutenInvoiceIn(BaseModel):
    invoice_no: str = ""
    invoice_date: str = ""
    exchange_rate: float
    domestic_freight: float = 0
    international_freight: float = 0
    import_tax_jpy: float = 0  # 輸入税合計（円）：関税＋消費税＋地方消費税
    items: List[RakutenInvoiceItemIn]

@router.post("/invoices/validate-pair")
async def rakuten_validate_pair(
    invoice_file: UploadFile = File(...),
    permit_file: UploadFile = File(...),
):
    """インボイスXLSと輸入許可書PDFのCNY合計が一致するか検証する"""
    import re, openpyxl
    inv_content = await invoice_file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(inv_content))
    except Exception as e:
        raise HTTPException(400, f"インボイス読み込みエラー: {str(e)}")

    ws = wb.active
    header_row = None
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), 1):
        if row[0] == "10) Name of Commodity":
            header_row = i + 1
            break
    if not header_row:
        raise HTTPException(400, "インボイスの商品データが見つかりません")

    total_cny = 0.0
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if row[0] and str(row[0]).startswith("MADE IN"):
            break
        if row[0] is None and row[6] and row[7]:
            total_cny += float(row[6]) * float(row[7])

    permit_content = await permit_file.read()
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(permit_content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        raise HTTPException(400, f"輸入許可書読み込みエラー: {str(e)}")

    m = re.search(r'仕入書価格\s+[A-Z]\s+-\s+CIF\s+-\s+CNY\s+-\s+([\d,\.]+)', text)
    permit_cny = float(m.group(1).replace(",", "")) if m else 0.0

    total_cny = round(total_cny, 2)
    diff = abs(total_cny - permit_cny)
    ok = diff <= 1.0

    return {
        "ok": ok,
        "invoice_cny": total_cny,
        "permit_cny": permit_cny,
        "diff": round(diff, 2),
        "message": "照合OK" if ok else f"金額不一致（インボイス: {total_cny}元、輸入許可書: {permit_cny}元、差額: {round(diff,2)}元）",
    }


@router.post("/invoices/parse-pdf")
async def rakuten_parse_pdf(file: UploadFile = File(...)):
    """輸入許可証PDFから納税額合計・為替レートを抽出"""
    import re, fitz
    content = await file.read()
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:
        raise HTTPException(400, f"PDF読み込みエラー: {str(e)}")

    full_text = ""
    for page in doc:
        from html import unescape
        html = page.get_text("html")
        text = unescape(re.sub('<[^>]+>', '\n', html))
        full_text += text + "\n"

    # 納税額合計：¥25,500 形式
    tax_total = 0
    m = re.search(r'\\([0-9,]+)\s*\n.*?納税額合計', full_text)
    if not m:
        # 数字の後に25,500のような値を探す（文字化けしていても数字は読める）
        # ページ内で最大の¥XXX,XXX を納税額合計とみなす
        amounts = re.findall(r'\\([0-9]{2,3},[0-9]{3})', full_text)
        if amounts:
            values = [int(a.replace(',', '')) for a in amounts]
            tax_total = max(values)
    else:
        tax_total = int(m.group(1).replace(',', ''))

    # 為替レート：CNY - 23.30 形式
    exchange_rate = 0
    m = re.search(r'CNY\s*[-\s]+([0-9]+\.[0-9]+)', full_text)
    if m:
        exchange_rate = float(m.group(1))

    # 個別税額も抽出（関税・消費税・地方消費税）
    taxes = re.findall(r'\\([0-9,]+)', full_text)
    tax_values = sorted([int(t.replace(',', '')) for t in taxes], reverse=True)

    return {
        "import_tax_jpy": tax_total,
        "exchange_rate": exchange_rate,
        "tax_breakdown": tax_values[:10],  # デバッグ用：上位10件
    }


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
            asin_memo = str(row[9]).strip() if len(row) > 9 and row[9] else ""
            items.append({
                "sku": sku,
                "name_jp": str(row[2] or ""),
                "qty": int(row[6]) if row[6] else 0,
                "unit_price_cny": float(row[7]) if row[7] else 0,
                "total_price_cny": float(row[8]) if row[8] else 0,
                "asin_memo": asin_memo,  # J列（ASIN/商品番号）：商品内訳メモ
            })

    return {
        "invoice_no": invoice_no,
        "domestic_freight": domestic_freight,
        "international_freight": international_freight,
        "items": items,
    }

@router.post("/invoices/calculate")
def rakuten_calculate_cost(data: RakutenInvoiceIn, db: Session = Depends(get_db)):
    total_cny = sum(i.qty * i.unit_price_cny for i in data.items)
    total_freight = data.domestic_freight + data.international_freight
    import_tax_jpy = data.import_tax_jpy or 0
    result = []
    for item in data.items:
        item_total = item.qty * item.unit_price_cny
        freight_alloc = (item_total / total_cny * total_freight) if total_cny > 0 else 0
        tax_alloc_jpy = (item_total / total_cny * import_tax_jpy) if total_cny > 0 else 0
        cost_jpy = (((item_total + freight_alloc) * data.exchange_rate + tax_alloc_jpy) / item.qty) if item.qty > 0 else 0
        product = db.query(RakutenProduct).filter(RakutenProduct.sku == item.sku, RakutenProduct.is_active == True).first()
        customer_memo = product.customer_memo if product else None
        result.append({**item.model_dump(), "total_price_cny": round(item_total, 2),
                        "freight_alloc_cny": round(freight_alloc, 2),
                        "tax_alloc_jpy": round(tax_alloc_jpy, 0),
                        "cost_jpy": round(cost_jpy, 1),
                        "customer_memo": customer_memo})
    return {"items": result, "total_cny": round(total_cny, 2),
            "total_freight_cny": round(total_freight, 2),
            "import_tax_jpy": import_tax_jpy,
            "grand_total_jpy": round((total_cny + total_freight) * data.exchange_rate + import_tax_jpy, 0)}

@router.post("/invoices/save")
def rakuten_save_invoice(data: RakutenInvoiceIn, db: Session = Depends(get_db)):
    total_cny = sum(i.qty * i.unit_price_cny for i in data.items)
    total_freight = data.domestic_freight + data.international_freight
    updated = 0
    updated_skus: dict[str, float] = {}  # sku -> cost_jpy

    import_tax_jpy = data.import_tax_jpy or 0
    for item in data.items:
        item_total = item.qty * item.unit_price_cny
        freight_alloc = (item_total / total_cny * total_freight) if total_cny > 0 else 0
        tax_alloc_jpy = (item_total / total_cny * import_tax_jpy) if total_cny > 0 else 0
        product = db.query(RakutenProduct).filter(RakutenProduct.sku == item.sku, RakutenProduct.is_active == True).first()
        if product:
            set_size = product.set_size or 1
            cost_jpy = round((((item_total + freight_alloc) * data.exchange_rate + tax_alloc_jpy) / (item.qty * set_size)), 1) if item.qty > 0 else 0
            product.cost_jpy = cost_jpy
            product.price = round(item.unit_price_cny / set_size, 2) if item.unit_price_cny else product.price
            updated_skus[item.sku] = cost_jpy
            updated += 1

    # set_componentsを持つセット商品の原価を自動再計算
    set_products = db.query(RakutenProduct).filter(
        RakutenProduct.is_active == True,
        RakutenProduct.is_component == False,
        RakutenProduct.set_components != None,
    ).all()
    for sp in set_products:
        try:
            comps = json.loads(sp.set_components or "[]")
        except Exception:
            continue
        total_cost = 0.0
        all_found = True
        for c in comps:
            comp_sku = c.get("sku", "")
            qty = c.get("qty", 1)
            # 更新されたSKUの原価を優先、なければDB値を使用
            if comp_sku in updated_skus:
                comp_cost = updated_skus[comp_sku]
            else:
                comp_product = db.query(RakutenProduct).filter(
                    RakutenProduct.sku == comp_sku, RakutenProduct.is_active == True
                ).first()
                if comp_product and comp_product.cost_jpy:
                    comp_cost = comp_product.cost_jpy
                else:
                    all_found = False
                    break
            total_cost += comp_cost * qty
        if all_found and total_cost > 0:
            sp.cost_jpy = round(total_cost, 1)
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


@router.get("/rms/debug-order-detail")
async def debug_rms_order_detail(db: Session = Depends(get_db)):
    """デバッグ用: getOrderの生レスポンスを返す（直近3日の先頭1件）"""
    import json, base64, httpx
    from datetime import datetime, timedelta
    settings = _get_or_create_settings(db)
    if not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "APIキーが設定されていません")
    token = base64.b64encode(f"{settings.rms_service_secret}:{settings.rms_license_key}".encode()).decode()
    headers = {"Authorization": f"ESA {token}", "Content-Type": "application/json; charset=utf-8"}
    now = datetime.now()
    # まず注文番号を1件取得
    search_body = {
        "dateType": 1,
        "startDatetime": (now - timedelta(days=3)).strftime("%Y-%m-%dT00:00:00+0900"),
        "endDatetime": now.strftime("%Y-%m-%dT23:59:59+0900"),
        "PaginationRequestModel": {"requestRecordsAmount": 1, "requestPage": 1},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.rms.rakuten.co.jp/es/2.0/order/searchOrder",
            headers=headers,
            content=json.dumps(search_body, ensure_ascii=False).encode("utf-8"),
        )
        data = res.json()
    order_numbers = data.get("orderNumberList", [])
    if not order_numbers:
        return {"error": "注文なし"}
    # getOrderで詳細取得
    async with httpx.AsyncClient(timeout=30) as client:
        res2 = await client.post(
            "https://api.rms.rakuten.co.jp/es/2.0/order/getOrder",
            headers=headers,
            content=json.dumps({"orderNumberList": order_numbers[:1], "version": 10}, ensure_ascii=False).encode("utf-8"),
        )
    return {"status": res2.status_code, "body": res2.json()}


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
                            merchant_sku_id = variant_data.get("merchantDefinedSkuId")
                            if merchant_sku_id:
                                sku_price_map[f"__spec__{variant_key}"] = merchant_sku_id
                    total = data.get("numFound", 0)
                    offset += len(results)
                    if offset >= total:
                        break
                    await asyncio.sleep(0.3)

            updated = 0
            session = SessionLocal()
            try:
                for pid, key in product_data:
                    if not key:
                        continue
                    p = session.query(RakutenProduct).filter(RakutenProduct.id == pid).first()
                    if not p:
                        continue
                    if key in sku_price_map:
                        p.selling_price = sku_price_map[key]
                        updated += 1
                    spec_val = sku_price_map.get(f"__spec__{key}")
                    if spec_val and not p.spec:
                        p.spec = spec_val
                session.commit()
            finally:
                session.close()

            _price_sync_status["result"] = {"ok": True, "fetched_variants": len(sku_price_map), "updated_products": updated}
        except Exception as e:
            _price_sync_status["result"] = {"ok": False, "error": str(e)}
        finally:
            _price_sync_status["running"] = False

    asyncio.create_task(do_sync())
    return {"ok": True, "message": "バックグラウンドで売価取得を開始しました。/status で進捗確認できます。"}


@router.post("/rms/sync-sku-mapping")
async def sync_sku_mapping_from_rms(db: Session = Depends(get_db)):
    """RMS Items APIから商品管理番号(rakuten_item_url)とSKU番号(rakuten_sku_id)を一括取得してDBに保存"""
    import base64, httpx, asyncio
    settings = _get_or_create_settings(db)
    if not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません。")

    token = base64.b64encode(
        f"{settings.rms_service_secret}:{settings.rms_license_key}".encode()
    ).decode()
    headers = {"Authorization": f"ESA {token}"}

    # RMSから全商品のmanageNumber・variantId・merchantDefinedSkuIdを取得
    # variant_key(SKU管理番号) -> {manage_number, merchant_sku_id}
    sku_map: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=60) as client:
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
                raise HTTPException(502, f"RMS API エラー: {res.status_code}")
            retry = 0
            data = res.json()
            results = data.get("results", [])
            if not results:
                break
            for entry in results:
                item = entry.get("item", {})
                manage_number = item.get("manageNumber", "")
                for variant_key, variant_data in item.get("variants", {}).items():
                    merchant_sku_id = variant_data.get("merchantDefinedSkuId") or ""
                    sku_map[variant_key] = {
                        "manage_number": manage_number,
                        "merchant_sku_id": merchant_sku_id,
                    }
            total = data.get("numFound", 0)
            offset += len(results)
            if offset >= total:
                break
            await asyncio.sleep(0.3)

    # DBの商品と照合してrakuten_item_url・rakuten_sku_idを更新
    products = db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all()
    updated = 0
    for p in products:
        if not p.sku:
            continue
        info = sku_map.get(p.sku)
        if info:
            p.rakuten_item_url = info["manage_number"]
            if info["merchant_sku_id"]:
                p.rakuten_sku_id = info["merchant_sku_id"]
            updated += 1
    db.commit()

    return {"ok": True, "fetched_variants": len(sku_map), "updated": updated}


@router.get("/rms/item-sample")
async def rms_item_sample(db: Session = Depends(get_db)):
    """Item API 2.0のレスポンス構造確認用（先頭1件取得）"""
    import base64, httpx
    settings = _get_or_create_settings(db)
    if not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません。")
    token = base64.b64encode(f"{settings.rms_service_secret}:{settings.rms_license_key}".encode()).decode()
    headers = {"Authorization": f"ESA {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(
            "https://api.rms.rakuten.co.jp/es/2.0/items/search",
            headers=headers,
            params={"offset": 0, "limit": 1},
        )
    return {"status": res.status_code, "body": res.json() if res.status_code == 200 else res.text[:1000]}


@router.post("/rms/import-stock")
async def import_stock_from_rms(db: Session = Depends(get_db)):
    """RMSから在庫数を一括取得してDBのstockに保存"""
    from app.services.rakuten_rms import fetch_inventory_from_rms
    settings = _get_or_create_settings(db)
    if not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません。")

    # manageNumberが設定されている商品を対象にする
    # manageNumber = skuの "_" より前の部分（例: y49_pink2 → y49）
    # ただしrakuten_item_urlが設定されていればそちらを優先
    products = db.query(RakutenProduct).filter(
        RakutenProduct.is_active == True,
        RakutenProduct.sku != None,
    ).all()

    items = []
    sku_to_product = {}
    for p in products:
        sku = p.sku or ""
        if not sku:
            continue
        # manageNumber: rakuten_item_url優先、なければskuの"_"前
        if p.rakuten_item_url:
            manage_number = p.rakuten_item_url
        elif "_" in sku:
            manage_number = sku.rsplit("_", maxsplit=sku.count("_"))[0].split("_")[0]
            # y49_pink2 → y49
            manage_number = sku.split("_")[0]
        else:
            manage_number = sku
        items.append({"manage_number": manage_number, "variant_id": sku})
        sku_to_product[sku] = p

    if not items:
        raise HTTPException(400, "対象商品がありません。")

    try:
        rms_stock = await fetch_inventory_from_rms(
            settings.rms_service_secret,
            settings.rms_license_key,
            items,
        )
    except Exception as e:
        raise HTTPException(502, f"楽天APIエラー: {str(e)}")

    import json as _json

    def _parse_comps(p):
        try:
            return _json.loads(p.set_components or "[]")
        except Exception:
            return []

    # Step1: RMSから取得できた在庫を上書き
    updated = 0
    not_found = 0
    for sku, p in sku_to_product.items():
        if sku in rms_stock:
            p.stock = rms_stock[sku]
            updated += 1
        else:
            not_found += 1

    # Step2: セット商品の在庫を構成品から再計算
    all_products = list(sku_to_product.values())
    sku_stock = {p.sku: (p.stock or 0) for p in all_products}
    for p in all_products:
        comps = _parse_comps(p)
        if not comps:
            continue
        # 同一SKUが複数エントリある場合はqtyを合算
        req: dict[str, int] = {}
        for c in comps:
            c_sku = c.get("sku")
            c_qty = c.get("qty") or 1
            if not c_sku:
                continue
            req[c_sku] = req.get(c_sku, 0) + c_qty
        set_qty = None
        for c_sku, c_qty in req.items():
            avail = sku_stock.get(c_sku, 0) // c_qty
            set_qty = avail if set_qty is None else min(set_qty, avail)
        if set_qty is not None:
            p.stock = set_qty
            sku_stock[p.sku] = set_qty

    # Step3: RMSにないSKU（単品販売なし）の在庫をセット商品から逆算
    for p in all_products:
        if p.sku in rms_stock:
            continue
        comps = _parse_comps(p)
        if comps:
            continue
        inferred_qty = 0
        for sp in all_products:
            sp_comps = _parse_comps(sp)
            for c in sp_comps:
                if c.get("sku") == p.sku:
                    inferred_qty += sku_stock.get(sp.sku, 0) * (c.get("qty") or 1)
        if inferred_qty > 0:
            p.stock = inferred_qty
            sku_stock[p.sku] = inferred_qty

    db.commit()
    return {
        "ok": True,
        "updated": updated,
        "not_found": not_found,
        "total_from_rms": len(rms_stock),
    }


# ===== 売上同期（バックグラウンドジョブ） =====
# 受注60日分の取得は数分かかり1リクエストでは502になるため、
# バックグラウンドで実行し、フロントはjob_idでポーリングする。
_sync_jobs: dict = {}
_sync_jobs_lock = threading.Lock()


def _prune_sync_jobs():
    """古い同期ジョブをメモリから掃除（_sync_jobsの肥大化＝メモリリーク防止）"""
    now = time.time()
    with _sync_jobs_lock:
        for jid in [j for j, v in _sync_jobs.items() if now - v.get("started_at", now) > 3600]:
            _sync_jobs.pop(jid, None)
        if len(_sync_jobs) > 20:
            for jid, _ in sorted(_sync_jobs.items(), key=lambda kv: kv[1].get("started_at", 0))[:-20]:
                _sync_jobs.pop(jid, None)


def _run_sales_sync_job(job_id: str, service_secret: str, license_key: str):
    """バックグラウンドで楽天RMSから受注を取得し、各商品の販売数を更新する"""
    with _sync_jobs_lock:
        _sync_jobs[job_id] = {"status": "running", "result": None, "error": None, "started_at": time.time()}

    from app.services.rakuten_rms import fetch_sales_by_sku
    db = SessionLocal()
    try:
        # 60日分取得（元の設計値）。直近30日=recent、31〜60日前=prevで成長率も算出でき、
        # sales_90(=60日合計)が発注計算の日販ベースになる。
        # 並列取得＋100件/回でメモリは同時リクエスト分で頭打ちのため60日でも落ちない。
        sku_sales = asyncio.run(fetch_sales_by_sku(service_secret, license_key, days=60))

        products = db.query(RakutenProduct).filter(
            RakutenProduct.is_active == True,
            RakutenProduct.is_component == False,
        ).all()

        updated = 0
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

        with _sync_jobs_lock:
            _sync_jobs[job_id]["status"] = "done"
            _sync_jobs[job_id]["result"] = {
                "synced_skus": len(sku_sales),
                "updated_products": updated,
                "last_sync": datetime.now().isoformat(),
            }
    except Exception as e:
        db.rollback()
        with _sync_jobs_lock:
            _sync_jobs[job_id]["status"] = "error"
            _sync_jobs[job_id]["error"] = str(e)
    finally:
        db.close()


@router.post("/rms/sync/start")
def start_sales_sync(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """売上同期をバックグラウンドで開始し、job_idを返す（処理は数分かかる）"""
    _prune_sync_jobs()
    settings = _get_or_create_settings(db)
    if not settings.rms_service_secret or not settings.rms_license_key:
        raise HTTPException(400, "RMS APIキーが設定されていません。楽天設定から登録してください。")
    job_id = str(uuid.uuid4())
    background_tasks.add_task(
        _run_sales_sync_job, job_id,
        settings.rms_service_secret, settings.rms_license_key,
    )
    return {"job_id": job_id}


@router.get("/rms/sync/status/{job_id}")
def get_sales_sync_status(job_id: str):
    """売上同期ジョブの状態と結果を返す"""
    with _sync_jobs_lock:
        job = _sync_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "ジョブが見つかりません")
    return {
        "status": job["status"],
        "result": job["result"],
        "error": job["error"],
        "elapsed": round(time.time() - job["started_at"], 1),
    }
