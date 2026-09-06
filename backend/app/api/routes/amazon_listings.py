"""Amazonへの商品登録。

競合リサーチシートを元に、1リサーチ＝1商品として出品内容をまとめる。
これまでの登録画面は楽天用のドラフト（product_drafts）を流用していて、
シートの商品タイトル・検索キーワード・三辺・重量が一切渡っていなかった。
ここではシートを直接の元にしている。
"""
import base64
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.amazon_research import (
    AmazonResearchSheet, AmazonResearchSettings, JanCode,
)
from app.models.amazon_research_page import AmazonResearchPage
from app.models.product import Product
from app.models.amazon_listing import (
    AmazonListing, AmazonListingChild, AmazonListingImage,
)
from app.services import amazon_listing_sync as sync
from app.services import listing_prompt
from app.services import amazon_api

router = APIRouter(prefix="/amazon-listings", tags=["amazon-listings"])

MAX_IMAGE_BYTES = 8 * 1024 * 1024      # Amazonが取りに来られる大きさの目安


# ---------- 入れ物 ----------

class ListingIn(BaseModel):
    title: Optional[str] = None
    keywords: Optional[str] = None
    bullets: Optional[list] = None
    description: Optional[str] = None
    brand: Optional[str] = None
    price: Optional[int] = None
    len_a: Optional[float] = None
    len_b: Optional[float] = None
    len_c: Optional[float] = None
    weight: Optional[float] = None
    rival_asin: Optional[str] = None
    attrs: Optional[dict] = None
    must_kw: Optional[str] = None       # ② 商品説明に入れる必須キーワード
    diff_points: Optional[str] = None   # 自社の差別化ポイント
    parent_sku: Optional[str] = None
    variation_theme: Optional[str] = None
    axis1_label: Optional[str] = None
    axis2_label: Optional[str] = None
    status: Optional[str] = None
    is_test: Optional[bool] = None
    children: Optional[list] = None      # [{id?, sku, title, axis1, axis2, price}]


class SubmitIn(BaseModel):
    listing_ids: list
    dry_run: bool = True


# ---------- 小道具 ----------

def _sheet(db: Session) -> dict:
    row = (db.query(AmazonResearchSheet)
           .filter(AmazonResearchSheet.workspace == "default").first())
    return sync.load_sheet(row.data if row else None)


def _loads(raw, fallback):
    if not raw:
        return fallback
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return fallback
    return v if isinstance(v, type(fallback)) else fallback


def _child_out(c: AmazonListingChild) -> dict:
    return {"id": c.id, "sort_order": c.sort_order, "sku": c.sku, "jan": c.jan,
            "title": c.title, "axis1": c.axis1, "axis2": c.axis2,
            "price": c.price, "status": c.status, "asin": c.asin,
            "error": c.error}


def _image_out(i: AmazonListingImage) -> dict:
    return {"id": i.id, "child_id": i.child_id, "file_name": i.file_name,
            "mime": i.mime, "size": i.size, "sort_order": i.sort_order,
            "url": f"/api/amazon-listings/public-image/{i.public_token}"}


def _out(row: AmazonListing, db: Session, src: dict = None) -> dict:
    kids = (db.query(AmazonListingChild)
            .filter(AmazonListingChild.listing_id == row.id)
            .order_by(AmazonListingChild.sort_order).all())
    imgs = (db.query(AmazonListingImage)
            .filter(AmazonListingImage.listing_id == row.id)
            .order_by(AmazonListingImage.sort_order).all())
    d = {
        "id": row.id, "research_id": row.research_id,
        "research_title": row.research_title,
        "title": row.title, "keywords": row.keywords,
        "bullets": _loads(row.bullets, []),
        "description": row.description, "brand": row.brand, "price": row.price,
        "len_a": row.len_a, "len_b": row.len_b, "len_c": row.len_c,
        "weight": row.weight,
        "rival_asin": row.rival_asin, "product_type": row.product_type,
        "attrs": _loads(row.attrs, {}),
        "parent_sku": row.parent_sku,
        "variation_theme": row.variation_theme,
        "axis1_label": row.axis1_label, "axis2_label": row.axis2_label,
        "monthly_sales": row.monthly_sales, "review_count": row.review_count,
        "review_rate": row.review_rate, "profit_rate": row.profit_rate,
        "rival_image": row.rival_image,
        "status": row.status,
        "is_test": bool(row.is_test),
        "synced_at": row.synced_at.isoformat() if row.synced_at else None,
        "children": [_child_out(c) for c in kids],
        "images": [_image_out(i) for i in imgs],
    }
    if src:
        # シート側の今の中身。取り込み直すと何が変わるかを画面で見せるため
        d["sheet"] = src
        # 出品原稿はシートが正。二重に持つとずれるので、常にシートの値を返す
        d.update(_read_sheet_draft(src))
        # 出品原稿を書くときの材料。競合の商品仕様・レビュー・分析の結果を
        # 登録画面でも読めるようにする（別タブへ戻らずに済むように）
        ids = [src["research_id"]] + [c.get("row_id") for c in src.get("rows", [])]
        d["notes"] = _notes_for(db, [i for i in ids if i])
    return d


def _notes_for(db: Session, ids: list) -> dict:
    """調査メモを必要なぶんだけ読む。レビューは数千文字あるので字数も返す。"""
    if not ids:
        return {}
    rows = (db.query(AmazonResearchPage)
            .filter(AmazonResearchPage.workspace == "default",
                    AmazonResearchPage.row_id.in_(ids)).all())
    out = {}
    for r in rows:
        out[r.row_id] = {
            "spec": r.spec or "", "reviews": r.reviews or "",
            "keywords": r.keywords or "", "imgtext": r.imgtext or "",
            "analysis": r.analysis or "",
        }
    return out


# ---------- 一覧 ----------

