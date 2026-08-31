"""リサーチで採用した商品の登録前ドラフト（スプレッドシートの置き換え）。

リサーチ→採用→情報を埋める→タイトル・説明文を生成→楽天へ登録、という
流れの「採用」以降を受け持つ。生成した文章は履歴として残す。
"""
import base64
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.product_draft import (
    ProductDraft, ProductDraftGeneration, ProductDraftImage,
)
from app.models.research import ResearchWatchlistItem, RakutenGenre
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
    # バリエーション。軸が空なら単品として登録する
    variant_axis:    Optional[str] = None
    variants:        Optional[list[dict]] = None
    image_urls:      Optional[list[str]] = None


class AdoptIn(BaseModel):
    """ウォッチリストの行を「採用」してドラフト化する。"""
    watchlist_id: int
    sku: Optional[str] = None


def _dict(d: ProductDraft) -> dict:
    try:
        refs = json.loads(d.ref_image_urls or "[]")
    except Exception:
        refs = []
    try:
        variants = json.loads(d.variants or "[]")
    except Exception:
        variants = []
    try:
        images = json.loads(d.image_urls or "[]")
    except Exception:
        images = []
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
        "variant_axis": d.variant_axis, "variants": variants,
        "image_urls": images,
        "registered_at": d.registered_at.isoformat() if d.registered_at else None,
        "register_error": d.register_error,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _apply(d: ProductDraft, data: DraftIn):
    for k, v in data.model_dump(exclude_unset=True).items():
        if k == "ref_image_urls":
            d.ref_image_urls = json.dumps(v or [], ensure_ascii=False)
        elif k == "variants":
            d.variants = json.dumps(v or [], ensure_ascii=False)
        elif k == "image_urls":
            d.image_urls = json.dumps(v or [], ensure_ascii=False)
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


@router.put("/{draft_id:int}")
def update_draft(draft_id: int, data: DraftIn, db: Session = Depends(get_db)):
    d = db.query(ProductDraft).filter(ProductDraft.id == draft_id).first()
    if not d:
        raise HTTPException(404, "ドラフトが見つかりません")
    _apply(d, data)
    db.commit()
    db.refresh(d)
    return _dict(d)


@router.delete("/{draft_id:int}")
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


@router.post("/{draft_id:int}/generate")
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


@router.get("/{draft_id:int}/generations")
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


# ---------- RMSへの登録（手元のPCから実行する） ----------
#
# 楽天の商品APIは書込みに有料オプションが要り、未契約だと401（GA0001）に
# なる。Compassにログインしたブラウザから内部APIへ送れば追加費用なしで
# 登録できるが、ブラウザが要るのでサーバー（Render）では動かせない。
# そのため、ここは「登録するものを渡す」「結果を受け取る」だけを担う。

@router.get("/pending-register")
def pending_register(limit: int = 20, db: Session = Depends(get_db)):
    """登録待ちのドラフト。手元のスクリプトが取りに来る。

    status が ready で、まだ登録していないものだけ返す。
    登録に必要な項目が欠けているものは、理由を付けて分けて返す
    （実行してから足りないと分かるより、先に知りたいため）。
    """
    rows = (db.query(ProductDraft)
            .filter(ProductDraft.status == "ready",
                    ProductDraft.registered_at.is_(None))
            .order_by(ProductDraft.id).limit(limit).all())

    ready, incomplete = [], []
    for d in rows:
        missing = [label for value, label in (
            (d.sku, "SKU"),
            (d.rakuten_title, "楽天商品名"),
            (d.price, "販売価格"),
        ) if not value]
        item = _dict(d)
        if missing:
            item["missing"] = missing
            incomplete.append(item)
        else:
            ready.append(item)
    return {"ready": ready, "incomplete": incomplete,
            "counts": {"ready": len(ready), "incomplete": len(incomplete)}}


class RegisterResultIn(BaseModel):
    """手元のスクリプトから送られてくる登録結果。"""
    ok: bool
    error: Optional[str] = None
    log: Optional[list] = None       # 3本のリクエストの結果


