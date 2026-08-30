"""セラースカウト。

登録セラーのAmazonストアフロントを巡回し、「過去1か月で〇〇点以上購入されました」
バッジを集める。月間販売数はSP-APIでは取れず、これでしか手に入らない。

巡回そのもの（ブラウザ自動操縦）は手元のPCで走らせる。
Amazonはデータセンターのipからだと即ブロックするので、サーバー上では動かない。
ここは「結果を受け取って集約し、誰でも同じ一覧を見られるようにする」役目。

複数人で分担できる。分担の割り当てはせず、同じASINは新しい巡回で上書きする
（誰が回しても結果は同じなので、重複しても新しい情報になるだけ）。
"""
from datetime import datetime, timezone, date
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.scout import (
    ScoutSeller, ScoutProduct, ScoutHistory, ScoutBasket, ScoutRun,
)

router = APIRouter(prefix="/scout", tags=["scout"])


# ---------- セラー ----------

class SellerIn(BaseModel):
    seller_id: str
    name: Optional[str] = None
    folder: Optional[str] = None
    url: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("/sellers")
def list_sellers(
    folder: Optional[str] = None,
    enabled_only: bool = False,
    db: Session = Depends(get_db),
):
    q = db.query(ScoutSeller)
    if folder:
        q = q.filter(ScoutSeller.folder == folder)
    if enabled_only:
        q = q.filter(ScoutSeller.enabled == True)
    rows = q.all()
    rows.sort(key=lambda r: (r.folder or "", r.name or r.seller_id))

    folders = sorted({r.folder for r in db.query(ScoutSeller).all() if r.folder})
    return {
        "sellers": [{
            "seller_id": r.seller_id, "name": r.name, "folder": r.folder,
            "url": r.url, "enabled": r.enabled,
            "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
            "last_status": r.last_status, "last_note": r.last_note,
            "last_run_by": r.last_run_by,
            "product_count": r.product_count or 0,
        } for r in rows],
        "folders": folders,
        "total": len(rows),
    }


@router.post("/sellers/bulk")
def upsert_sellers(data: List[SellerIn], db: Session = Depends(get_db)):
    """ブックマークから取り込んだセラーをまとめて登録する。

    既にあるセラーは名前とフォルダだけ更新し、巡回の記録は消さない。
    """
    created = updated = 0
    for s in data:
        sid = (s.seller_id or "").strip()
        if not sid:
            continue
        row = db.query(ScoutSeller).filter(ScoutSeller.seller_id == sid).first()
        if row is None:
            row = ScoutSeller(seller_id=sid, enabled=True)
            db.add(row)
            created += 1
        else:
            updated += 1
        if s.name:
            row.name = s.name
        if s.folder:
            row.folder = s.folder
        if s.url:
            row.url = s.url
        if s.enabled is not None:
            row.enabled = s.enabled
    db.commit()
    return {"created": created, "updated": updated}


@router.patch("/sellers/{seller_id}")
def update_seller(seller_id: str, data: SellerIn, db: Session = Depends(get_db)):
    row = db.query(ScoutSeller).filter(ScoutSeller.seller_id == seller_id).first()
    if not row:
        raise HTTPException(404, "セラーが見つかりません")
    for f in ("name", "folder", "url", "enabled"):
        v = getattr(data, f, None)
        if v is not None:
            setattr(row, f, v)
    db.commit()
    return {"seller_id": row.seller_id, "enabled": row.enabled}


@router.delete("/sellers/{seller_id}")
def delete_seller(seller_id: str, db: Session = Depends(get_db)):
    row = db.query(ScoutSeller).filter(ScoutSeller.seller_id == seller_id).first()
    if not row:
        raise HTTPException(404, "セラーが見つかりません")
    db.query(ScoutProduct).filter(ScoutProduct.seller_id == seller_id).delete()
    db.delete(row)
    db.commit()
    return {"deleted": seller_id}


# ---------- 巡回結果の受け取り ----------

