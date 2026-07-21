from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
from app.core.database import get_db
from app.models.seo import SeoKeyword, SeoRanking

router = APIRouter(prefix="/seo", tags=["SEO"])

JST = timezone(timedelta(hours=9))


class KeywordIn(BaseModel):
    keyword: str
    product_sku: Optional[str] = None
    product_name: Optional[str] = None
    memo: Optional[str] = None


class KeywordUpdate(BaseModel):
    keyword: Optional[str] = None
    product_sku: Optional[str] = None
    product_name: Optional[str] = None
    is_active: Optional[bool] = None
    memo: Optional[str] = None


# ---------- キーワードCRUD ----------

@router.get("/keywords")
def list_keywords(active_only: bool = True, db: Session = Depends(get_db)):
    q = db.query(SeoKeyword)
    if active_only:
        q = q.filter(SeoKeyword.is_active == True)
    rows = q.order_by(SeoKeyword.id).all()
    return {"keywords": [_kw_dict(r) for r in rows]}


@router.post("/keywords")
def create_keyword(data: KeywordIn, db: Session = Depends(get_db)):
    kw = SeoKeyword(
        keyword=data.keyword,
        product_sku=data.product_sku,
        product_name=data.product_name,
        memo=data.memo,
    )
    db.add(kw)
    db.commit()
    db.refresh(kw)
    return _kw_dict(kw)


@router.put("/keywords/{keyword_id}")
def update_keyword(keyword_id: int, data: KeywordUpdate, db: Session = Depends(get_db)):
    kw = db.query(SeoKeyword).filter(SeoKeyword.id == keyword_id).first()
    if not kw:
        raise HTTPException(404, "キーワードが見つかりません")
    for field in ("keyword", "product_sku", "product_name", "is_active", "memo"):
        val = getattr(data, field, None)
        if val is not None:
            setattr(kw, field, val)
    db.commit()
    db.refresh(kw)
    return _kw_dict(kw)


@router.delete("/keywords/{keyword_id}")
def delete_keyword(keyword_id: int, db: Session = Depends(get_db)):
    kw = db.query(SeoKeyword).filter(SeoKeyword.id == keyword_id).first()
    if not kw:
        raise HTTPException(404, "キーワードが見つかりません")
    db.delete(kw)
    db.commit()
    return {"ok": True}


# ---------- 順位チェック ----------

@router.post("/check")
async def check_rankings(keyword_ids: list[int] = None, db: Session = Depends(get_db)):
    from app.services.rakuten_seo import check_ranking

    if keyword_ids:
        keywords = db.query(SeoKeyword).filter(SeoKeyword.id.in_(keyword_ids)).all()
    else:
        keywords = db.query(SeoKeyword).filter(SeoKeyword.is_active == True).all()

    if not keywords:
        raise HTTPException(400, "チェック対象のキーワードがありません")

    results = []
    now = datetime.now(JST)

    for kw in keywords:
        try:
            data = await check_ranking(kw.keyword)
        except Exception as e:
            results.append({"keyword_id": kw.id, "keyword": kw.keyword, "error": str(e)})
            continue

        if data["my_ranks"]:
            for r in data["my_ranks"]:
                ranking = SeoRanking(
                    seo_keyword_id=kw.id,
                    keyword=kw.keyword,
                    product_sku=kw.product_sku,
                    rank=r["rank"],
                    page=r["page"],
                    total_items=data["total_items"],
                    card_type=r["card_type"],
                    checked_at=now,
                )
                db.add(ranking)
        else:
            ranking = SeoRanking(
                seo_keyword_id=kw.id,
                keyword=kw.keyword,
                product_sku=kw.product_sku,
                rank=None,
                page=None,
                total_items=data["total_items"],
                card_type=None,
                checked_at=now,
            )
            db.add(ranking)

        results.append({
            "keyword_id": kw.id,
            "keyword": kw.keyword,
            "total_items": data["total_items"],
            "ranks": data["my_ranks"],
        })

    db.commit()
    return {"results": results, "checked_at": now.isoformat()}


@router.post("/check-single")
async def check_single(keyword: str):
    from app.services.rakuten_seo import check_ranking
    data = await check_ranking(keyword)
    return data


# ---------- 順位履歴 ----------

@router.get("/rankings/{keyword_id}")
def get_rankings(keyword_id: int, days: int = 30, db: Session = Depends(get_db)):
    cutoff = datetime.now(JST) - timedelta(days=days)
    rows = (
        db.query(SeoRanking)
        .filter(SeoRanking.seo_keyword_id == keyword_id, SeoRanking.checked_at >= cutoff)
        .order_by(SeoRanking.checked_at.desc())
        .all()
    )
    return {"rankings": [_rank_dict(r) for r in rows]}


@router.get("/rankings")
def get_all_latest_rankings(db: Session = Depends(get_db)):
    from sqlalchemy import func
    subq = (
        db.query(
            SeoRanking.seo_keyword_id,
            func.max(SeoRanking.checked_at).label("latest"),
        )
        .group_by(SeoRanking.seo_keyword_id)
        .subquery()
    )
    rows = (
        db.query(SeoRanking)
        .join(subq, (SeoRanking.seo_keyword_id == subq.c.seo_keyword_id) & (SeoRanking.checked_at == subq.c.latest))
        .all()
    )
    return {"rankings": [_rank_dict(r) for r in rows]}


# ---------- helpers ----------

def _kw_dict(kw: SeoKeyword) -> dict:
    return {
        "id": kw.id,
        "keyword": kw.keyword,
        "product_sku": kw.product_sku,
        "product_name": kw.product_name,
        "is_active": kw.is_active,
        "memo": kw.memo,
        "created_at": kw.created_at.isoformat() if kw.created_at else None,
    }


def _rank_dict(r: SeoRanking) -> dict:
    return {
        "id": r.id,
        "seo_keyword_id": r.seo_keyword_id,
        "keyword": r.keyword,
        "product_sku": r.product_sku,
        "rank": r.rank,
        "page": r.page,
        "total_items": r.total_items,
        "card_type": r.card_type,
        "checked_at": r.checked_at.isoformat() if r.checked_at else None,
    }