@router.post("/{draft_id:int}/register-result")
def register_result(draft_id: int, data: RegisterResultIn,
                    db: Session = Depends(get_db)):
    """登録の結果を記録する。

    失敗も残す。何度やっても通らない商品を後から探せるようにするため。
    """
    d = db.query(ProductDraft).filter(ProductDraft.id == draft_id).first()
    if not d:
        raise HTTPException(404, "ドラフトが見つかりません")

    d.register_log = json.dumps(data.log or [], ensure_ascii=False)
    if data.ok:
        d.status = "registered"
        d.registered_at = datetime.now(timezone.utc)
        d.register_error = None
    else:
        d.register_error = data.error or "理由が分かりません"
    db.commit()
    return _dict(d)


# ---------- 商品画像 ----------
#
# R-Cabinetへの書き込みはCompassにログインしたブラウザからしかできない。
# 画面で選んだ画像はここへ預かり、登録するときに手元のPCが上げる。

# 1枚あたりの上限。楽天のR-Cabinetは2MBまでなので、それに合わせる
MAX_IMAGE_BYTES = 2 * 1024 * 1024


class ImageIn(BaseModel):
    file_name: str
    mime: Optional[str] = None
    data: str            # base64（data URLの接頭辞は付いていてもよい）


def _image_dict(i, with_data=False):
    d = {"id": i.id, "file_name": i.file_name, "mime": i.mime,
         "size": i.size, "sort_order": i.sort_order,
         "cabinet_url": i.cabinet_url,
         "uploaded_at": i.uploaded_at.isoformat() if i.uploaded_at else None}
    if with_data:
        d["data"] = i.data
    return d


@router.get("/{draft_id:int}/images")
def list_images(draft_id: int, db: Session = Depends(get_db)):
    """預かっている画像の一覧。中身（base64）は返さない。

    一覧に画像そのものを載せると重くなるので、表示用は別途取りに来る。
    """
    rows = (db.query(ProductDraftImage)
            .filter(ProductDraftImage.draft_id == draft_id)
            .order_by(ProductDraftImage.sort_order, ProductDraftImage.id).all())
    return [_image_dict(i) for i in rows]


@router.get("/{draft_id:int}/images/{image_id:int}/data")
def get_image_data(draft_id: int, image_id: int, db: Session = Depends(get_db)):
    """画像の中身。画面での表示と、登録スクリプトの取得に使う。"""
    i = (db.query(ProductDraftImage)
         .filter(ProductDraftImage.id == image_id,
                 ProductDraftImage.draft_id == draft_id).first())
    if not i:
        raise HTTPException(404, "画像が見つかりません")
    return _image_dict(i, with_data=True)


@router.post("/{draft_id:int}/images")
def add_image(draft_id: int, data: ImageIn, db: Session = Depends(get_db)):
    """画像を預かる。"""
    d = db.query(ProductDraft).filter(ProductDraft.id == draft_id).first()
    if not d:
        raise HTTPException(404, "ドラフトが見つかりません")

    # data URL で来ることがあるので、接頭辞を落とす
    raw = data.data or ""
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]

    try:
        size = len(base64.b64decode(raw, validate=True))
    except Exception:
        raise HTTPException(400, "画像を読み取れませんでした")
    if size > MAX_IMAGE_BYTES:
        raise HTTPException(
            400, f"画像が大きすぎます（{size // 1024}KB）。"
                 f"R-Cabinetは1枚{MAX_IMAGE_BYTES // 1024 // 1024}MBまでです")

    last = (db.query(ProductDraftImage)
            .filter(ProductDraftImage.draft_id == draft_id)
            .order_by(ProductDraftImage.sort_order.desc()).first())
    i = ProductDraftImage(
        draft_id=draft_id, file_name=data.file_name,
        mime=data.mime or "image/jpeg", size=size, data=raw,
        sort_order=(last.sort_order + 1) if last else 0)
    db.add(i)
    db.commit()
    db.refresh(i)
    return _image_dict(i)


