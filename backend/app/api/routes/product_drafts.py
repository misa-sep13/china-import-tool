"""リサーチで採用した商品の登録前ドラフト（スプレッドシートの置き換え）。

リサーチ→採用→情報を埋める→タイトル・説明文を生成→楽天へ登録、という
流れの「採用」以降を受け持つ。生成した文章は履歴として残す。
"""
import base64
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.product_draft import (
    ProductDraft, ProductDraftGeneration, ProductDraftImage,
)
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
    # バリエーション。軸が空なら単品として登録する
    variant_axis:    Optional[str] = None
    variant_axis2:   Optional[str] = None
    template_sku:    Optional[str] = None
    series_name:     Optional[str] = None
    item_specs:      Optional[dict] = None
    shipping_set:    Optional[str] = None
    variants:        Optional[list[dict]] = None
    image_urls:      Optional[list[str]] = None
    features:        Optional[list[str]] = None
    spec_rows:       Optional[list[dict]] = None
    seo_words:       Optional[str] = None
    product_notes:   Optional[str] = None
    amazon_product_type: Optional[str] = None
    amazon_jan:      Optional[str] = None
    amazon_bullets:  Optional[list[str]] = None
    amazon_attrs:    Optional[dict] = None
    amazon_sku:      Optional[str] = None
    amazon_status:   Optional[str] = None


class AdoptIn(BaseModel):
    """ウォッチリストの行を「採用」してドラフト化する。"""
    watchlist_id: int
    sku: Optional[str] = None


def _json_obj(raw):
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _json_list(raw):
    try:
        return json.loads(raw or "[]")
    except Exception:
        return []


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
        "variant_axis": d.variant_axis, "variant_axis2": d.variant_axis2,
        "variants": variants, "template_sku": d.template_sku,
        "series_name": d.series_name,
        "item_specs": _json_obj(d.item_specs),
        "shipping_set": d.shipping_set,
        "image_urls": images,
        "features": _json_list(d.features),
        "spec_rows": _json_list(d.spec_rows),
        "seo_words": d.seo_words, "product_notes": d.product_notes,
        "amazon_product_type": d.amazon_product_type,
        "amazon_jan": d.amazon_jan,
        "amazon_bullets": _json_list(d.amazon_bullets),
        "amazon_attrs": _json_obj(d.amazon_attrs),
        "amazon_sku": d.amazon_sku,
        "amazon_status": d.amazon_status or "draft",
        "amazon_asin": d.amazon_asin,
        "amazon_error": d.amazon_error,
        "amazon_submitted_at": (d.amazon_submitted_at.isoformat()
                                if d.amazon_submitted_at else None),
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
        elif k in ("features", "spec_rows"):
            setattr(d, k, json.dumps(v or [], ensure_ascii=False))
        elif k == "item_specs":
            d.item_specs = json.dumps(v or {}, ensure_ascii=False)
        elif k == "amazon_bullets":
            d.amazon_bullets = json.dumps(v or [], ensure_ascii=False)
        elif k == "amazon_attrs":
            d.amazon_attrs = json.dumps(v or {}, ensure_ascii=False)
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

    # 材料を直したらHTMLも作り直す。手で直したHTMLがある場合を考えて、
    # 材料が送られてきたときだけ組み立てる
    sent = data.model_dump(exclude_unset=True)
    if any(k in sent for k in ("features", "spec_rows", "seo_words")):
        html = copywriter.build_description(
            _json_list(d.features), _json_list(d.spec_rows), d.seo_words or "")
        d.description_pc = html
        d.description_sp = html

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
    if data.kind not in ("title", "description", "both", "material"):
        raise HTTPException(
            400, "kind は title / description / both / material のいずれかです")

    try:
        res = await copywriter.generate(_dict(d), data.kind)
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    db.add(ProductDraftGeneration(
        draft_id=d.id, kind=data.kind,
        prompt=res["prompt"], output=res["output"], model=res["model"],
    ))

    if data.kind == "material":
        # 材料をもらって、決まった形のHTMLはこちらで組み立てる。
        # HTMLごと書かせると形が崩れるため
        raw = (res["output"] or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1] if "```" in raw[3:] else raw
            raw = raw.lstrip("json").strip()
        try:
            m = json.loads(raw)
        except Exception:
            raise HTTPException(502, f"材料を読み取れませんでした: {raw[:200]}")

        features = [str(x).strip() for x in (m.get("features") or []) if str(x).strip()]
        spec_rows = [r for r in (m.get("spec_rows") or [])
                     if isinstance(r, dict) and r.get("label")]
        seo_words = str(m.get("seo_words") or "").strip()
        html = copywriter.build_description(features, spec_rows, seo_words)
        parts = {"features": features, "spec_rows": spec_rows,
                 "seo_words": seo_words, "description": html}
        if data.apply:
            d.features = json.dumps(features, ensure_ascii=False)
            d.spec_rows = json.dumps(spec_rows, ensure_ascii=False)
            d.seo_words = seo_words
            # PC・スマホとも同じものを入れる（今までそうしていた）
            d.description_pc = html
            d.description_sp = html
    else:
        parts = copywriter.split_output(data.kind, res["output"])
        # 情報が足りないとAIが断ることがある。その文を商品名として
        # 保存すると、断り文が商品名になってしまう
        if copywriter.looks_like_refusal(parts.get("title") or ""):
            raise HTTPException(
                400,
                "材料が足りず、AIが作成できませんでした。"
                "「この商品について」に、サイズ・素材・特徴などを書いてから"
                "もう一度お試しください。")
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


