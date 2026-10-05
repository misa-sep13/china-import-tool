from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from app.core.database import get_db, SessionLocal
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


class BulkRankingItem(BaseModel):
    seo_keyword_id: int
    keyword: str
    product_sku: Optional[str] = None
    rank: Optional[int] = None
    page: Optional[int] = None
    total_items: Optional[int] = None
    card_type: Optional[str] = None


class BulkRankingRequest(BaseModel):
    checked_at: str
    results: list[BulkRankingItem]


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

_check_jobs: dict = {}


async def _run_check_job(job_id: str, keyword_ids: Optional[list[int]]):
    from app.services.rakuten_seo import check_ranking

    db = SessionLocal()
    try:
        if keyword_ids:
            keywords = db.query(SeoKeyword).filter(SeoKeyword.id.in_(keyword_ids)).all()
        else:
            keywords = db.query(SeoKeyword).filter(SeoKeyword.is_active == True).all()

        results = []
        now = datetime.now(JST)

        for kw in keywords:
            try:
                data = await check_ranking(kw.keyword)
            except Exception as e:
                results.append({"keyword_id": kw.id, "keyword": kw.keyword, "error": str(e)})
                continue

            # 取りに行けなかったものを「圏外」として残さない。
            # 残すと、順位が落ちたのか取れなかったのかが後から分からなくなる
            if data.get("debug_error") and not data["my_ranks"]:
                results.append({"keyword_id": kw.id, "keyword": kw.keyword,
                                "error": data["debug_error"]})
                continue

            if data["my_ranks"]:
                for r in data["my_ranks"]:
                    db.add(SeoRanking(
                        seo_keyword_id=kw.id,
                        keyword=kw.keyword,
                        product_sku=kw.product_sku,
                        rank=r["rank"],
                        page=r["page"],
                        total_items=data["total_items"],
                        card_type=r["card_type"],
                        checked_at=now,
                    ))
            else:
                db.add(SeoRanking(
                    seo_keyword_id=kw.id,
                    keyword=kw.keyword,
                    product_sku=kw.product_sku,
                    rank=None,
                    page=None,
                    total_items=data["total_items"],
                    card_type=None,
                    checked_at=now,
                ))

            results.append({
                "keyword_id": kw.id,
                "keyword": kw.keyword,
                "total_items": data["total_items"],
                "ranks": data["my_ranks"],
            })
            db.commit()

        _check_jobs[job_id] = {"status": "done", "results": results, "checked_at": now.isoformat()}
    except Exception as e:
        _check_jobs[job_id] = {"status": "error", "error": str(e)}
    finally:
        db.close()


@router.post("/check")
def check_rankings(background_tasks: BackgroundTasks, keyword_ids: list[int] = None, db: Session = Depends(get_db)):
    """SEO順位チェックをバックグラウンドで開始する。
    208キーワード×最大8ページを楽天APIへ順次リクエストするため数分かかり、
    Render側のリクエストタイムアウトに収まらない。同期応答はせず即座にjob_idを返す。"""
    import uuid

    if keyword_ids:
        exists = db.query(SeoKeyword.id).filter(SeoKeyword.id.in_(keyword_ids)).first()
    else:
        exists = db.query(SeoKeyword.id).filter(SeoKeyword.is_active == True).first()
    if not exists:
        raise HTTPException(400, "チェック対象のキーワードがありません")

    job_id = str(uuid.uuid4())
    _check_jobs[job_id] = {"status": "running"}
    background_tasks.add_task(_run_check_job, job_id, keyword_ids)
    return {"job_id": job_id}


@router.get("/check/status/{job_id}")
def get_check_status(job_id: str):
    job = _check_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "ジョブが見つかりません")
    return job


@router.post("/check-single")
async def check_single(keyword: str):
    from app.services.rakuten_seo import check_ranking
    data = await check_ranking(keyword)
    return data


@router.get("/_outbound-ip")
async def _outbound_ip():
    """RenderからのアウトバウンドIPを確認する（楽天APIのIPホワイトリスト登録用）。
    確認が済んだら削除する一時的なエンドポイント。"""
    import httpx
    out = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for name, url in (
            ("ipify", "https://api.ipify.org?format=json"),
            ("aws", "https://checkip.amazonaws.com"),
        ):
            try:
                r = await client.get(url)
                out[name] = r.text.strip()
            except Exception as e:
                out[name] = f"error: {e}"
    return out


# ---------- 順位履歴 ----------

# パスは上から順に照合されるので、数字だけに限定しないと
# /rankings/matrix がこちらに吸われて422になる（実際そうなっていた）
@router.get("/rankings/{keyword_id:int}")
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


# ---------- バルク登録（GH Actions用） ----------

@router.post("/rankings/bulk")
def bulk_import_rankings(data: BulkRankingRequest, db: Session = Depends(get_db)):
    checked_at = datetime.fromisoformat(data.checked_at)
    count = 0
    for item in data.results:
        ranking = SeoRanking(
            seo_keyword_id=item.seo_keyword_id,
            keyword=item.keyword,
            product_sku=item.product_sku,
            rank=item.rank,
            page=item.page,
            total_items=item.total_items,
            card_type=item.card_type,
            checked_at=checked_at,
        )
        db.add(ranking)
        count += 1
    db.commit()
    return {"imported": count, "checked_at": checked_at.isoformat()}


# ---------- マトリクス表示用 ----------