@router.delete("/{draft_id:int}/images/{image_id:int}")
def delete_image(draft_id: int, image_id: int, db: Session = Depends(get_db)):
    i = (db.query(ProductDraftImage)
         .filter(ProductDraftImage.id == image_id,
                 ProductDraftImage.draft_id == draft_id).first())
    if not i:
        raise HTTPException(404, "画像が見つかりません")
    db.delete(i)
    db.commit()
    return {"deleted": image_id}


class ImageUploadedIn(BaseModel):
    """R-Cabinetへ上げ終わったら、そのURLを記録する。"""
    cabinet_url: str


@router.post("/{draft_id:int}/images/{image_id:int}/uploaded")
def mark_uploaded(draft_id: int, image_id: int, data: ImageUploadedIn,
                  db: Session = Depends(get_db)):
    i = (db.query(ProductDraftImage)
         .filter(ProductDraftImage.id == image_id,
                 ProductDraftImage.draft_id == draft_id).first())
    if not i:
        raise HTTPException(404, "画像が見つかりません")
    i.cabinet_url = data.cabinet_url
    i.uploaded_at = datetime.now(timezone.utc)
    # 中身はもう要らない。上げ終わった画像を持ち続けるとDBが太る
    i.data = None
    db.commit()
    return _image_dict(i)


@router.get("/{draft_id:int}/images/{image_id:int}/preview")
def preview_image(draft_id: int, image_id: int, db: Session = Depends(get_db)):
    """画面に出すための画像そのもの。

    base64のまま返すとimgタグで使えないので、画像として返す。
    """
    from fastapi import Response
    i = (db.query(ProductDraftImage)
         .filter(ProductDraftImage.id == image_id,
                 ProductDraftImage.draft_id == draft_id).first())
    if not i or not i.data:
        raise HTTPException(404, "画像が見つかりません")
    return Response(content=base64.b64decode(i.data),
                    media_type=i.mime or "image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})


# ---------- ジャンルID ----------

@router.post("/{draft_id:int}/fetch-genre")
async def fetch_genre(draft_id: int, db: Session = Depends(get_db)):
    """ライバル商品からジャンルIDを取る。

    楽天のジャンルIDは自分で調べると手間なので、参考にした商品から
    引く。同じ商品を売るなら同じジャンルになるはずで、実際に売れて
    いる商品のジャンルなら間違いが少ない。
    """
    import httpx
    from app.core.config import settings

    d = db.query(ProductDraft).filter(ProductDraft.id == draft_id).first()
    if not d:
        raise HTTPException(404, "ドラフトが見つかりません")
    if not d.rival_item_code:
        raise HTTPException(400, "参考にした商品がありません")
    if not settings.RAKUTEN_APP_ID or not settings.RAKUTEN_ACCESS_KEY:
        raise HTTPException(400, "RAKUTEN_APP_ID/RAKUTEN_ACCESS_KEYが未設定です")

    # accessKey も要る。applicationId だけだと400になる
    params = {
        "applicationId": settings.RAKUTEN_APP_ID,
        "accessKey": settings.RAKUTEN_ACCESS_KEY,
        "itemCode": d.rival_item_code,
        "hits": 1,
        "format": "json",
    }

    from app.services.rakuten_seo import SEARCH_API_URL as url
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, params=params)
    if r.status_code != 200:
        raise HTTPException(
            502, f"楽天から取れませんでした（{r.status_code}）: {r.text[:300]}")

    items = (r.json() or {}).get("Items") or []
    if not items:
        raise HTTPException(404, "その商品が見つかりませんでした（削除された可能性）")
    item = items[0].get("Item") or items[0]
    genre_id = str(item.get("genreId") or "")
    if not genre_id:
        raise HTTPException(404, "ジャンルIDが取れませんでした")

    # ジャンル名も分かれば出す。IDだけだと合っているか判断できない
    name = ""
    row = (db.query(RakutenGenre)
           .filter(RakutenGenre.genre_id == int(genre_id)).first()) \
        if genre_id.isdigit() else None
    if row:
        name = row.path or row.name or ""

    d.genre_id = genre_id
    db.commit()
    return {"genre_id": genre_id, "genre_name": name,
            "from_item": d.rival_item_code}