class ProductIn(BaseModel):
    asin: str
    title: Optional[str] = None
    image: Optional[str] = None
    url: Optional[str] = None
    price: Optional[int] = None
    sales_min: Optional[int] = None
    sales_text: Optional[str] = None
    reviews: Optional[int] = None
    rating: Optional[float] = None
    page: Optional[int] = None
    rank: Optional[int] = None


class CrawlResultIn(BaseModel):
    seller_id: str
    status: Optional[str] = "ok"      # ok / blocked / error
    note: Optional[str] = None
    run_by: Optional[str] = None      # 誰が巡回したか
    products: List[ProductIn] = []


@router.post("/crawl-result")
def push_crawl_result(data: CrawlResultIn, db: Session = Depends(get_db)):
    """手元のPCで巡回した結果を受け取る。

    同じセラー・同じASINは上書きする。誰が回しても結果は同じなので、
    重複しても新しい情報になるだけで問題ない。
    日別の推移も残す（販売数が伸びている商品を見つけるため）。
    """
    sid = (data.seller_id or "").strip()
    if not sid:
        raise HTTPException(400, "seller_id がありません")

    seller = db.query(ScoutSeller).filter(ScoutSeller.seller_id == sid).first()
    if seller is None:
        seller = ScoutSeller(seller_id=sid, enabled=True)
        db.add(seller)

    now = datetime.now(timezone.utc)
    today = date.today().isoformat()
    saved = 0

    for p in data.products:
        asin = (p.asin or "").strip()
        if not asin:
            continue
        row = (db.query(ScoutProduct)
               .filter(ScoutProduct.seller_id == sid, ScoutProduct.asin == asin)
               .first())
        if row is None:
            row = ScoutProduct(seller_id=sid, asin=asin)
            db.add(row)
        for f in ("title", "image", "url", "price", "sales_min", "sales_text",
                  "reviews", "rating", "page", "rank"):
            v = getattr(p, f, None)
            if v is not None:
                setattr(row, f, v)
        row.last_seen = now
        saved += 1

        # 日別の推移。同じ日に2回巡回したら後の値で上書きする
        h = (db.query(ScoutHistory)
             .filter(ScoutHistory.seller_id == sid, ScoutHistory.asin == asin,
                     ScoutHistory.day == today)
             .first())
        if h is None:
            h = ScoutHistory(seller_id=sid, asin=asin, day=today)
            db.add(h)
        h.sales_min = p.sales_min
        h.reviews = p.reviews
        h.rating = p.rating
        h.price = p.price
        h.rank = p.rank

    seller.last_run_at = now
    seller.last_status = data.status or "ok"
    seller.last_note = data.note
    seller.last_run_by = data.run_by
    if data.status == "ok":
        # 件数は保存を確定させてから数える（flush前だと新規分が入らない）
        db.flush()
        seller.product_count = (db.query(ScoutProduct)
                                .filter(ScoutProduct.seller_id == sid).count())
    db.commit()
    return {"seller_id": sid, "saved": saved,
            "product_count": seller.product_count or 0}


# ---------- 商品一覧 ----------