@router.get("")
def list_listings(db: Session = Depends(get_db)):
    """シートの候補と、登録レコードを突き合わせて返す。

    まだ登録を始めていないリサーチも出す（始めるボタンを出すため）。
    """
    cands = sync.candidates(_sheet(db))
    saved = {r.research_id: r for r in db.query(AmazonListing).all()}

    rows = []
    for c in cands:
        row = saved.pop(c["research_id"], None)
        rows.append({
            "research_id": c["research_id"],
            "research_title": c["research_title"],
            "status_on_sheet": c["status_on_sheet"],
            "status_label": c["status_label"],
            "rival_asin": c["rival_asin"],
            "rival_image": c["rival_image"],
            "monthly_sales": c["monthly_sales"],
            "review_count": c["review_count"],
            "review_rate": c["review_rate"],
            "price": c["price"],
            "profit_rate": c["profit_rate"],
            "cost_missing": c["cost_missing"],
            # 出品原稿がシートにあるか。無ければ登録画面で書いてもらう
            "has_title": bool(c["title"]),
            "has_keywords": bool(c["keywords"]),
            "bullet_count": len(c["bullets"]),
            "child_count": len(c["children"]),
            "listing_id": row.id if row else None,
            "listing_status": row.status if row else None,
        })

    # シートから消えたが登録レコードだけ残っているもの。取りこぼさないよう出す
    for r in saved.values():
        rows.append({
            "research_id": r.research_id, "research_title": r.research_title,
            "status_on_sheet": "", "status_label": "",
            "rival_asin": r.rival_asin,
            "rival_image": r.rival_image, "monthly_sales": r.monthly_sales,
            "review_count": r.review_count, "review_rate": r.review_rate,
            "price": r.price, "profit_rate": r.profit_rate, "cost_missing": [],
            "has_title": bool(r.title), "has_keywords": bool(r.keywords),
            "bullet_count": len(_loads(r.bullets, [])), "child_count": 0,
            "listing_id": r.id, "listing_status": r.status,
            "orphan": True,
        })
    return {"rows": rows}


# ---------- 取り込み ----------

@router.post("/sync/{research_id}")
def sync_one(research_id: str, overwrite: bool = False,
             db: Session = Depends(get_db)):
    """シートから1件取り込む。無ければ作る。

    overwrite=False（既定）だと、画面で直したところは残し、
    空の欄だけをシートの値で埋める。
    """
    src = None
    for c in sync.candidates(_sheet(db)):
        if c["research_id"] == research_id:
            src = c
            break
    if src is None:
        raise HTTPException(404, "そのリサーチがシートにありません")

    row = (db.query(AmazonListing)
           .filter(AmazonListing.research_id == research_id).first())
    if row is None:
        row = AmazonListing(research_id=research_id)
        db.add(row)

    def put(field, value):
        """空の欄だけ埋める。overwrite なら上書き。"""
        if value in (None, "", []):
            return
        if overwrite or not getattr(row, field, None):
            setattr(row, field, value)

    row.research_title = src["research_title"]
    put("title", src["title"])
    put("keywords", src["keywords"])
    put("bullets", json.dumps(src["bullets"], ensure_ascii=False)
        if src["bullets"] else None)
    put("description", src["description"])
    put("price", src["price"])
    put("len_a", src["len_a"])
    put("len_b", src["len_b"])
    put("len_c", src["len_c"])
    put("weight", src["weight"])
    put("rival_asin", src["rival_asin"])

    # 判断根拠はシートが正。毎回そのまま写す
    row.rival_image = src["rival_image"]
    row.monthly_sales = src["monthly_sales"]
    row.review_count = src["review_count"]
    row.review_rate = src["review_rate"]
    row.profit_rate = src["profit_rate"]
    row.synced_at = datetime.now(timezone.utc)
    db.flush()

    # 子はシートに追従させる（SKU・JANはこちらのものを残す）
    _pull_children(db, row, src)
    db.commit()
    db.refresh(row)
    return _out(row, db, src)


@router.get("/{listing_id:int}")
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")
    # すでに登録を始めてあるので、採用を外していても読めるようにする
    src = None
    for c in sync.candidates(_sheet(db), all_status=True):
        if c["research_id"] == row.research_id:
            src = c
            break
    # 開くたびにシートの子へ追従させる。シートで子を足しても
    # ここに出てこない、ということがないように
    if src:
        _pull_children(db, row, src)
        db.commit()
        db.refresh(row)
    return _out(row, db, src)


@router.put("/{listing_id:int}")
def update_listing(listing_id: int, body: ListingIn,
                   db: Session = Depends(get_db)):
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")

    data = body.model_dump(exclude_unset=True)
    kids = data.pop("children", None)
    for k, v in data.items():
        if k == "bullets":
            row.bullets = json.dumps([b for b in (v or []) if str(b).strip()],
                                     ensure_ascii=False)
        elif k == "attrs":
            row.attrs = json.dumps(v or {}, ensure_ascii=False)
        else:
            setattr(row, k, v)

    if kids is not None:
        keep = set()
        for i, ch in enumerate(kids):
            cid = ch.get("id")
            c = db.get(AmazonListingChild, cid) if cid else None
            if c is None or c.listing_id != row.id:
                c = AmazonListingChild(listing_id=row.id)
                db.add(c)
            c.sort_order = i
            c.sku = (ch.get("sku") or "").strip() or None
            c.title = ch.get("title")
            c.axis1 = ch.get("axis1")
            c.axis2 = ch.get("axis2")
            c.price = ch.get("price")
            db.flush()
            keep.add(c.id)
        for c in (db.query(AmazonListingChild)
                  .filter(AmazonListingChild.listing_id == row.id).all()):
            # JANを発番済みの子は、消す指示でも残す（番号を宙に浮かせないため）
            if c.id not in keep and not c.jan:
                db.delete(c)

    # 出品原稿はシートを正とするので、こちらで直したぶんも書き戻す。
    # そうしないと、シートを開いたときに古い内容に戻って見える
    draft = {k: v for k, v in data.items()
             if k in ("title", "keywords", "description",
                      "must_kw", "diff_points")}
    if "bullets" in data:
        draft["description"] = "\n".join(
            [str(b) for b in (data["bullets"] or []) if str(b).strip()])
    back_kids = None
    if kids is not None:
        db.flush()
        back_kids = [
            {"axis1": c.axis1, "title": c.title}
            for c in (db.query(AmazonListingChild)
                      .filter(AmazonListingChild.listing_id == row.id)
                      .order_by(AmazonListingChild.sort_order).all())]
    if draft or back_kids is not None:
        _write_sheet_draft(db, row.research_id, draft, back_kids)

    db.commit()
    db.refresh(row)
    return _out(row, db)