@router.get("/rankings/matrix")
def get_ranking_matrix(days: int = 30, db: Session = Depends(get_db)):
    cutoff = datetime.now(JST) - timedelta(days=days)

    keywords = (
        db.query(SeoKeyword)
        .filter(SeoKeyword.is_active == True)
        .order_by(SeoKeyword.product_sku, SeoKeyword.id)
        .all()
    )

    rankings = (
        db.query(SeoRanking)
        .filter(SeoRanking.checked_at >= cutoff)
        .all()
    )

    date_set = set()
    kw_date_rank = defaultdict(dict)
    for r in rankings:
        if not r.checked_at:
            continue
        date_str = r.checked_at.strftime("%Y-%m-%d")
        date_set.add(date_str)
        existing = kw_date_rank[r.seo_keyword_id].get(date_str)
        if existing is None or (r.rank and (existing is None or (existing and r.rank < existing))):
            kw_date_rank[r.seo_keyword_id][date_str] = r.rank

    dates = sorted(date_set, reverse=True)

    rows = []
    for kw in keywords:
        row = {
            "keyword_id": kw.id,
            "keyword": kw.keyword,
            "product_sku": kw.product_sku or "",
            "product_name": kw.product_name or "",
            "ranks": {d: kw_date_rank.get(kw.id, {}).get(d) for d in dates},
        }
        rows.append(row)

    return {"dates": dates, "rows": rows}


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


# ============================================================
# 整理
# ============================================================
# 昔のデータをそのまま持ってきているので、終売商品のキーワードが残り、
# 新商品は登録されていない。どれを消してどれを足すかを出す。
#
# SEOのキーワードは商品ページ単位（y104）で持っているが、商品マスタは
# 色違い（y104_gold）に分かれている。寄せて数えないと、ほとんどが
# 「マスタに無い」に見えてしまう。

import re as _re

from app.models.rakuten_product import RakutenProduct


def _page_code(sku: str) -> str:
    """商品ページ単位のコード。色違い（y104_gold）は y104 に寄せる。"""
    return _re.split(r"[_]", str(sku or "").strip(), maxsplit=1)[0]


@router.get("/tidy")
def tidy(db: Session = Depends(get_db)):
    """整理の材料を出す。

      ・終売（マスタに無い）商品のキーワード  → 消す候補
      ・ずっと圏外のキーワード                → 見直す候補
      ・キーワードが1つも無い販売中の商品     → 足す候補
    """
    products = db.query(RakutenProduct).all()
    # 商品ページ → その中の商品たち
    pages: dict = {}
    for p in products:
        code = (p.rakuten_item_url or "").strip() or _page_code(p.sku)
        if code:
            pages.setdefault(code, []).append(p)
    # 色違いのSKUそのものでも引けるようにしておく
    by_sku = {p.sku: p for p in products if p.sku}

    keywords = (db.query(SeoKeyword)
                .filter(SeoKeyword.is_active == True)  # noqa: E712
                .order_by(SeoKeyword.id).all())

    # 直近の順位（キーワードごとの最新1件）
    latest: dict = {}
    for r in (db.query(SeoRanking)
              .order_by(SeoRanking.checked_at.asc().nullsfirst()).all()):
        latest[r.seo_keyword_id] = r

    def sellable(rows) -> bool:
        return any(p.is_active is not False and not p.is_component
                   and not p.is_material and not p.is_promo for p in rows)

    gone, out_of_range, kept = [], [], set()
    for k in keywords:
        sku = (k.product_sku or "").strip()
        code = _page_code(sku)
        rows = pages.get(sku) or pages.get(code) or (
            [by_sku[sku]] if sku in by_sku else [])
        last = latest.get(k.id)
        item = {
            "id": k.id, "keyword": k.keyword,
            "product_sku": sku,
            "product_name": (k.product_name
                             or (rows[0].name if rows else "")),
            "rank": (last.rank if last else None),
            "checked_at": (last.checked_at.isoformat()
                           if last and last.checked_at else None),
        }
        if not rows:
            gone.append(item)        # マスタに無い＝終売・旧データ
            continue
        kept.add(code)
        if last is not None and not last.rank:
            out_of_range.append(item)   # 直近が圏外

    # キーワードが1つも無い、売っている商品ページ
    missing = []
    for code, rows in pages.items():
        if code in kept or not sellable(rows):
            continue
        main = rows[0]
        missing.append({
            "page": code,
            "sku": main.sku,
            "name": main.name or "",
            "stock": sum(int(p.stock or 0) for p in rows),
        })
    missing.sort(key=lambda x: -x["stock"])

    return {
        "total": len(keywords),
        "gone": gone,
        "out_of_range": out_of_range,
        "missing": missing[:100],
        "missing_total": len(missing),
    }


class BulkDeleteIn(BaseModel):
    ids: list[int]


@router.post("/keywords/bulk-delete")
def bulk_delete_keywords(data: BulkDeleteIn, db: Session = Depends(get_db)):
    """選んだキーワードをまとめて消す。順位の記録も一緒に消す。"""
    ids = [int(i) for i in (data.ids or [])]
    if not ids:
        return {"deleted": 0}
    db.query(SeoRanking).filter(SeoRanking.seo_keyword_id.in_(ids)).delete(
        synchronize_session=False)
    n = db.query(SeoKeyword).filter(SeoKeyword.id.in_(ids)).delete(
        synchronize_session=False)
    db.commit()
    return {"deleted": n}