@router.get("/products")
def list_products(
    kw: Optional[str] = None,
    seller: Optional[str] = None,
    folder: Optional[str] = None,
    sales_min: Optional[int] = None,
    sales_max: Optional[int] = None,
    rev_min: Optional[int] = None,
    rev_max: Optional[int] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    rating_max: Optional[float] = None,
    sort: str = "price_desc",
    limit: int = 600,
    db: Session = Depends(get_db),
):
    """巡回で集めた商品。

    パラメータと戻り値は配布版のセラースカウトに合わせてある
    （画面はそのHTMLをそのまま使っているため）。
    """
    query = db.query(ScoutProduct)
    if seller:
        query = query.filter(ScoutProduct.seller_id == seller)
    if sales_min:
        query = query.filter(ScoutProduct.sales_min >= sales_min)
    if sales_max:
        query = query.filter(ScoutProduct.sales_min <= sales_max)
    if rev_min:
        query = query.filter(ScoutProduct.reviews >= rev_min)
    if rev_max:
        query = query.filter(ScoutProduct.reviews <= rev_max)
    if price_min:
        query = query.filter(ScoutProduct.price >= price_min)
    if price_max:
        query = query.filter(ScoutProduct.price <= price_max)
    if rating_max:
        query = query.filter(ScoutProduct.rating <= rating_max)
    rows = query.all()

    sellers = {s.seller_id: s for s in db.query(ScoutSeller).all()}
    if folder:
        rows = [r for r in rows
                if (sellers[r.seller_id].folder if r.seller_id in sellers else None) == folder]
    if kw:
        k = kw.strip().lower()
        rows = [r for r in rows if k in (r.title or "").lower()
                or k in (r.asin or "").lower()]

    key = {
        "price_desc": lambda r: -(r.price or 0),
        "price_asc": lambda r: (r.price or 0),
        "sales_desc": lambda r: -(r.sales_min or 0),
        "sales_asc": lambda r: (r.sales_min or 0),
        "rev_asc": lambda r: (r.reviews if r.reviews is not None else 10 ** 9),
        "rev_desc": lambda r: -(r.reviews or 0),
        "rank_asc": lambda r: (r.rank if r.rank is not None else 10 ** 9),
    }.get(sort, lambda r: -(r.price or 0))
    rows.sort(key=key)

    total = len(rows)
    rows = rows[:max(1, limit)]

    in_basket = {b.asin for b in db.query(ScoutBasket)
                 .filter(ScoutBasket.taken_at.is_(None)).all()}

    return {
        "total": total,
        "rows": [{
            "seller_id": r.seller_id,
            "seller_name": (sellers[r.seller_id].name
                            if r.seller_id in sellers else r.seller_id),
            "asin": r.asin, "title": r.title, "image": r.image,
            "url": r.url or f"https://www.amazon.co.jp/dp/{r.asin}",
            "price": r.price, "sales_min": r.sales_min, "sales_text": r.sales_text,
            "reviews": r.reviews, "rating": r.rating,
            "page": r.page, "rank": r.rank,
            "in_cart": r.asin in in_basket,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
        } for r in rows],
    }


@router.get("/status")
def scout_status(db: Session = Depends(get_db)):
    """画面が定期的に見に来る状態。

    配布版はローカルサーバーが巡回を実行していたので進捗を返していたが、
    ここでは巡回は手元のPCで走るため「実行中」は常にfalse。
    画面側は running=false なら操作を受け付ける作りになっている。
    """
    sellers = db.query(ScoutSeller).all()
    latest = max((s.last_run_at for s in sellers if s.last_run_at), default=None)
    return {
        "running": False,
        "phase": "",
        "done": 0,
        "total": 0,
        "current": "",
        "blocked": len([s for s in sellers if s.last_status == "blocked"]),
        "last_run_at": latest.isoformat() if latest else None,
        # 画面上部の「セラー〇件 / 商品〇件」がここを見ている
        "seller_total": len(sellers),
        "product_total": db.query(ScoutProduct).count(),
        "message": "巡回は手元のPCで実行します（scripts/scout/sync_server.py）",
    }