@router.delete("/{listing_id:int}")
def delete_listing(listing_id: int, db: Session = Depends(get_db)):
    """登録レコードを消す。シートのリサーチには手を付けない。

    Amazonへ送ったあとのものは消さない（何を出したか分からなくなるため）。
    """
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")
    if row.status in ("submitted", "live"):
        raise HTTPException(400, "すでにAmazonへ送ったものは消せません")

    kids = (db.query(AmazonListingChild)
            .filter(AmazonListingChild.listing_id == row.id).all())
    # JANを発番済みのものは消させない。消すと番号だけ台帳に残り、
    # 何に使ったか分からなくなる（同じ番号は二度と使えない）
    used = [c.jan for c in kids if c.jan]
    if used:
        raise HTTPException(
            400, "JANを発番済みなので消せません（" + "・".join(used[:3])
                 + "）。番号が宙に浮いてしまいます")
    for c in kids:
        db.delete(c)
    for i in (db.query(AmazonListingImage)
              .filter(AmazonListingImage.listing_id == row.id).all()):
        db.delete(i)
    db.delete(row)
    db.commit()
    return {"deleted": True}


# ---------- 商品画像 ----------
#
# Amazonは画像をURLで取りに来る。手元のファイルをそのまま渡せないので、
# ここで預かってトークン付きの公開URLで読ませる。
# 楽天のR-Cabinetは使わない（Amazonが取りに行けるか分からないため）。

