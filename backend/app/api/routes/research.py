from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
from app.core.database import get_db
from app.models.research import ResearchTarget, ResearchCandidate, ResearchWatchlistItem

router = APIRouter(prefix="/research", tags=["リサーチツール"])

JST = timezone(timedelta(hours=9))


class TargetIn(BaseModel):
    type: str            # "keyword" | "genre"
    value: str
    label: Optional[str] = None


class TargetUpdate(BaseModel):
    label: Optional[str] = None
    is_active: Optional[bool] = None


class CandidateItem(BaseModel):
    item_code: str
    item_name: Optional[str] = None
    item_price: Optional[int] = None
    review_count: Optional[int] = 0
    review_average: Optional[float] = 0
    shop_code: Optional[str] = None
    shop_name: Optional[str] = None
    item_url: Optional[str] = None
    image_url: Optional[str] = None
    rank: Optional[int] = None


class CandidateBulkIn(BaseModel):
    research_target_id: int
    fetched_at: str
    items: list[CandidateItem]


class WatchlistPickIn(BaseModel):
    item_code: str
    item_name: Optional[str] = None
    item_price: Optional[int] = None
    review_count: Optional[int] = 0
    review_average: Optional[float] = 0
    shop_code: Optional[str] = None
    shop_name: Optional[str] = None
    item_url: Optional[str] = None
    image_url: Optional[str] = None
    folder: Optional[str] = None
    memo: Optional[str] = None


class WatchlistUpdate(BaseModel):
    monthly_sales: Optional[int] = None
    folder: Optional[str] = None
    memo: Optional[str] = None


# ---------- リサーチ対象（ジャンル/キーワード）CRUD ----------

@router.get("/targets")
def list_targets(active_only: bool = False, db: Session = Depends(get_db)):
    q = db.query(ResearchTarget)
    if active_only:
        q = q.filter(ResearchTarget.is_active == True)
    rows = q.order_by(ResearchTarget.id).all()
    return {"targets": [_target_dict(r) for r in rows]}


@router.post("/targets")
def create_target(data: TargetIn, db: Session = Depends(get_db)):
    if data.type not in ("keyword", "genre"):
        raise HTTPException(400, "typeはkeywordかgenreを指定してください")
    t = ResearchTarget(type=data.type, value=data.value, label=data.label)
    db.add(t)
    db.commit()
    db.refresh(t)
    return _target_dict(t)


@router.put("/targets/{target_id}")
def update_target(target_id: int, data: TargetUpdate, db: Session = Depends(get_db)):
    t = db.query(ResearchTarget).filter(ResearchTarget.id == target_id).first()
    if not t:
        raise HTTPException(404, "対象が見つかりません")
    if data.label is not None:
        t.label = data.label
    if data.is_active is not None:
        t.is_active = data.is_active
    db.commit()
    db.refresh(t)
    return _target_dict(t)


@router.delete("/targets/{target_id}")
def delete_target(target_id: int, db: Session = Depends(get_db)):
    t = db.query(ResearchTarget).filter(ResearchTarget.id == target_id).first()
    if not t:
        raise HTTPException(404, "対象が見つかりません")
    db.query(ResearchCandidate).filter(ResearchCandidate.research_target_id == target_id).delete()
    db.delete(t)
    db.commit()
    return {"ok": True}


# ---------- 候補（ローカルバッチが投入） ----------

@router.post("/candidates/bulk")
def bulk_import_candidates(data: CandidateBulkIn, db: Session = Depends(get_db)):
    """ローカルバッチ用。対象1件分の最新候補で洗い替える
    （毎週の再取得のたびに前回分を消してから入れる＝履歴は持たない）。"""
    target = db.query(ResearchTarget).filter(ResearchTarget.id == data.research_target_id).first()
    if not target:
        raise HTTPException(404, "対象が見つかりません")

    fetched_at = datetime.fromisoformat(data.fetched_at)

    db.query(ResearchCandidate).filter(
        ResearchCandidate.research_target_id == data.research_target_id
    ).delete()

    for item in data.items:
        db.add(ResearchCandidate(
            research_target_id=data.research_target_id,
            item_code=item.item_code,
            item_name=item.item_name,
            item_price=item.item_price,
            review_count=item.review_count or 0,
            review_average=item.review_average or 0,
            shop_code=item.shop_code,
            shop_name=item.shop_name,
            item_url=item.item_url,
            image_url=item.image_url,
            rank=item.rank,
            fetched_at=fetched_at,
        ))
    db.commit()
    return {"imported": len(data.items), "research_target_id": data.research_target_id}