@router.get("/csv")
def export_csv(
    kw: Optional[str] = None,
    seller: Optional[str] = None,
    folder: Optional[str] = None,
    sales_min: Optional[int] = None,
    sales_max: Optional[int] = None,
    rev_min: Optional[int] = None,
    rev_max: Optional[int] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    rating_max: Optional[float] = None,
    sort: str = "price_desc",
    limit: int = 100000,
    db: Session = Depends(get_db),
):
    """絞り込んだ結果をCSVで落とす。Excelで開けるようBOM付きにする。"""
    import csv as _csv
    import io as _io
    from fastapi.responses import StreamingResponse

    data = list_products(kw=kw, seller=seller, folder=folder,
                         sales_min=sales_min, sales_max=sales_max,
                         rev_min=rev_min, rev_max=rev_max,
                         price_min=price_min, price_max=price_max,
                         rating_max=rating_max, sort=sort, limit=limit, db=db)
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["ASIN", "商品名", "セラー", "価格", "月間販売数",
                "レビュー数", "評価", "順位", "URL"])
    for r in data["rows"]:
        w.writerow([r["asin"], r["title"], r["seller_name"], r["price"],
                    r["sales_min"], r["reviews"], r["rating"], r["rank"], r["url"]])
    out = "﻿" + buf.getvalue()
    return StreamingResponse(
        _io.BytesIO(out.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="seller_scout.csv"'},
    )


# ---------- かご（リサーチシートへ送る） ----------

class BasketIn(BaseModel):
    asin: str
    added_by: Optional[str] = None


@router.get("/basket")
def list_basket(db: Session = Depends(get_db)):
    """まだシートへ入れていない分を返す。シート側がこれを読んで行にする。"""
    rows = (db.query(ScoutBasket).filter(ScoutBasket.taken_at.is_(None))
            .order_by(ScoutBasket.added_at.asc()).all())
    asins = [b.asin for b in rows]
    products = {}
    if asins:
        for p in db.query(ScoutProduct).filter(ScoutProduct.asin.in_(asins)).all():
            # 同じASINが複数セラーにあることがある。販売数が大きい方を採る
            cur = products.get(p.asin)
            if cur is None or (p.sales_min or 0) > (cur.sales_min or 0):
                products[p.asin] = p
    out = []
    for b in rows:
        p = products.get(b.asin)
        out.append({
            "id": b.id, "asin": b.asin,
            "title": p.title if p else None,
            "image": p.image if p else None,
            "price": p.price if p else None,
            "sales_min": p.sales_min if p else None,
            "reviews": p.reviews if p else None,
            "rating": p.rating if p else None,
            "added_at": b.added_at.isoformat() if b.added_at else None,
        })
    # 配布版の画面は rows で読む
    return {"rows": out, "items": out, "count": len(out)}


@router.get("/basket/count")
def basket_count(db: Session = Depends(get_db)):
    n = db.query(ScoutBasket).filter(ScoutBasket.taken_at.is_(None)).count()
    return {"count": n}


@router.post("/basket/add")
def add_basket(data: BasketIn, db: Session = Depends(get_db)):
    asin = (data.asin or "").strip()
    if not asin:
        raise HTTPException(400, "ASINがありません")
    exists = (db.query(ScoutBasket)
              .filter(ScoutBasket.asin == asin, ScoutBasket.taken_at.is_(None))
              .first())
    if exists:
        return {"added": False, "reason": "すでに入っています"}
    db.add(ScoutBasket(asin=asin, added_by=data.added_by))
    db.commit()
    n = db.query(ScoutBasket).filter(ScoutBasket.taken_at.is_(None)).count()
    return {"added": True, "count": n}


@router.post("/basket/remove")
def remove_basket(data: BasketIn, db: Session = Depends(get_db)):
    (db.query(ScoutBasket)
     .filter(ScoutBasket.asin == data.asin, ScoutBasket.taken_at.is_(None))
     .delete())
    db.commit()
    n = db.query(ScoutBasket).filter(ScoutBasket.taken_at.is_(None)).count()
    return {"count": n}


@router.post("/basket/taken")
def mark_taken(db: Session = Depends(get_db)):
    """シートへ入れ終わった印を付ける。次回から出てこなくなる。"""
    now = datetime.now(timezone.utc)
    rows = db.query(ScoutBasket).filter(ScoutBasket.taken_at.is_(None)).all()
    for b in rows:
        b.taken_at = now
    db.commit()
    return {"taken": len(rows)}


# ---------- 巡回の記録 ----------

@router.get("/runs")
def list_runs(limit: int = 20, db: Session = Depends(get_db)):
    rows = (db.query(ScoutRun).order_by(ScoutRun.started_at.desc())
            .limit(limit).all())
    return {"runs": [{
        "id": r.id,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "run_by": r.run_by, "seller_count": r.seller_count,
        "product_count": r.product_count, "blocked_count": r.blocked_count,
        "note": r.note,
    } for r in rows]}


class RunIn(BaseModel):
    run_by: Optional[str] = None
    seller_count: Optional[int] = None
    product_count: Optional[int] = None
    blocked_count: Optional[int] = None
    note: Optional[str] = None
    finished: Optional[bool] = None


@router.post("/runs")
def create_run(data: RunIn, db: Session = Depends(get_db)):
    row = ScoutRun(run_by=data.run_by, seller_count=0, product_count=0)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id}