@router.post("/{listing_id:int}/images")
async def add_image(listing_id: int, child_id: Optional[int] = None,
                    file: UploadFile = File(...),
                    db: Session = Depends(get_db)):
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")

    blob = await file.read()
    if not blob:
        raise HTTPException(400, "中身が空です")
    if len(blob) > MAX_IMAGE_BYTES:
        raise HTTPException(400,
                            f"画像が大きすぎます（{len(blob)//1024//1024}MB）。8MBまでにしてください")
    mime = (file.content_type or "").lower()
    if not mime.startswith("image/"):
        raise HTTPException(400, "画像ファイルを選んでください")

    last = (db.query(AmazonListingImage)
            .filter(AmazonListingImage.listing_id == listing_id)
            .order_by(AmazonListingImage.sort_order.desc()).first())
    img = AmazonListingImage(
        listing_id=listing_id, child_id=child_id,
        file_name=file.filename or "image", mime=mime, size=len(blob),
        data=base64.b64encode(blob).decode(),
        sort_order=((last.sort_order or 0) + 1) if last else 0,
        public_token=secrets.token_urlsafe(24),
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return _image_out(img)


@router.delete("/images/{image_id:int}")
def delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.get(AmazonListingImage, image_id)
    if not img:
        raise HTTPException(404, "ありません")
    db.delete(img)
    db.commit()
    return {"deleted": True}


@router.put("/images/{image_id:int}/order")
def move_image(image_id: int, sort_order: int, db: Session = Depends(get_db)):
    """並び順を変える。0番がメイン画像になる。"""
    img = db.get(AmazonListingImage, image_id)
    if not img:
        raise HTTPException(404, "ありません")
    img.sort_order = sort_order
    db.commit()
    return _image_out(img)


@router.get("/public-image/{token}")
def public_image(token: str, db: Session = Depends(get_db)):
    """Amazonが取りに来る口。認証なしで開ける必要がある。

    推測できないトークンを付けてあるので、URLを知らなければ開けない。
    """
    img = (db.query(AmazonListingImage)
           .filter(AmazonListingImage.public_token == token).first())
    if not img or not img.data:
        raise HTTPException(404, "ありません")
    return Response(content=base64.b64decode(img.data),
                    media_type=img.mime or "image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


# ---------- 出品の準備 ----------

def _issue_jan(db: Session, sku: str, name: str, test: bool = False) -> str:
    """JANを1つ発番して台帳に残す。amazon_research 側と同じ採番。

    バリエーションでは子の数だけ続けて呼ぶ。台帳に書き込む前に次を採ると
    同じ番号になってしまうので、1件ごとに flush して確定させる。
    """
    from app.api.routes.amazon_research import _get_settings, _make_jan
    st = _get_settings(db)
    prefix = (st.gs1_prefix or "").strip()
    if not prefix.isdigit() or len(prefix) not in (7, 9):
        raise HTTPException(
            400, "先にGS1事業者コード（7桁か9桁）を設定してください")
    last = db.query(JanCode).order_by(JanCode.item_seq.desc()).first()
    seq = (last.item_seq or 0) + 1 if last else 1
    code = _make_jan(prefix, seq)
    db.add(JanCode(code=code, item_seq=seq, sku=sku or None,
                   name=name or None,
                   status="test" if test else "issued",
                   note="動作確認のための出品" if test else None))
    db.flush()
    return code


@router.post("/{listing_id:int}/prepare")
def prepare(listing_id: int, db: Session = Depends(get_db)):
    """出品に足りないものを揃える。

      1. 競合ASINから商品タイプを引く
      2. その商品タイプで何が必須かを調べる
      3. SKUがまだ無い子に採番し、JANを発番する

    JANはSKUごとに要る。同じ番号を2つの商品に使うと同一視されるため。
    """
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")
    if not (row.rival_asin or "").strip():
        raise HTTPException(400, "参考にする競合のASINを入れてください")

    pt = amazon_api.fetch_product_type(row.rival_asin.strip())
    if not pt.get("ok"):
        raise HTTPException(400, pt.get("error") or "商品タイプが分かりませんでした")
    row.product_type = pt["product_type"]

    schema = amazon_api.fetch_product_type_schema(row.product_type)
    fields = schema.get("fields") or [] if schema.get("ok") else []

    # 採番する前に、シートの子へそろえておく
    for c in sync.candidates(_sheet(db), all_status=True):
        if c["research_id"] == row.research_id:
            _pull_children(db, row, c)
            db.flush()
            break

    kids = (db.query(AmazonListingChild)
            .filter(AmazonListingChild.listing_id == row.id)
            .order_by(AmazonListingChild.sort_order).all())
    if not kids:
        kids = [AmazonListingChild(listing_id=row.id, sort_order=0,
                                   title=row.title or "")]
        db.add(kids[0])
        db.flush()

    # SKUは「a」＋連番（a01, a02, …）が親。子はその下に付ける。
    # Amazonは単品でも親子で作るのが推奨とされているので、親は常に作る。
    #   単品          a05（親） / a05_1（子）
    #   バリエーション a06（親） / a06_black・a06_s（子）
    #
    # すでにSKUのある子がいれば、その頭を引き継ぐ。番号を採り直すと
    # 発番済みのJANとの結びつきがずれるため。
    head = (row.parent_sku or "").strip()
    if not head:
        for c in kids:
            if (c.sku or "").strip():
                head = c.sku.strip().split("_")[0]
                break
    if not head:
        head = next_sku(db, "a")[0]
    row.parent_sku = head

    taken = {(c.sku or "").strip() for c in kids if (c.sku or "").strip()}
    single = len(kids) == 1
    for i, c in enumerate(kids):
        if (c.sku or "").strip():
            continue
        # 単品は _1。バリエーションは軸の値から作り、作れなければ連番
        suf = "1" if single else (sku_suffix(c.axis1) or sku_suffix(c.axis2)
                                  or str(i + 1))
        cand = f"{head}_{suf}"
        n = i + 1
        while cand in taken:
            n += 1
            cand = f"{head}_{suf}{n}"
        c.sku = cand
        taken.add(cand)

    issued = []
    for c in kids:
        if not c.jan:
            c.jan = _issue_jan(db, c.sku, c.title or row.title or "",
                               test=bool(row.is_test))
            issued.append({"sku": c.sku, "jan": c.jan})

    if row.status == "draft":
        row.status = "prepared"
    db.commit()
    db.refresh(row)

    out = _out(row, db)
    out["product_type_name"] = pt.get("item_name")
    out["required_fields"] = fields
    out["issued_jan"] = issued
    if not schema.get("ok"):
        out["schema_error"] = schema.get("error")
    return out


# 出ていても送信は止めないもの。画像は後から足せるし、
# ノーブランドの案内はそもそも「そう出します」という知らせなので
_NOT_BLOCKING = ("画像がありません", "ノーブランド")


def _blocking(problems: list) -> list:
    return [p for p in problems
            if not any(k in p for k in _NOT_BLOCKING)]


@router.get("/{listing_id:int}/check")
def check(listing_id: int, db: Session = Depends(get_db)):
    """送る前の見落としを洗い出す。

    blocking に入っているものが残っていると出品できない。
    画像なしとノーブランドの案内は、出しても送信は止めない。
    """
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")
    problems = _problems(row, db)
    return {"problems": problems, "blocking": _blocking(problems)}


def _problems(row: AmazonListing, db: Session) -> list:
    """出品として成り立たないところを挙げる。"""
    p = []
    if not (row.title or "").strip():
        p.append("商品タイトルがありません")
    elif len(row.title) > 200:
        p.append(f"商品タイトルが長すぎます（{len(row.title)}字）")
    if not row.product_type:
        p.append("商品タイプがありません。「出品の準備」を押してください")
    st = db.query(AmazonResearchSettings).first()
    if st is None or not st.brand_ready:
        p.append("ブランド登録がまだなので「ノーブランド」で出します"
                 "（自社ブランド名では弾かれます）")
        # ブランド名がタイトルに残っていると、ノーブランドと食い違って弾かれる
        own = ((st.brand_name if st else "") or "").strip()
        if own and own.lower() in (row.title or "").lower():
            p.append(f"商品タイトルに「{own}」が入っています。"
                     "ノーブランドで出す間は外してください")
    elif not (row.brand or st.brand_name or "").strip():
        p.append("ブランド名がありません")
    if not row.price:
        p.append("価格がありません")
    if not _loads(row.bullets, []):
        p.append("商品の要点が1つもありません")

    kw = (row.keywords or "").strip()
    if not kw:
        p.append("検索キーワードがありません")
    elif len(kw.encode("utf-8")) >= 500:
        p.append(f"検索キーワードが上限です（{len(kw.encode('utf-8'))}バイト／500未満）")

    if not all([row.len_a, row.len_b, row.len_c, row.weight]):
        p.append("三辺と重量のどれかが空です")

    imgs = (db.query(AmazonListingImage)
            .filter(AmazonListingImage.listing_id == row.id).all())
    if not imgs:
        p.append("商品画像がありません。Amazonは画像が無いと公開されないことがあります")

    kids = (db.query(AmazonListingChild)
            .filter(AmazonListingChild.listing_id == row.id).all())
    if not kids:
        p.append("出品するSKUがありません")
    for c in kids:
        who = c.title[:16] if c.title else f"#{c.sort_order + 1}"
        if not c.sku:
            p.append(f"[{who}] SKUがありません")
        if not c.jan:
            p.append(f"[{who}] JANがありません")
    # バリエーションは常に色で登録する（色でないと選択肢ごとの画像が出ない）
    if len(kids) > 1:
        shared = any(i.child_id is None for i in imgs)
        for c in kids:
            who = c.axis1 or c.title[:16] if (c.axis1 or c.title) else c.sku
            if not (c.axis1 or "").strip():
                p.append(f"[{c.title[:16] if c.title else c.sku}] 色が空です")
            # 色ごとの画像が無ければ共通を使う。どちらも無ければ画像なし
            if imgs and not shared and not any(i.child_id == c.id for i in imgs):
                p.append(f"[{who}] 画像がありません（共通の画像もありません）")
    return p


# ---------- Amazonへ送る ----------

# ブランド登録（Amazonブランド登録）が済むまで、自社ブランド名では弾かれる。
# 済むまでは「ノーブランド」で出す。設定の brand_ready で切り替える。
NO_BRAND = "ノーブランド"


def _brand_for(db: Session, row: AmazonListing) -> str:
    st = db.query(AmazonResearchSettings).first()
    if st is not None and st.brand_ready:
        return (row.brand or st.brand_name or "").strip()
    return NO_BRAND


# ---------- どのカテゴリでもだいたい聞かれる項目 ----------
#
# 「電池が必要な商品ですか？」のように、商品タイプが違ってもほぼ必ず
# required に入る項目がある。商品ごとに入れ直すのは手間なので、
# 設定に既定値を1度だけ持たせ、出品のたびに差し込む。
#
# 商品ごとに変えたいときは、その商品の必須項目で上書きできる
# （商品側の値のほうが優先される）。

COMMON_FIELDS = [
    {"name": "batteries_required", "label": "電池・バッテリーが必要な商品ですか？",
     "type": "bool", "default": "false"},
    {"name": "batteries_included", "label": "電池・バッテリーは同梱されていますか？",
     "type": "bool", "default": "false"},
    {"name": "country_of_origin", "label": "原産国",
     "type": "select", "default": "CN",
     "choices": [["CN", "中国"], ["JP", "日本"], ["VN", "ベトナム"],
                 ["KR", "韓国"], ["TW", "台湾"], ["US", "アメリカ"]]},
    {"name": "supplier_declared_dg_hz_regulation", "label": "危険物の該当性",
     "type": "select", "default": "not_applicable",
     "choices": [["not_applicable", "該当なし"],
                 ["ghs", "GHS（化学品）"],
                 ["storage", "保管の規制あり"],
                 ["transportation", "輸送の規制あり"]]},
]

_COMMON_DEFAULTS = {f["name"]: f["default"] for f in COMMON_FIELDS}
_COMMON_TYPE = {f["name"]: f["type"] for f in COMMON_FIELDS}


def _typed(name: str, value):
    """Amazonへ送る形にそろえる。真偽値を文字列のまま送ると弾かれる。"""
    if _COMMON_TYPE.get(name) == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "はい")
    return value


def common_attrs(db: Session) -> dict:
    """設定に入っている既定値。未設定なら初期値を使う。"""
    st = db.query(AmazonResearchSettings).first()
    saved = {}
    if st is not None and st.common_attrs:
        try:
            v = json.loads(st.common_attrs)
            if isinstance(v, dict):
                saved = v
        except (ValueError, TypeError):
            pass
    out = dict(_COMMON_DEFAULTS)
    out.update({k: v for k, v in saved.items() if v not in (None, "")})
    return {k: _typed(k, v) for k, v in out.items()}


def _public_base() -> str:
    """Amazonが画像を取りに来るときの土台となるURL。"""
    import os
    return (os.getenv("PUBLIC_BASE_URL")
            or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")


# バリエーションは必ず色（COLOR）で登録する。
#
# Amazonはバリエーションテーマが色でないと、選択肢ごとの画像が出ない。
# 個数違い・サイズ違いでも色として登録し、値のほうに「2個/ブラック」の
# ように書く（Amazonの商品ページでも「色: 4個/クリア」と出る）。
VARIATION_THEME = "COLOR"


def _axis_attrs(row: AmazonListing, child: AmazonListingChild) -> dict:
    """子の軸の値。色として送る。"""
    v = (child.axis1 or "").strip()
    return {"color": v} if v else {}


def _attributes(row: AmazonListing, child: AmazonListingChild,
                db: Session, parent_sku: str = None) -> dict:
    """1SKUぶんの attributes を組み立てる。

    Amazonは項目ごとに [{"value": ..., "marketplace_id": ...}] の形を取る。
    これまで送れていなかった検索キーワード・三辺・重量もここで入れる。
    """
    mp = amazon_api._RESEARCH_MP
    # 共通の既定値を土台に、商品ごとの値で上書きする
    extra = dict(common_attrs(db))
    extra.update({k: _typed(k, v)
                  for k, v in (_loads(row.attrs, {}) or {}).items()
                  if v not in (None, "")})

    def one(v, **kw):
        return [{"value": v, "marketplace_id": mp, **kw}]

    a = {}
    a["item_name"] = one((child.title or row.title or "").strip())
    brand = _brand_for(db, row)
    if brand:
        a["brand"] = one(brand)
    if row.description:
        a["product_description"] = one(row.description)

    bullets = _loads(row.bullets, [])
    if bullets:
        a["bullet_point"] = [{"value": b, "marketplace_id": mp}
                             for b in bullets[:5] if str(b).strip()]

    # 検索キーワード。これまで一度も送っていなかった
    if (row.keywords or "").strip():
        a["generic_keyword"] = one(row.keywords.strip())

    if child.jan:
        a["externally_assigned_product_identifier"] = one(child.jan, type="ean")

    price = child.price or row.price
    if price:
        a["purchasable_offer"] = [{
            "marketplace_id": mp, "currency": "JPY",
            "our_price": [{"schedule": [{"value_with_tax": int(price)}]}],
        }]
    # 在庫は0で作る。実在庫は既存の在庫連携が入れる
    a["fulfillment_availability"] = [{
        "fulfillment_channel_code": "DEFAULT", "quantity": 0,
    }]
    a["condition_type"] = one("new_new")

    # 三辺と重量。必須なのにこれまで空だった。
    # 長い順に length / width / height へ入れる
    if all([row.len_a, row.len_b, row.len_c]):
        dims = sorted([row.len_a, row.len_b, row.len_c], reverse=True)
        a["item_package_dimensions"] = [{
            "marketplace_id": mp,
            "length": {"value": dims[0], "unit": "centimeters"},
            "width":  {"value": dims[1], "unit": "centimeters"},
            "height": {"value": dims[2], "unit": "centimeters"},
        }]
    if row.weight:
        a["item_package_weight"] = [{
            "marketplace_id": mp, "value": row.weight, "unit": "kilograms",
        }]

    # 画像。この子ぶんが無ければ親の画像を使う
    base = _public_base()
    if base:
        imgs = (db.query(AmazonListingImage)
                .filter(AmazonListingImage.listing_id == row.id)
                .order_by(AmazonListingImage.sort_order).all())
        mine = ([i for i in imgs if i.child_id == child.id]
                or [i for i in imgs if i.child_id is None])
        urls = [f"{base}/api/amazon-listings/public-image/{i.public_token}"
                for i in mine]
        if urls:
            a["main_product_image_locator"] = [
                {"marketplace_id": mp, "media_location": urls[0]}]
            if len(urls) > 1:
                a["other_product_image_locator"] = [
                    {"marketplace_id": mp, "media_location": u}
                    for u in urls[1:9]]

    # バリエーションの子。親との紐づけと、軸の値を入れる
    if parent_sku is not None:
        a["parentage_level"] = one("child")
        a["child_parent_sku_relationship"] = [{
            "marketplace_id": mp, "child_relationship_type": "variation",
            "parent_sku": parent_sku,
        }]
        # 軸がある（＝本当のバリエーション）ときだけテーマを送る
        axis = _axis_attrs(row, child)
        if axis:
            a["variation_theme"] = [{"marketplace_id": mp,
                                     "name": VARIATION_THEME}]
        for key, val in axis.items():
            a[key] = one(val)

    # 商品タイプごとの必須項目。画面で入れてもらったもの
    for k, v in extra.items():
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        a[k] = one(v)
    return a


def _parent_attributes(row: AmazonListing, has_variation: bool = True,
                       db: Session = None) -> dict:
    """親。売り物ではないので価格も在庫も付けない。

    Amazonは単品でも親子で作るのが推奨なので、バリエーションが無くても
    親は出す。そのときはバリエーションテーマを付けない
    （軸が無いのにテーマだけ送ると弾かれるため）。
    """
    mp = amazon_api._RESEARCH_MP
    extra = dict(common_attrs(db)) if db is not None else {}
    extra.update({k: _typed(k, v)
                  for k, v in (_loads(row.attrs, {}) or {}).items()
                  if v not in (None, "")})

    def one(v, **kw):
        return [{"value": v, "marketplace_id": mp, **kw}]

    a = {
        "item_name": one((row.title or "").strip()),
        "parentage_level": one("parent"),
        "condition_type": one("new_new"),
    }
    if has_variation:
        a["variation_theme"] = [{"marketplace_id": mp, "name": VARIATION_THEME}]
    brand = _brand_for(db, row) if db is not None else (row.brand or "")
    if brand:
        a["brand"] = one(brand)
    if row.description:
        a["product_description"] = one(row.description)
    bullets = _loads(row.bullets, [])
    if bullets:
        a["bullet_point"] = [{"value": b, "marketplace_id": mp}
                             for b in bullets[:5] if str(b).strip()]
    if (row.keywords or "").strip():
        a["generic_keyword"] = one(row.keywords.strip())
    # 親にも画像を付ける。共通のものを使う（無ければ子の1枚目）
    base = _public_base()
    if db is not None and base:
        imgs = (db.query(AmazonListingImage)
                .filter(AmazonListingImage.listing_id == row.id)
                .order_by(AmazonListingImage.sort_order).all())
        mine = [i for i in imgs if i.child_id is None] or imgs
        urls = [f"{base}/api/amazon-listings/public-image/{i.public_token}"
                for i in mine]
        if urls:
            a["main_product_image_locator"] = [
                {"marketplace_id": mp, "media_location": urls[0]}]
            if len(urls) > 1:
                a["other_product_image_locator"] = [
                    {"marketplace_id": mp, "media_location": u}
                    for u in urls[1:9]]

    for k, v in extra.items():
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        a[k] = one(v)
    return a


@router.post("/submit")
def submit(body: SubmitIn, db: Session = Depends(get_db)):
    """選んだものをAmazonへ出す。

    dry_run=True なら送らずに、送る中身をそのまま返す。
    実際に出す前に中身を確かめてほしいので、既定はTrue。

    バリエーションがある場合は親→子の順に送る。
    親が失敗したら子は送らない（親のいない子はエラーになるため）。
    """
    if not body.listing_ids:
        raise HTTPException(400, "選ばれていません")

    results = []
    for lid in body.listing_ids:
        row = db.get(AmazonListing, lid)
        if not row:
            results.append({"listing_id": lid, "ok": False,
                            "error": "見つかりません"})
            continue

        problems = _problems(row, db)
        kids = (db.query(AmazonListingChild)
                .filter(AmazonListingChild.listing_id == row.id)
                .order_by(AmazonListingChild.sort_order).all())
        # 単品でも親子で作る（Amazonの推奨）。子が1つなら
        # バリエーションテーマは持たせず、親1・子1の形で出す
        has_variation = len(kids) > 1

        item = {"listing_id": lid, "title": row.title,
                "product_type": row.product_type,
                "problems": problems, "sent": []}

        blocking = _blocking(problems)
        if blocking and not body.dry_run:
            item["ok"] = False
            item["error"] = "足りないところがあるので送っていません"
            results.append(item)
            continue

        parent_sku = ((row.parent_sku or "").strip()
                      or (kids[0].sku or "").split("_")[0]
                      or f"a{row.id:02d}")
        # 親を先に出す。親が失敗したら子は送らない（親のいない子は弾かれる）
        attrs = _parent_attributes(row, has_variation, db)
        rec = {"sku": parent_sku, "kind": "親", "attributes": attrs}
        if body.dry_run:
            rec["dry_run"] = True
            item["sent"].append(rec)
        else:
            r = amazon_api.submit_listing(parent_sku, row.product_type, attrs)
            rec.update(r)
            item["sent"].append(rec)
            if not r.get("ok"):
                item["ok"] = False
                item["error"] = "親の登録に失敗したので、子は送っていません"
                row.status = "failed"
                db.commit()
                results.append(item)
                continue

        all_ok = True
        for c in kids:
            attrs = _attributes(row, c, db, parent_sku=parent_sku)
            rec = {"sku": c.sku, "kind": "子" if has_variation else "単品",
                   "jan": c.jan, "attributes": attrs}
            if body.dry_run:
                rec["dry_run"] = True
            else:
                r = amazon_api.submit_listing(c.sku, row.product_type, attrs)
                rec.update(r)
                c.status = "submitted" if r.get("ok") else "failed"
                c.error = None if r.get("ok") else json.dumps(
                    r.get("issues") or r.get("error"), ensure_ascii=False)[:1000]
                c.submitted_at = datetime.now(timezone.utc)
                if r.get("ok"):
                    # 使ったJANを台帳で「使用済み」にする
                    j = (db.query(JanCode)
                         .filter(JanCode.code == c.jan).first()) if c.jan else None
                    if j:
                        j.status = "used"
                else:
                    all_ok = False
            item["sent"].append(rec)

        item["ok"] = all_ok
        if not body.dry_run:
            row.status = "submitted" if all_ok else "failed"
            db.commit()
        results.append(item)

    return {"dry_run": body.dry_run, "results": results}


# ---------- SKUの採番 ----------
#
# SKUは「a」＋2桁の連番（a01, a02, …）。2026-09 時点で a04 まで使用済み。
# 次の番号は、商品マスタと出品レコードの両方を見て決める。
# 片方だけ見ると、まだ商品マスタに載っていない出品ぶんと番号がぶつかる。
#
# 画面で好きな番号に直せるようにしてあるので、ここが返すのは「たたき台」。

_SKU_RE = re.compile(r"^([a-z]+)(\d+)")


def _used_sku_numbers(db: Session, prefix: str) -> set:
    """その頭文字で使われている番号を集める。"""
    used = set()

    def take(sku):
        m = _SKU_RE.match((sku or "").strip().lower())
        if m and m.group(1) == prefix:
            used.add(int(m.group(2)))

    for (sku,) in db.query(Product.sku).all():
        take(sku)
    for (sku,) in db.query(AmazonListingChild.sku).all():
        take(sku)
    # 台帳に控えたぶんも見る（出品前に採番だけした状態を拾うため）
    for (sku,) in db.query(JanCode.sku).all():
        take(sku)
    return used


def next_sku(db: Session, prefix: str = "a", width: int = 2, count: int = 1) -> list:
    """空いている番号を若い順に count 個返す。

    抜け番があればそこを埋める、ということはしない。過去のSKUと
    取り違えるより、常に最後の次を使うほうが安全なため。
    """
    used = _used_sku_numbers(db, prefix)
    start = (max(used) + 1) if used else 1
    return [f"{prefix}{str(start + i).zfill(width)}" for i in range(count)]


@router.get("/next-sku")
def peek_next_sku(prefix: str = "a", count: int = 1,
                  db: Session = Depends(get_db)):
    """次に使えるSKUを教える（採番はしない）。

    画面で「次は a05 です」と出し、直したいときは直してもらう。
    """
    used = sorted(_used_sku_numbers(db, prefix))
    return {"prefix": prefix,
            "next": next_sku(db, prefix, count=max(1, min(count, 50))),
            "used_count": len(used),
            "last_used": f"{prefix}{str(used[-1]).zfill(2)}" if used else None}


@router.get("/sku-available")
def sku_available(sku: str, db: Session = Depends(get_db)):
    """そのSKUが使えるか調べる。画面で直したときの確認用。"""
    s = (sku or "").strip()
    if not s:
        return {"ok": False, "reason": "SKUが空です"}
    if db.query(Product).filter(Product.sku == s).first():
        return {"ok": False, "reason": "商品マスタで使われています"}
    if db.query(AmazonListingChild).filter(AmazonListingChild.sku == s).first():
        return {"ok": False, "reason": "ほかの出品で使われています"}
    return {"ok": True}


# ---------- 子SKUの末尾 ----------
#
# Amazonは単品でも親子で作るのが推奨とされているので、親は常に作る。
#   単品          a05（親） / a05_1（子）
#   バリエーション a06（親） / a06_black・a06_s（子）
#
# 末尾は軸の値から作る。日本語のままだとSKUに使えないので、
# よくある色名・サイズ名は英字に直す。当たらなければローマ字か連番。

_COLOR_WORDS = {
    "ブラック": "black", "黒": "black", "ホワイト": "white", "白": "white",
    "グレー": "gray", "灰": "gray", "ネイビー": "navy", "ブルー": "blue",
    "青": "blue", "レッド": "red", "赤": "red", "ピンク": "pink",
    "グリーン": "green", "緑": "green", "イエロー": "yellow", "黄": "yellow",
    "ベージュ": "beige", "ブラウン": "brown", "茶": "brown",
    "パープル": "purple", "紫": "purple", "オレンジ": "orange",
    "シルバー": "silver", "銀": "silver", "ゴールド": "gold", "金": "gold",
    "カーキ": "khaki", "アイボリー": "ivory", "クリア": "clear",
    "透明": "clear", "モカ": "mocha", "グレージュ": "greige",
}

_SIZE_WORDS = {
    "エス": "s", "エム": "m", "エル": "l",
    "小": "s", "中": "m", "大": "l",
    "スモール": "s", "ミディアム": "m", "ラージ": "l",
    "フリー": "free", "フリーサイズ": "free",
}


def sku_suffix(value: str) -> str:
    """軸の値（ブラック・M・2個/ブラック など）をSKUの末尾にする。

    英数字はそのまま小文字に、よくある色名・サイズ名は英字へ。
    「2個/ブラック」のような複合値は区切りごとに直して繋ぐ（2black）。
    どれにも当たらなければ空を返し、呼び出し側で連番にする。
    """
    v = (value or "").strip()
    if not v:
        return ""

    # 区切りがあれば、それぞれ直して繋ぐ
    if re.search(r"[/／・]", v):
        parts = [p.strip() for p in re.split(r"[/／・]", v) if p.strip()]
        joined = "".join(_one_suffix(p) for p in parts)
        if joined:
            return joined[:16]
    return _one_suffix(v)


def _one_suffix(v: str) -> str:
    """区切りのない1語ぶん。"""
    v = (v or "").strip()
    if not v:
        return ""

    # 英数字だけならそのまま使える（M / XL / 120cm など）
    ascii_only = re.sub(r"[^0-9A-Za-z]", "", v)
    if ascii_only and len(ascii_only) == len(re.sub(r"\s", "", v)):
        return ascii_only.lower()[:12]

    for table in (_COLOR_WORDS, _SIZE_WORDS):
        if v in table:
            return table[v]
        # 「ブラック（つや消し）」のような書き方も拾う
        for k, en in table.items():
            if v.startswith(k):
                return en

    # 数字を含むなら数字を活かす（120cm → 120）
    num = re.sub(r"[^0-9]", "", v)
    if num:
        return num[:6]
    return ""


@router.post("/{listing_id:int}/title")
def make_title(listing_id: int, push: str = "", db: Session = Depends(get_db)):
    """商品タイトルの下書きを作る。作るだけで、保存はしない。

    命名ルール（ブランド名／メインキーワード／関連ワード／サイズ・数量・色）
    に沿って65字程度にまとめる。ここから手で直してもらう前提。
    """
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")

    src = None
    for c in sync.candidates(_sheet(db), all_status=True):
        if c["research_id"] == row.research_id:
            src = c
            break
    if src is None:
        raise HTTPException(404, "元のリサーチがシートにありません")

    # 子の軸の値は、この画面で直したぶんを使う
    kids = (db.query(AmazonListingChild)
            .filter(AmazonListingChild.listing_id == row.id)
            .order_by(AmazonListingChild.sort_order).all())
    if kids:
        src = dict(src)
        src["children"] = [{"axis_label_value": (c.axis1 or "")} for c in kids]

    brand = (row.brand or "").strip()
    if not brand:
        st = db.query(AmazonResearchSettings).first()
        brand = (st.brand_name or "").strip() if st else ""

    # 競合のブランド名を外すため、取り込んである商品仕様も渡す
    ids = [c.get("row_id") for c in (src.get("rows") or []) if c.get("row_id")]
    specs = [v["spec"] for v in _notes_for(db, ids).values() if v.get("spec")]

    title = sync.build_title(src, brand=brand, push=push or "", specs=specs)
    if not title:
        return {"ok": False,
                "error": "元になる語がありません。リサーチシートでサジェストを取得するか、"
                         "競合の商品名を入れてください"}
    return {"ok": True, "title": title, "length": len(title)}


# ---------- 出品原稿はリサーチシートを正とする ----------
#
# 商品タイトル・検索キーワード・要点の5行・子（色）は、リサーチシートの
# 「🏷 出品原稿をつくる」で作るものと同じ中身。二重に持つと必ずずれるので、
# シート側を正とし、この画面からの編集もシートへ書き戻す。
#
# amazon_listings の同名の列は、一覧の絞り込みや送信時の取り回しのために
# 写しとして持っているだけ。読むときは常にシートを見る。

# シート側のキー名（HTMLの都合で決まっていて変えられない）
_DRAFT_KEYS = {
    "title": "titleParent",
    "keywords": "kwDraft",
    "description": "listingBullets",
    "must_kw": "kwSpec",
    "diff_points": "diffPoints",
}


def _write_sheet_draft(db: Session, research_id: str, data: dict,
                       children: list = None) -> bool:
    """出品原稿をシートへ書き戻す。

    シートは1枚のJSONなので、丸ごと読んで、その1リサーチの
    決まった項目だけ差し替えて書く。ほかの人の編集を消さないよう、
    書く直前に読み直す。
    """
    row = (db.query(AmazonResearchSheet)
           .filter(AmazonResearchSheet.workspace == "default").first())
    if row is None or not row.data:
        return False
    try:
        sheet = json.loads(row.data)
    except (ValueError, TypeError):
        return False

    target = None
    for r in (sheet.get("researches") or []):
        if isinstance(r, dict) and r.get("id") == research_id:
            target = r
            break
    if target is None:
        return False

    changed = False
    for field, key in _DRAFT_KEYS.items():
        if field in data:
            v = data[field]
            v = "" if v is None else str(v)
            if (target.get(key) or "") != v:
                target[key] = v
                changed = True

    if children is not None:
        kids = target.get("titleChildren")
        kids = kids if isinstance(kids, list) else []
        out = []
        for i, c in enumerate(children):
            old = kids[i] if i < len(kids) else {}
            out.append({
                "name": (c.get("axis1") or "").strip(),
                "title": c.get("title") or "",
                # 色を外した土台は画面側が持っているので、あれば引き継ぐ
                "titleBase": old.get("titleBase"),
            })
        if out != kids:
            target["titleChildren"] = out
            changed = True

    if not changed:
        return False
    raw = json.dumps(sheet, ensure_ascii=False)
    row.data = raw
    row.size_bytes = len(raw.encode("utf-8"))
    return True


def _read_sheet_draft(src: dict) -> dict:
    """シートの出品原稿を、この画面が使う形にして返す。"""
    if not src:
        return {}
    return {
        "title": src.get("title") or "",
        "keywords": src.get("keywords") or "",
        "bullets": src.get("bullets") or [],
        "description": src.get("description") or "",
        "must_kw": src.get("must_kw") or "",
        "diff_points": src.get("diff_points") or "",
    }


def _pull_children(db: Session, row: AmazonListing, src: dict) -> None:
    """シートの子（色・子タイトル）をこちらへ取り込む。

    出品原稿はシートが正なので、開くたびに追従させる。
    ただしSKU・JAN・送信の結果はこちら側にしかないので、並び順で
    突き合わせて残す（JANを振り直すと別商品として扱われてしまう）。

    シートの子が減ったとき、JANを発番済みのものは消さない。
    番号を宙に浮かせないため。
    """
    if not src:
        return
    kids = (db.query(AmazonListingChild)
            .filter(AmazonListingChild.listing_id == row.id)
            .order_by(AmazonListingChild.sort_order).all())
    sheet_kids = src.get("children") or []

    if not sheet_kids:
        # 単品。器が1つも無ければ作る。中身はシートの親タイトル
        if not kids:
            db.add(AmazonListingChild(listing_id=row.id, sort_order=0,
                                      title=src.get("title") or ""))
        elif len(kids) == 1 and not (kids[0].title or "").strip():
            kids[0].title = src.get("title") or ""
        return

    for i, sk in enumerate(sheet_kids):
        if i < len(kids):
            c = kids[i]
        else:
            c = AmazonListingChild(listing_id=row.id)
            db.add(c)
        c.sort_order = i
        c.title = sk.get("title") or ""
        c.axis1 = sk.get("axis1") or ""

    # シートから減ったぶん。まだJANを振っていなければ落とす
    for c in kids[len(sheet_kids):]:
        if not c.jan:
            db.delete(c)


# ---------- 商品説明のプロンプトと検査 ----------

@router.post("/{listing_id:int}/desc-prompt")
def desc_prompt(listing_id: int, short: bool = False,
                db: Session = Depends(get_db)):
    """商品説明（5行）を作らせるプロンプトを組み立てる。

    シートの「④ 商品説明プロンプトをコピー」と同じもの。
    ChatGPTなどに貼り、返ってきた5行を「商品の要点」に貼ってもらう。
    """
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")

    src = None
    for c in sync.candidates(_sheet(db), all_status=True):
        if c["research_id"] == row.research_id:
            src = c
            break
    if src is None:
        raise HTTPException(404, "元のリサーチがシートにありません")

    # 子のタイトルは、この画面で直したぶんを使う
    kids = (db.query(AmazonListingChild)
            .filter(AmazonListingChild.listing_id == row.id)
            .order_by(AmazonListingChild.sort_order).all())
    if kids:
        src = dict(src)
        src["children"] = [{"title": c.title or ""} for c in kids]

    ids = [c.get("row_id") for c in (src.get("rows") or []) if c.get("row_id")]
    text = listing_prompt.build(
        src, must_kw=src.get("must_kw") or "",
        diff=src.get("diff_points") or "",
        notes=_notes_for(db, ids), short=short)
    if not text:
        return {"ok": False, "error": "まず商品タイトルを入れてください"}
    return {"ok": True, "prompt": text, "length": len(text)}


class LinesIn(BaseModel):
    text: str


@router.post("/{listing_id:int}/check-lines")
def check_lines(listing_id: int, body: LinesIn,
                db: Session = Depends(get_db)):
    """貼ってもらった5行を検査する。シートの「✅ チェックする」と同じ観点。"""
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")
    must = ""
    for c in sync.candidates(_sheet(db), all_status=True):
        if c["research_id"] == row.research_id:
            must = c.get("must_kw") or ""
            break
    return listing_prompt.check_lines(body.text, must_kw=must)


@router.get("/common-attrs")
def get_common_attrs(db: Session = Depends(get_db)):
    """どのカテゴリでもだいたい聞かれる項目の既定値。"""
    return {"fields": COMMON_FIELDS, "values": common_attrs(db)}


class CommonAttrsIn(BaseModel):
    values: dict


@router.put("/common-attrs")
def put_common_attrs(body: CommonAttrsIn, db: Session = Depends(get_db)):
    """既定値を保存する。全商品に効く。"""
    st = db.query(AmazonResearchSettings).first()
    if st is None:
        st = AmazonResearchSettings(id=1)
        db.add(st)
    keep = {k: v for k, v in (body.values or {}).items()
            if k in _COMMON_DEFAULTS}
    st.common_attrs = json.dumps(keep, ensure_ascii=False)
    db.commit()
    return {"values": common_attrs(db)}