@router.get("/meta/rakuten-keys")
def rakuten_keys():
    """楽天APIのキーを、登録スクリプトへ渡す。

    楽天APIはIP制限がかかっていてサーバーからは呼べない（403
    CLIENT_IP_NOT_ALLOWED）。ジャンルIDの取得は手元のPCで行うため、
    サーバーが持っているキーをそこへ渡す必要がある。

    ログイン済みの本人しか叩けないので、キーが外に出ることはない。
    """
    from app.core.config import settings
    return {
        "app_id": settings.RAKUTEN_APP_ID or "",
        "access_key": settings.RAKUTEN_ACCESS_KEY or "",
        "configured": bool(settings.RAKUTEN_APP_ID and settings.RAKUTEN_ACCESS_KEY),
    }


# ---------- 雛形の下読み ----------
#
# 商品仕様はジャンルごとに項目が変わるが、楽天にその定義を返すAPIは
# 無かった（実測で404）。雛形にした商品が持っている項目を借りる。
# 同じジャンルなら同じ項目になるので、実用上はこれで足りる。

class TemplateInfoIn(BaseModel):
    """手元のスクリプトが読んだ雛形の中身を、画面用に預かる。

    雛形を読めるのはCompassにログインしたブラウザだけなので、
    サーバーからは取りに行けない。読んだ結果をここへ入れてもらう。
    """
    manage_number: str
    genre_id: Optional[str] = None
    attribute_names: list[str] = []      # 商品仕様の項目名
    shipping: Optional[dict] = None      # 配送方法セットなど
    raw: Optional[dict] = None           # 全体（あとで項目を増やすとき用）


@router.post("/meta/template-info")
def save_template_info(data: TemplateInfoIn, db: Session = Depends(get_db)):
    """雛形の中身を覚えておく。画面で項目を出すのに使う。"""
    from app.models.product_draft import ProductTemplateInfo
    row = (db.query(ProductTemplateInfo)
           .filter(ProductTemplateInfo.manage_number == data.manage_number).first())
    if row is None:
        row = ProductTemplateInfo(manage_number=data.manage_number)
        db.add(row)
    row.genre_id = data.genre_id
    row.attribute_names = json.dumps(data.attribute_names, ensure_ascii=False)
    row.shipping = json.dumps(data.shipping or {}, ensure_ascii=False)
    row.raw = json.dumps(data.raw or {}, ensure_ascii=False)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "manage_number": row.manage_number,
            "attribute_names": data.attribute_names}