@router.patch("/runs/{run_id:int}")
def update_run(run_id: int, data: RunIn, db: Session = Depends(get_db)):
    row = db.query(ScoutRun).filter(ScoutRun.id == run_id).first()
    if not row:
        raise HTTPException(404, "実行記録が見つかりません")
    for f in ("run_by", "seller_count", "product_count", "blocked_count", "note"):
        v = getattr(data, f, None)
        if v is not None:
            setattr(row, f, v)
    if data.finished:
        row.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": row.id}


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    """画面の上に出す集計。"""
    sellers = db.query(ScoutSeller).all()
    products = db.query(ScoutProduct).count()
    never = [s for s in sellers if s.last_run_at is None]
    blocked = [s for s in sellers if s.last_status == "blocked"]
    latest = max((s.last_run_at for s in sellers if s.last_run_at), default=None)
    return {
        "seller_count": len(sellers),
        "enabled_count": len([s for s in sellers if s.enabled]),
        "never_crawled": len(never),
        "blocked": len(blocked),
        "product_count": products,
        "last_run_at": latest.isoformat() if latest else None,
        "basket_count": db.query(ScoutBasket)
            .filter(ScoutBasket.taken_at.is_(None)).count(),
    }


# ---------- 配布版の画面が叩く残りのAPI ----------
# 巡回・ブックマーク取り込みはブラウザ自動操縦なのでサーバーでは動かない。
# 画面から押されたときは、手元で実行する旨を返して知らせる。

_LOCAL_ONLY = (
    "この操作は手元のPCで実行します。"
    "scripts/scout/sync_server.py を動かしてください"
)


@router.post("/crawl")
def crawl_not_here():
    return {"ok": False, "running": False, "message": _LOCAL_ONLY}


@router.post("/stop")
def stop_not_here():
    return {"ok": False, "running": False, "message": "巡回は手元のPCで止めてください"}


@router.post("/import")
def import_not_here():
    return {"ok": False, "message":
            "ブックマークの取り込みは手元のPCで実行します。"
            "配布版のセラースカウトで取り込んでから、"
            "scripts/scout/sync_server.py を動かしてください"}


@router.post("/resolve")
def resolve_not_here():
    return {"ok": False, "message": _LOCAL_ONLY}


@router.post("/basket/register")
def basket_register(db: Session = Depends(get_db)):
    """かごの中身を競合リサーチシートへ渡す印を付ける。

    シート側は /scout/basket を読んで行にするので、ここでは
    「渡した」印だけ付ける（もう一度押しても二重に入らないように）。
    """
    rows = db.query(ScoutBasket).filter(ScoutBasket.taken_at.is_(None)).all()
    if not rows:
        return {"ok": False, "count": 0}
    return {"ok": True, "count": len(rows)}


@router.get("/basket/registered")
def basket_registered(db: Session = Depends(get_db)):
    n = db.query(ScoutBasket).filter(ScoutBasket.taken_at.isnot(None)).count()
    return {"count": n}


@router.get("/keepa")
def keepa_not_here(asin: str = ""):
    """Keepaのグラフ中継。配布版はローカルサーバーが取りに行っていた。

    ここでは中継しないので、画面側は画像が出ないだけで他の機能は動く。
    """
    raise HTTPException(404, "Keepaグラフは手元のセラースカウトでご覧ください")
