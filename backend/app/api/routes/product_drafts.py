"""リサーチで採用した商品の登録前ドラフト（スプレッドシートの置き換え）。

リサーチ→採用→情報を埋める→タイトル・説明文を生成→楽天へ登録、という
流れの「採用」以降を受け持つ。生成した文章は履歴として残す。
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.product_draft import ProductDraft, ProductDraftGeneration
from app.models.research import ResearchWatchlistItem
from app.services import copywriter

router = APIRouter(prefix="/product-drafts", tags=["商品ドラフト"])


class DraftIn(BaseModel):
    sku:            Optional[str] = None
    status:         Optional[str] = None
    rakuten_title:  Optional[str] = None
    catchcopy:      Optional[str] = None
    description_pc: Optional[str] = None
    description_sp: Optional[str] = None
    genre_id:       Optional[str] = None
    price:          Optional[int] = None
    assignee:       Optional[str] = None
    supplier_url:       Optional[str] = None
    supplier_name_cn:   Optional[str] = None
    supplier_spec:      Optional[str] = None
    supplier_price_cny: Optional[float] = None
    supplier_note:      Optional[str] = None
    rival_item_code: Optional[str] = None
    rival_title:     Optional[str] = None
    rival_caption:   Optional[str] = None
    rival_url:       Optional[str] = None
    rival_price:     Optional[int] = None
    rival_image_url: Optional[str] = None
    rival_shop_name: Optional[str] = None
    ref_image_urls:  Optional[list[str]] = None
    memo:            Optional[str] = None


class AdoptIn(BaseModel):
    """ウォッチリストの行を「採用」してドラフト化する。"""
    watchlist_id: int
    sku: Optional[str] = None


def _dict(d: ProductDraft) -> dict:
    try:
        refs = json.loads(d.ref_image_urls or "[]")
    except Exception:
        refs = []
    return {
        "id": d.id, "sku": d.sku, "status": d.status or "draft",
        "rakuten_title": d.rakuten_title, "catchcopy": d.catchcopy,
        "description_pc": d.description_pc, "description_sp": d.description_sp,
        "genre_id": d.genre_id, "price": d.price, "assignee": d.assignee,
        "supplier_url": d.supplier_url, "supplier_name_cn": d.supplier_name_cn,
        "supplier_spec": d.supplier_spec, "supplier_price_cny": d.supplier_price_cny,
        "supplier_note": d.supplier_note,
        "rival_item_code": d.rival_item_code, "rival_title": d.rival_title,
        "rival_caption": d.rival_caption, "rival_url": d.rival_url,
        "rival_price": d.rival_price, "rival_image_url": d.rival_image_url,
        "rival_shop_name": d.rival_shop_name,
        "ref_image_urls": refs, "memo": d.memo,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _apply(d: ProductDraft, data: DraftIn):
    for k, v in data.model_dump(exclude_unset=True).items():
        if k == "ref_image_urls":
            d.ref_image_urls = json.dumps(v or [], ensure_ascii=False)
        else:
            setattr(d, k, v)


@router.get("")
def list_drafts(status: Optional[str] = None, q: Optional[str] = None,
                db: Session = Depends(get_db)):
    query = db.query(ProductDraft)
    if status:
        query = query.filter(ProductDraft.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (ProductDraft.sku.ilike(like)) |
            (ProductDraft.rakuten_title.ilike(like)) |
            (ProductDraft.supplier_name_cn.ilike(like)) |
            (ProductDraft.rival_title.ilike(like))
        )
    rows = query.order_by(ProductDraft.id.desc()).limit(500).all()
    return [_dict(r) for r in rows]


@router.post("")
def create_draft(data: DraftIn, db: Session = Depends(get_db)):
    d = ProductDraft(status="draft")
    _apply(d, data)
    db.add(d)
    db.commit()
    db.refresh(d)
    return _dict(d)


@router.post("/adopt")
def adopt_from_watchlist(data: AdoptIn, db: Session = Depends(get_db)):
    """ウォッチリストの商品を採用してドラフトを作る。
    ライバル商品の情報はここでコピーして固定する（あとで相手が
    商品名を変えても、採用当時の内容が残るようにするため）。"""
    w = db.query(ResearchWatchlistItem).filter(
        ResearchWatchlistItem.id == data.watchlist_id
    ).first()
    if not w:
        raise HTTPException(404, "ウォッチリストの商品が見つかりません")

    existing = db.query(ProductDraft).filter(
        ProductDraft.rival_item_code == w.item_code
    ).first()
    if existing:
        return {**_dict(existing), "already_exists": True}

    d = ProductDraft(
        sku=data.sku,
        status="draft",
        rival_item_code=w.item_code,
        rival_title=w.item_name,
        rival_url=w.item_url,
        rival_price=w.item_price,
        rival_image_url=w.image_url,
        rival_shop_name=w.shop_name,
        memo=w.memo,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return {**_dict(d), "already_exists": False}


@router.put("/{draft_id}")
def update_draft(draft_id: int, data: DraftIn, db: Session = Depends(get_db)):
    d = db.query(ProductDraft).filter(ProductDraft.id == draft_id).first()
    if not d:
        raise HTTPException(404, "ドラフトが見つかりません")
    _apply(d, data)
    db.commit()
    db.refresh(d)
    return _dict(d)


@router.delete("/{draft_id}")
def delete_draft(draft_id: int, db: Session = Depends(get_db)):
    d = db.query(ProductDraft).filter(ProductDraft.id == draft_id).first()
    if not d:
        raise HTTPException(404, "ドラフトが見つかりません")
    db.query(ProductDraftGeneration).filter(
        ProductDraftGeneration.draft_id == draft_id
    ).delete()
    db.delete(d)
    db.commit()
    return {"ok": True}


class GenerateIn(BaseModel):
    kind: str = "both"          # title / description / both
    apply: bool = False          # 生成結果をそのままドラフトへ反映するか


@router.post("/{draft_id}/generate")
async def generate_copy(draft_id: int, data: GenerateIn, db: Session = Depends(get_db)):
    d = db.query(ProductDraft).filter(ProductDraft.id == draft_id).first()
    if not d:
        raise HTTPException(404, "ドラフトが見つかりません")
    if not copywriter.is_enabled():
        raise HTTPException(400, "ANTHROPIC_API_KEY が未設定のため生成できません。")
    if data.kind not in ("title", "description", "both"):
        raise HTTPException(400, "kind は title / description / both のいずれかです")

    try:
        res = await copywriter.generate(_dict(d), data.kind)
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    db.add(ProductDraftGeneration(
        draft_id=d.id, kind=data.kind,
        prompt=res["prompt"], output=res["output"], model=res["model"],
    ))

    parts = copywriter.split_output(data.kind, res["output"])
    if data.apply:
        if parts.get("title"):
            d.rakuten_title = parts["title"]
        if parts.get("description"):
            d.description_pc = parts["description"]
    db.commit()
    db.refresh(d)
    return {"generated": parts, "raw": res["output"], "model": res["model"],
            "applied": data.apply, "draft": _dict(d)}


@router.get("/{draft_id}/generations")
def list_generations(draft_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(ProductDraftGeneration)
        .filter(ProductDraftGeneration.draft_id == draft_id)
        .order_by(ProductDraftGeneration.id.desc())
        .limit(50).all()
    )
    return [{
        "id": r.id, "kind": r.kind, "output": r.output, "prompt": r.prompt,
        "model": r.model,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@router.get("/meta/status")
def generation_status():
    """画面側で生成ボタンを出してよいか判断するための状態。"""
    return {"generator_enabled": copywriter.is_enabled()}