@router.get("/meta/template-info")
def get_template_info(manage_number: str, db: Session = Depends(get_db)):
    """覚えておいた雛形の中身。画面がこれを見て入力欄を出す。"""
    from app.models.product_draft import ProductTemplateInfo
    row = (db.query(ProductTemplateInfo)
           .filter(ProductTemplateInfo.manage_number == manage_number).first())
    if not row:
        return {"found": False, "manage_number": manage_number,
                "attribute_names": []}
    return {
        "found": True, "manage_number": row.manage_number,
        "genre_id": row.genre_id,
        "attribute_names": _json_list(row.attribute_names),
        "shipping": json.loads(row.shipping or "{}"),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------- Amazonへ渡す画像の公開 ----------
#
# Amazonは出品時に画像を公開URLで受け取る。認証を付けられないので、
# 推測されにくい合言葉を持つ口を用意して、そのURLを渡す。

@router.get("/public-image/{token}")
def public_image(token: str, db: Session = Depends(get_db)):
    """合言葉つきの画像。Amazonが取りに来る。

    ログイン不要。合言葉は32文字のランダムなので、総当たりでは当たらない。
    出品が終わったら合言葉を消せば見られなくなる。
    """
    from fastapi import Response
    if not token or len(token) < 16:
        raise HTTPException(404, "見つかりません")
    i = (db.query(ProductDraftImage)
         .filter(ProductDraftImage.public_token == token).first())
    if not i or not i.data:
        raise HTTPException(404, "見つかりません")
    return Response(content=base64.b64decode(i.data),
                    media_type=i.mime or "image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.post("/{draft_id:int}/images/publish")
def publish_images(draft_id: int, request: Request, db: Session = Depends(get_db)):
    """預かっている画像に公開URLを付ける。出品の直前に呼ぶ。

    すでに合言葉があるものは作り直さない（Amazon側が同じURLを見ている
    ことがあるため）。
    """
    import secrets
    rows = (db.query(ProductDraftImage)
            .filter(ProductDraftImage.draft_id == draft_id)
            .order_by(ProductDraftImage.sort_order, ProductDraftImage.id).all())
    if not rows:
        return {"urls": [], "件数": 0}

    base = str(request.base_url).rstrip("/")
    urls = []
    for i in rows:
        if not i.public_token:
            i.public_token = secrets.token_urlsafe(24)
        urls.append(f"{base}/api/product-drafts/public-image/{i.public_token}")
    db.commit()
    return {"urls": urls, "件数": len(urls)}


# ---------- Amazonへの出品 ----------

class AmazonPrepareIn(BaseModel):
    """出品の下ごしらえ。競合ASINから商品タイプを決め、JANを割り当てる。"""
    rival_asin: Optional[str] = None    # 空ならドラフトの参考商品を使う
    issue_jan: bool = True              # JANが無ければ採番する


@router.post("/{draft_id:int}/amazon/prepare")
def amazon_prepare(draft_id: int, data: AmazonPrepareIn,
                   db: Session = Depends(get_db)):
    """出品の準備。商品タイプを決めて、必要なものを揃える。

    商品タイプはAmazonの分類で、これが決まらないと何を入れるべきかも
    決まらない。競合の商品から借りるのが一番確実で早い。
    """
    from app.services import amazon_api

    d = db.query(ProductDraft).filter(ProductDraft.id == draft_id).first()
    if not d:
        raise HTTPException(404, "ドラフトが見つかりません")

    asin = (data.rival_asin or d.rival_item_code or "").strip()
    # 楽天の商品コードはASINではないので、形で見分ける
    if not (len(asin) == 10 and asin.upper().startswith("B")):
        asin = ""
    if not asin:
        raise HTTPException(
            400, "参考にするAmazonのASINがありません。ASINを指定してください")

    r = amazon_api.fetch_product_type(asin)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error") or "商品タイプが分かりません")
    d.amazon_product_type = r["product_type"]

    # JANの割り当て。無ければ台帳から1つ取る
    if data.issue_jan and not d.amazon_jan:
        from app.models.amazon_research import JanCode
        free = (db.query(JanCode)
                .filter(JanCode.status == "issued", JanCode.sku.is_(None))
                .order_by(JanCode.item_seq).first())
        if free:
            free.sku = d.sku
            free.name = (d.rakuten_title or "")[:80]
            free.status = "used"
            d.amazon_jan = free.code

    db.commit()

    schema = amazon_api.fetch_product_type_schema(d.amazon_product_type)
    return {
        "product_type": d.amazon_product_type,
        "display_name": schema.get("display_name"),
        "required_fields": schema.get("required_fields") or [],
        "jan": d.amazon_jan,
        "jan_warning": None if d.amazon_jan else
            "JANコードがありません。台帳に空きがないか確認してください",
    }


class AmazonSubmitIn(BaseModel):
    draft_ids: list[int]
    dry_run: bool = True     # 既定は送らない。中身を見てから実行する


@router.post("/amazon/submit")
def amazon_submit(data: AmazonSubmitIn, request: Request,
                  db: Session = Depends(get_db)):
    """まとめてAmazonへ出品する。

    送る前に全件そろっているか確かめ、1件でも足りなければ1件も送らない。
    途中まで登録して失敗するのが一番後始末が大変なため。
    """
    import secrets
    from app.services import amazon_api
    from app.models.amazon_research import AmazonResearchSettings

    st = db.query(AmazonResearchSettings).first()
    brand = (st.brand_name if st else "") or ""

    rows = (db.query(ProductDraft)
            .filter(ProductDraft.id.in_(data.draft_ids)).all())
    if not rows:
        raise HTTPException(400, "対象がありません")

    # 事前チェック
    problems = []
    for d in rows:
        miss = []
        if not d.sku:
            miss.append("SKU")
        if not d.rakuten_title:
            miss.append("商品名")
        if not d.price:
            miss.append("価格")
        if not d.amazon_product_type:
            miss.append("商品タイプ（先に「出品の準備」を押す）")
        if not d.amazon_jan:
            miss.append("JANコード")
        if not brand:
            miss.append("ブランド名（設定で入れる）")
        if miss:
            problems.append({"sku": d.sku or f"id={d.id}", "足りないもの": miss})
    if problems:
        return {"ok": False, "送っていません": True, "問題": problems}

    base = str(request.base_url).rstrip("/")
    results = []
    for d in rows:
        # 画像に公開URLを付ける。Amazonが取りに来る
        imgs = (db.query(ProductDraftImage)
                .filter(ProductDraftImage.draft_id == d.id)
                .order_by(ProductDraftImage.sort_order, ProductDraftImage.id).all())
        urls = []
        for i in imgs:
            if not i.public_token:
                i.public_token = secrets.token_urlsafe(24)
            urls.append(f"{base}/api/product-drafts/public-image/{i.public_token}")

        draft = _dict(d)
        draft["brand_name"] = brand
        draft["amazon_jan"] = d.amazon_jan
        draft["amazon_bullets"] = _json_list(d.amazon_bullets)
        draft["amazon_image_urls"] = urls

        attrs = amazon_api.build_listing_attributes(
            draft, d.amazon_product_type, _json_obj(d.amazon_attrs))
        sku = d.amazon_sku or d.sku

        if data.dry_run:
            results.append({"sku": sku, "dry_run": True,
                            "product_type": d.amazon_product_type,
                            "attributes": attrs})
            continue

        r = amazon_api.submit_listing(sku, d.amazon_product_type, attrs)
        if r.get("ok"):
            d.amazon_status = "submitted"
            d.amazon_submitted_at = datetime.now(timezone.utc)
            d.amazon_error = None
        else:
            d.amazon_status = "failed"
            d.amazon_error = json.dumps(r, ensure_ascii=False)[:2000]
        results.append({"sku": sku, **r})

    db.commit()
    ok = sum(1 for r in results if r.get("ok") or r.get("dry_run"))
    return {"ok": True, "dry_run": data.dry_run,
            "成功": ok, "失敗": len(results) - ok, "結果": results}
