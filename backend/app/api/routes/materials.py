"""資材・レビュープレゼントの発注画面。

買うものは既に商品マスタに入っている（is_material=資材、is_promo=販促品）。
売り物ではないので発注推奨にも在庫一覧にも出てこず、これまでは
「そろそろ袋が切れる」を目で見る場所が無かった。ここがその場所。

商品の発注とは別の表（material_orders）に記録する。混ぜると売り物の
発注一覧に紛れて見づらくなるため。
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.material_order import MaterialOrder
from app.models.rakuten_product import RakutenProduct

router = APIRouter(prefix="/materials", tags=["materials"])


def _kind(p: RakutenProduct) -> str:
    return "promo" if p.is_promo else "material"


def _item_out(p: RakutenProduct, orders: List[MaterialOrder]) -> dict:
    mine = [o for o in orders if o.sku == p.sku]
    last = mine[0] if mine else None          # ordersは新しい順で渡す
    # 届いていない発注。これがあるうちは「発注済み」として扱う
    pending = sum((o.qty or 0) for o in mine if not o.received_at)
    return {
        "sku": p.sku,
        "name": p.name or "",
        "kind": _kind(p),
        "photo_url": p.photo_url or "",
        "buy_url": p.buy_url or "",
        "supplier_spec": p.supplier_spec or "",
        "price_cny": p.price,
        "stock": p.stock or 0,
        "pending_qty": pending,
        "last_ordered_at": last.ordered_at.isoformat() if last and last.ordered_at else None,
        "last_qty": last.qty if last else None,
        "order_count": len(mine),
    }


@router.get("/items")
def list_items(kind: Optional[str] = None, db: Session = Depends(get_db)):
    """資材と販促品の一覧。kind=material / promo で絞れる。"""
    q = db.query(RakutenProduct).filter(RakutenProduct.is_active == True)
    if kind == "material":
        q = q.filter(RakutenProduct.is_material == True)
    elif kind == "promo":
        q = q.filter(RakutenProduct.is_promo == True)
    else:
        q = q.filter(or_(RakutenProduct.is_material == True,
                         RakutenProduct.is_promo == True))
    prods = q.order_by(RakutenProduct.sku).all()

    orders = (db.query(MaterialOrder)
              .filter(MaterialOrder.is_deleted == False)
              .order_by(MaterialOrder.ordered_at.desc(), MaterialOrder.id.desc())
              .all())
    items = [_item_out(p, orders) for p in prods]
    return {
        "items": items,
        "material_count": sum(1 for i in items if i["kind"] == "material"),
        "promo_count": sum(1 for i in items if i["kind"] == "promo"),
    }


class OrderIn(BaseModel):
    sku: str
    qty: int
    ordered_at: Optional[str] = None
    unit_price_cny: Optional[float] = None
    memo: Optional[str] = ""


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"日付の形が違います: {s}")


@router.post("/orders")
def create_order(data: OrderIn, db: Session = Depends(get_db)):
    if (data.qty or 0) <= 0:
        raise HTTPException(400, "発注数を1以上で入れてください")
    p = (db.query(RakutenProduct)
         .filter(RakutenProduct.sku == data.sku).first())
    if not p:
        raise HTTPException(404, f"商品マスタに {data.sku} がありません")
    o = MaterialOrder(
        sku=p.sku,
        name=p.name or "",
        qty=int(data.qty),
        ordered_at=_parse_date(data.ordered_at) or date.today(),
        unit_price_cny=data.unit_price_cny if data.unit_price_cny is not None else p.price,
        memo=(data.memo or "").strip(),
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return {"ok": True, "id": o.id}


@router.get("/orders")
def list_orders(sku: Optional[str] = None, limit: int = 300,
                db: Session = Depends(get_db)):
    q = db.query(MaterialOrder).filter(MaterialOrder.is_deleted == False)
    if sku:
        q = q.filter(MaterialOrder.sku == sku)
    rows = (q.order_by(MaterialOrder.ordered_at.desc(), MaterialOrder.id.desc())
            .limit(max(1, min(limit, 1000))).all())
    names = {p.sku: p for p in db.query(RakutenProduct).all()}
    return {"items": [{
        "id": r.id,
        "sku": r.sku,
        # 名前はマスタの今の値を優先する（改名しても一覧が古い名前のままにならない）
        "name": (names[r.sku].name if r.sku in names and names[r.sku].name else r.name) or "",
        "photo_url": (names[r.sku].photo_url if r.sku in names else "") or "",
        "kind": _kind(names[r.sku]) if r.sku in names else "material",
        "qty": r.qty or 0,
        "ordered_at": r.ordered_at.isoformat() if r.ordered_at else None,
        "received_at": r.received_at.isoformat() if r.received_at else None,
        "unit_price_cny": r.unit_price_cny,
        "memo": r.memo or "",
    } for r in rows]}


class OrderPatch(BaseModel):
    qty: Optional[int] = None
    ordered_at: Optional[str] = None
    received_at: Optional[str] = None   # "" で未入荷に戻す
    memo: Optional[str] = None


@router.patch("/orders/{order_id:int}")
def update_order(order_id: int, data: OrderPatch, db: Session = Depends(get_db)):
    o = db.query(MaterialOrder).filter(MaterialOrder.id == order_id).first()
    if not o or o.is_deleted:
        raise HTTPException(404, "その発注はありません")
    p = db.query(RakutenProduct).filter(RakutenProduct.sku == o.sku).first()

    if data.qty is not None:
        if data.qty < 0:
            raise HTTPException(400, "発注数は0以上で入れてください")
        # 入荷済みの数を直したら、在庫も差分だけ動かす
        if o.received_at and p:
            p.stock = (p.stock or 0) + (int(data.qty) - (o.qty or 0))
        o.qty = int(data.qty)
    if data.ordered_at is not None:
        o.ordered_at = _parse_date(data.ordered_at) or o.ordered_at
    if data.memo is not None:
        o.memo = data.memo.strip()
    if data.received_at is not None:
        was = o.received_at
        now = _parse_date(data.received_at)
        o.received_at = now
        # 未入荷→入荷で在庫に足す。戻したら引く。二重に足さないよう状態で見る
        if p:
            if not was and now:
                p.stock = (p.stock or 0) + (o.qty or 0)
            elif was and not now:
                p.stock = max(0, (p.stock or 0) - (o.qty or 0))
    db.commit()
    return {"ok": True, "stock": (p.stock if p else None)}


@router.delete("/orders/{order_id:int}")
def delete_order(order_id: int, db: Session = Depends(get_db)):
    o = db.query(MaterialOrder).filter(MaterialOrder.id == order_id).first()
    if not o or o.is_deleted:
        raise HTTPException(404, "その発注はありません")
    p = db.query(RakutenProduct).filter(RakutenProduct.sku == o.sku).first()
    # 入荷済みを消すなら、足した在庫も戻す
    if o.received_at and p:
        p.stock = max(0, (p.stock or 0) - (o.qty or 0))
    o.is_deleted = True
    db.commit()
    return {"ok": True}


@router.post("/fetch-images")
async def fetch_images(only_missing: bool = True, db: Session = Depends(get_db)):
    """仕入先URLから商品画像を取ってきてマスタに入れる。

    タオタロウの商品詳細を使う。仕様が複数ある商品（袋のサイズ違いなど）は
    仕入れ仕様（supplier_spec）と突き合わせて、その仕様の画像を選ぶ。
    合うものが無ければ商品の1枚目で代える。
    """
    import asyncio
    from app.services import taotaro

    q = db.query(RakutenProduct).filter(
        RakutenProduct.is_active == True,
        or_(RakutenProduct.is_material == True, RakutenProduct.is_promo == True),
    )
    targets = [p for p in q.all() if (p.buy_url or "").strip()]
    if only_missing:
        targets = [p for p in targets if not (p.photo_url or "").strip()]

    done, failed = 0, []
    cache: dict = {}
    for p in targets:
        url = (p.buy_url or "").strip()
        try:
            if url not in cache:
                cache[url] = taotaro.goods_detail(url)
                # 続けて叩くと止められる。1件ずつ間を空ける
                await asyncio.sleep(1.0)
            d = cache[url]
        except Exception as e:
            failed.append(f"{p.sku}: {type(e).__name__} {str(e)[:80]}")
            continue

        img = ""
        spec = (p.supplier_spec or "").strip()
        if spec:
            for s in d.get("skus") or []:
                for key in ("label", "label_raw", "label_ja"):
                    v = str(s.get(key) or "")
                    if v and (v in spec or spec in v):
                        img = s.get("image") or ""
                        break
                if img:
                    break
        if not img:
            pics = d.get("images") or []
            img = pics[0] if pics else ""
        img = str(img or "").strip()
        if img.startswith("//"):
            img = "https:" + img
        if not img:
            failed.append(f"{p.sku}: 画像が見つかりません")
            continue
        p.photo_url = img
        done += 1

    db.commit()
    return {"ok": not failed, "done": done, "total": len(targets),
            "failed": failed[:10]}


class PhotoIn(BaseModel):
    photo_url: str


@router.put("/items/{sku}/photo")
def set_photo(sku: str, data: PhotoIn, db: Session = Depends(get_db)):
    """画像を手で入れ替える。自動取得が的外れだったとき用。"""
    p = db.query(RakutenProduct).filter(RakutenProduct.sku == sku).first()
    if not p:
        raise HTTPException(404, f"商品マスタに {sku} がありません")
    p.photo_url = (data.photo_url or "").strip()
    db.commit()
    return {"ok": True, "photo_url": p.photo_url}