@router.get("/candidates")
def list_candidates(
    target_id: Optional[int] = None,
    keyword: Optional[str] = None,
    sort: str = "review_count",
    order: str = "desc",
    min_review: Optional[int] = None,
    max_review: Optional[int] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(ResearchCandidate)
    if target_id:
        q = q.filter(ResearchCandidate.research_target_id == target_id)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(ResearchCandidate.item_name.ilike(like), ResearchCandidate.shop_name.ilike(like)))
    if min_review is not None:
        q = q.filter(ResearchCandidate.review_count >= min_review)
    if max_review is not None:
        q = q.filter(ResearchCandidate.review_count <= max_review)
    if min_price is not None:
        q = q.filter(ResearchCandidate.item_price >= min_price)
    if max_price is not None:
        q = q.filter(ResearchCandidate.item_price <= max_price)

    sort_col = {
        "review_count": ResearchCandidate.review_count,
        "price": ResearchCandidate.item_price,
        "review_average": ResearchCandidate.review_average,
        "rank": ResearchCandidate.rank,
    }.get(sort, ResearchCandidate.review_count)
    q = q.order_by(sort_col.desc() if order == "desc" else sort_col.asc())

    rows = q.limit(500).all()

    picked_codes = {
        r[0] for r in db.query(ResearchWatchlistItem.item_code).all()
    }

    return {
        "candidates": [_candidate_dict(r, picked=r.item_code in picked_codes) for r in rows],
    }


# ---------- ウォッチリスト（ピックアップした商品） ----------

@router.post("/watchlist")
def pick_item(data: WatchlistPickIn, db: Session = Depends(get_db)):
    existing = db.query(ResearchWatchlistItem).filter(ResearchWatchlistItem.item_code == data.item_code).first()
    if existing:
        return _watchlist_dict(existing)

    w = ResearchWatchlistItem(
        item_code=data.item_code,
        item_name=data.item_name,
        item_price=data.item_price,
        review_count=data.review_count or 0,
        review_average=data.review_average or 0,
        shop_code=data.shop_code,
        shop_name=data.shop_name,
        item_url=data.item_url,
        image_url=data.image_url,
        folder=data.folder,
        memo=data.memo,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return _watchlist_dict(w)


@router.get("/watchlist")
def list_watchlist(
    folder: Optional[str] = None,
    sort: str = "picked_at",
    order: str = "desc",
    db: Session = Depends(get_db),
):
    q = db.query(ResearchWatchlistItem)
    if folder:
        q = q.filter(ResearchWatchlistItem.folder == folder)

    sort_col = {
        "review_count": ResearchWatchlistItem.review_count,
        "price": ResearchWatchlistItem.item_price,
        "monthly_sales": ResearchWatchlistItem.monthly_sales,
        "picked_at": ResearchWatchlistItem.picked_at,
    }.get(sort, ResearchWatchlistItem.picked_at)
    q = q.order_by(sort_col.desc() if order == "desc" else sort_col.asc())

    rows = q.all()
    return {"items": [_watchlist_dict(r) for r in rows]}


@router.put("/watchlist/{item_id}")
def update_watchlist_item(item_id: int, data: WatchlistUpdate, db: Session = Depends(get_db)):
    w = db.query(ResearchWatchlistItem).filter(ResearchWatchlistItem.id == item_id).first()
    if not w:
        raise HTTPException(404, "アイテムが見つかりません")
    if data.monthly_sales is not None:
        w.monthly_sales = data.monthly_sales
    if data.folder is not None:
        w.folder = data.folder
    if data.memo is not None:
        w.memo = data.memo
    db.commit()
    db.refresh(w)
    return _watchlist_dict(w)


@router.delete("/watchlist/{item_id}")
def delete_watchlist_item(item_id: int, db: Session = Depends(get_db)):
    w = db.query(ResearchWatchlistItem).filter(ResearchWatchlistItem.id == item_id).first()
    if not w:
        raise HTTPException(404, "アイテムが見つかりません")
    db.delete(w)
    db.commit()
    return {"ok": True}


# ---------- helpers ----------

def _target_dict(t: ResearchTarget) -> dict:
    return {
        "id": t.id,
        "type": t.type,
        "value": t.value,
        "label": t.label or t.value,
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _candidate_dict(c: ResearchCandidate, picked: bool = False) -> dict:
    return {
        "id": c.id,
        "research_target_id": c.research_target_id,
        "item_code": c.item_code,
        "item_name": c.item_name,
        "item_price": c.item_price,
        "review_count": c.review_count,
        "review_average": c.review_average,
        "shop_code": c.shop_code,
        "shop_name": c.shop_name,
        "item_url": c.item_url,
        "image_url": c.image_url,
        "rank": c.rank,
        "fetched_at": c.fetched_at.isoformat() if c.fetched_at else None,
        "picked": picked,
    }


def _watchlist_dict(w: ResearchWatchlistItem) -> dict:
    return {
        "id": w.id,
        "item_code": w.item_code,
        "item_name": w.item_name,
        "item_price": w.item_price,
        "review_count": w.review_count,
        "review_average": w.review_average,
        "shop_code": w.shop_code,
        "shop_name": w.shop_name,
        "item_url": w.item_url,
        "image_url": w.image_url,
        "monthly_sales": w.monthly_sales,
        "folder": w.folder,
        "memo": w.memo,
        "picked_at": w.picked_at.isoformat() if w.picked_at else None,
    }
