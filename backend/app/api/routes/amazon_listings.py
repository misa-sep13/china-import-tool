"""Amazonへの商品登録。

競合リサーチシートを元に、1リサーチ＝1商品として出品内容をまとめる。
これまでの登録画面は楽天用のドラフト（product_drafts）を流用していて、
シートの商品タイトル・検索キーワード・三辺・重量が一切渡っていなかった。
ここではシートを直接の元にしている。
"""
import base64
import io
import json
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.amazon_research import (
    AmazonResearchSheet, AmazonResearchSettings, JanCode,
)
from app.models.amazon_research_page import AmazonResearchPage
from app.models.amazon_product_type_memo import AmazonProductTypeMemo
from app.models.product import Product
from app.models.amazon_listing import (
    AmazonListing, AmazonListingChild, AmazonListingImage,
)
from app.services import amazon_listing_sync as sync
from app.services import listing_prompt
from app.services import amazon_api

router = APIRouter(prefix="/amazon-listings", tags=["amazon-listings"])

MAX_IMAGE_BYTES = 8 * 1024 * 1024      # Amazonが取りに来られる大きさの目安
# 1つのSKUに付けられる画像の数。共通と色ごとに別々に数える。
# これを超えて入れてもAmazonへは送られず、消す手間が増えるだけ
# 共通に入れられる枚数。Amazonの枠は メイン1＋サブ8＝9枚 で、
# 色ごとにメインとバリエーションを1枚ずつ使うので、残りは7枚
MAX_IMAGES_PER_TARGET = 7
# Amazonが1SKUに持てる画像の枠。メイン1枚＋サブ8枚。
# 共通をたくさん入れても、ここを超えたぶんは送られない
AMAZON_IMAGE_SLOTS = 9


# ---------- 入れ物 ----------

class ListingIn(BaseModel):
    title: Optional[str] = None
    keywords: Optional[str] = None
    bullets: Optional[list] = None
    highlight: Optional[str] = None
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
    fulfillment: Optional[str] = None
    variation_theme: Optional[str] = None
    axis1_label: Optional[str] = None
    axis2_label: Optional[str] = None
    master_note: Optional[str] = None   # 商品マスタの備考に持っていく
    delivery_note: Optional[str] = None  # 納品時の備考に持っていく
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
            "role": i.role,
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
        "highlight": row.highlight or "",
        "description": row.description, "brand": row.brand, "price": row.price,
        "len_a": row.len_a, "len_b": row.len_b, "len_c": row.len_c,
        "weight": row.weight,
        "rival_asin": row.rival_asin, "product_type": row.product_type,
        "attrs": _loads(row.attrs, {}),
        "parent_sku": row.parent_sku,
        "fulfillment": _fulfillment_of(db, row),
        "variation_theme": row.variation_theme,
        "axis1_label": row.axis1_label, "axis2_label": row.axis2_label,
        "monthly_sales": row.monthly_sales, "review_count": row.review_count,
        "review_rate": row.review_rate, "profit_rate": row.profit_rate,
        "rival_image": row.rival_image,
        "master_note": row.master_note or "",
        "delivery_note": row.delivery_note or "",
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
        # 競合のAmazonページと1688。いつでも開けるように常に返す
        d["links"] = _links_of(src)
    return d


def _fulfillment_of(db: Session, row: AmazonListing) -> str:
    """FBAか自己発送か。空ならシートの「配送」を見に行く。

    列を後から足したので、それ以前に作った登録は空のままになっている。
    空を自己発送と決めつけると、FBAの商品がFBMで出てしまう。
    """
    v = (row.fulfillment or "").strip().lower()
    if v:
        return v
    # シートの「配送」に合わせる。判定は登録時（put("fulfillment", ...)）と
    # 同じにする。ここだけ「FBAと書いてなければ自己発送」になっていたため、
    # 画面でFBAと出ているのにFBMで出品されていた
    for c in sync.candidates(_sheet(db), all_status=True):
        if c["research_id"] == row.research_id:
            return "merchant" if c.get("fulfill") == "自己発送" else "fba"
    return "fba"


def _links_of(src: dict) -> list:
    """自分で確かめたいときのために、競合のAmazonページと1688を並べる。

    素材や寸法が商品仕様に書かれていないことは多く、
    そのときは元のページを見るしかない。
    """
    out = []
    if not src:
        return out
    for r in (src.get("rows") or []):
        asin = (r.get("asin") or "").strip().upper()
        if asin:
            out.append({"kind": "競合", "asin": asin,
                        "label": (r.get("competitor") or asin)[:40],
                        "url": f"https://www.amazon.co.jp/dp/{asin}"})
    for u in (src.get("urls_1688") or []):
        if u:
            out.append({"kind": "1688", "label": "仕入れ元のページ", "url": u})
    return out


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

    # 一覧に出すのは自社の情報（SKU・商品名・ASIN）。
    # 競合の数字は判断材料として残すが、主役ではない。
    # 子SKUは件数ぶん問い合わせると重いので、まとめて1回で引く
    kids_by_listing: dict = {}
    if saved:
        for ch in (db.query(AmazonListingChild)
                   .filter(AmazonListingChild.listing_id.in_(
                       [r.id for r in saved.values()]))
                   .order_by(AmazonListingChild.sort_order,
                             AmazonListingChild.id).all()):
            kids_by_listing.setdefault(ch.listing_id, []).append(ch)

    def own(row):
        """その登録の自社情報。まだ始めていなければ空。"""
        if not row:
            return {"parent_sku": "", "own_title": "", "skus": [], "asins": []}
        kids = kids_by_listing.get(row.id, [])
        return {
            "parent_sku": (row.parent_sku or "").strip(),
            "own_title": (row.title or "").strip(),
            "skus": [k.sku for k in kids if (k.sku or "").strip()],
            "asins": [k.asin for k in kids if (k.asin or "").strip()],
        }

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
            # 仕入元のページ。一覧からそのまま開けるようにする
            "urls_1688": c.get("urls_1688") or (
                [c["main_url"]] if c.get("main_url") else []),
            **own(row),
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
            "urls_1688": [],
            **own(r),
        })
    return {"rows": rows}


@router.get("/by-research/{research_id}")
def find_by_research(research_id: str, db: Session = Depends(get_db)):
    """このリサーチの登録レコードがすでにあるかだけを返す。

    ⑦を開いたとき、すでに始めてあるならボタンを押さずに
    中身を出したい。sync は無ければ作ってしまうので、
    開いただけでレコードができないよう、読むだけの口を別に用意する。
    一覧（GET ""）でも分かるが、あちらはシート全体を読むので重い。
    """
    row = (db.query(AmazonListing)
           .filter(AmazonListing.research_id == research_id).first())
    return {"listing_id": row.id if row else None}


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
    put("highlight", src.get("highlight"))
    put("price", src["price"])
    put("len_a", src["len_a"])
    put("len_b", src["len_b"])
    put("len_c", src["len_c"])
    put("weight", src["weight"])
    put("rival_asin", src["rival_asin"])
    # シートの「配送」から。うちはほぼFBAで出すので、はっきり「自己発送」と
    # 書かれているときだけ自己発送にする。空のまま自己発送で出ると、
    # 気づかないまま自分で送ることになる
    put("fulfillment",
        "merchant" if src.get("fulfill") == "自己発送" else "fba")

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
            # JANの付け替え。GS1に登録済みの番号を使いたいことがある。
            # 台帳にある番号だけ許し、外れた番号は取り消しにする
            new_jan = (ch.get("jan") or "").strip()
            if new_jan and new_jan != (c.jan or ""):
                if _old_account_jan(new_jan, db):
                    raise HTTPException(
                        400, f"{new_jan} は前のAmazonアカウントで使った番号です。"
                             "GS1に別商品として登録されているので使えません")
                j = db.query(JanCode).filter(JanCode.code == new_jan).first()
                if j is None:
                    raise HTTPException(400, f"{new_jan} は台帳にありません")
                # 台帳の sku は「発番したときの名前」。親SKUや色の名前を
                # 付け替えると、こちらの子のSKUだけが変わって台帳は
                # 古いまま残り、同じ番号なのに「すでに使われています」と
                # 止まってしまう（a16_beige → a013_offwhite で実際に起きた）。
                # 本当に使われているかは、ほかの子が持っているかで見る。
                if j.sku and j.sku != c.sku:
                    holder = (db.query(AmazonListingChild)
                              .filter(AmazonListingChild.jan == new_jan,
                                      AmazonListingChild.id != c.id)
                              .first())
                    if holder is not None:
                        raise HTTPException(
                            400, f"{new_jan} はすでに "
                                 f"{holder.sku or j.sku} で使われています")
                old_jan = c.jan
                c.jan = new_jan
                j.sku = c.sku
                j.status = "used"
                if old_jan:
                    o = (db.query(JanCode)
                         .filter(JanCode.code == old_jan).first())
                    if o is not None:
                        # 一度Amazonへ送った番号は再利用しない
                        o.status = "void"
                        o.sku = None
                        o.note = ((o.note + " ／ ") if o.note else "")                             + f"{c.sku} から外した（別の番号に付け替え）"
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
                      "must_kw", "diff_points", "highlight")}
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

# Amazonが画像を取りに来るとき、大きいままだと配信が間に合わず
# 「Media Download Timed Out from Server」で弾かれる。
# Amazonの推奨は長辺1600px。それ以上は意味が無いので縮めて持つ。
AMAZON_IMAGE_PX = 1600


def _shrink_for_amazon(blob: bytes, mime: str) -> tuple[bytes, str]:
    """長辺1600pxまで縮めてJPEGにする。縮められなければ元のまま返す。

    元の大きさのまま置くと1枚で数MBになり、Amazonの取得が
    タイムアウトする（実際に出品が弾かれた）。
    """
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(blob))
        im.load()
        # すでに基準内のJPEGは触らない。毎回かけ直すと、そのたびに
        # 圧縮し直して画質が落ちていく（起動のたびに縮める処理があるため）
        if (max(im.size) <= AMAZON_IMAGE_PX
                and (mime or "").lower() in ("image/jpeg", "image/jpg")):
            return blob, mime
        if im.mode in ("RGBA", "LA", "P"):
            # 透過は白で埋める。Amazonは背景が透明な画像を好まない
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        if max(im.size) > AMAZON_IMAGE_PX:
            im.thumbnail((AMAZON_IMAGE_PX, AMAZON_IMAGE_PX), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88, optimize=True)
        out = buf.getvalue()
        # 縮めたのに大きくなるなら、元のほうがよい
        return (out, "image/jpeg") if out and len(out) < len(blob) else (blob, mime)
    except Exception:
        return blob, mime


@router.post("/{listing_id:int}/images")
async def add_image(listing_id: int, child_id: Optional[int] = None,
                    role: Optional[str] = None,
                    file: UploadFile = File(...),
                    db: Session = Depends(get_db)):
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")

    role = (role or "").strip() or None
    if role not in (None, "main", "variation"):
        raise HTTPException(400, "画像の役割の指定が違います")
    if role and child_id is None:
        raise HTTPException(400, "メイン・バリエーションは色ごとに入れてください")

    if role:
        # メインとバリエーションは色ごとに1枚ずつ。入れ替えたいときは
        # 消してから入れ直すより、古いほうを落として差し替えるほうが早い
        old = (db.query(AmazonListingImage)
               .filter(AmazonListingImage.listing_id == listing_id,
                       AmazonListingImage.child_id == child_id,
                       AmazonListingImage.role == role).all())
        for o in old:
            db.delete(o)
    else:
        have = (db.query(AmazonListingImage)
                .filter(AmazonListingImage.listing_id == listing_id,
                        AmazonListingImage.child_id == child_id,
                        AmazonListingImage.role.is_(None)).count())
        if have >= MAX_IMAGES_PER_TARGET:
            where = "この色" if child_id else "共通"
            raise HTTPException(
                400, f"{where}の画像は{MAX_IMAGES_PER_TARGET}枚までです"
                     f"（いま{have}枚）。要らないものを消してから入れてください")

    blob = await file.read()
    if not blob:
        raise HTTPException(400, "中身が空です")
    if len(blob) > MAX_IMAGE_BYTES:
        raise HTTPException(400,
                            f"画像が大きすぎます（{len(blob)//1024//1024}MB）。8MBまでにしてください")
    mime = (file.content_type or "").lower()
    if not mime.startswith("image/"):
        raise HTTPException(400, "画像ファイルを選んでください")

    blob, mime = _shrink_for_amazon(blob, mime)

    last = (db.query(AmazonListingImage)
            .filter(AmazonListingImage.listing_id == listing_id)
            .order_by(AmazonListingImage.sort_order.desc()).first())
    img = AmazonListingImage(
        listing_id=listing_id, child_id=child_id,
        file_name=file.filename or "image", mime=mime, size=len(blob),
        data=base64.b64encode(blob).decode(), role=role,
        sort_order=((last.sort_order or 0) + 1) if last else 0,
        public_token=secrets.token_urlsafe(24),
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return _image_out(img)


# ---------- Amazonの登録Excelから商品マスタを更新 ----------
#
# スプレッドシート（Amazonの在庫ファイル）で直接登録した商品は、ツールの
# 出品フローを通らないので商品マスタに行ができない。発注も在庫も
# マスタを見るので、入れておかないとその商品だけ管理から外れる。
#
# 古い名前が残っていることがあるため、既にある行は上書きする。
# 仕入URL・原価・入数など、こちらでしか持っていない情報は触らない。

_TPL_SHEET = "テンプレート"
_TPL_LABEL_ROW = 4
_TPL_DATA_ROW = 7


def _tpl_col(ws, label: str):
    for c in range(1, ws.max_column + 1):
        if ws.cell(_TPL_LABEL_ROW, c).value == label:
            return c
    return None


@router.post("/master/import-excel")
async def master_import_excel(files: list[UploadFile] = File(...),
                              db: Session = Depends(get_db)):
    """Amazonの登録Excel（.xlsm）を読んで、商品マスタを作る・直す。

    1行＝1SKU。親の行は売り物ではないので飛ばす。
    """
    from openpyxl import load_workbook

    made, fixed, skipped = [], [], []
    for up in files:
        try:
            wb = load_workbook(io.BytesIO(await up.read()), data_only=True)
        except Exception:
            skipped.append(f"{up.filename}：Excelとして読めません")
            continue
        if _TPL_SHEET not in wb.sheetnames:
            skipped.append(f"{up.filename}：「テンプレート」のシートがありません")
            continue
        ws = wb[_TPL_SHEET]
        c_sku = _tpl_col(ws, "SKU")
        c_name = _tpl_col(ws, "商品名")
        c_lvl = _tpl_col(ws, "親子レベル")
        c_color = _tpl_col(ws, "色")
        c_price = _tpl_col(ws, "商品の販売価格 JPY (Amazonで販売, JP)")
        if not c_sku:
            skipped.append(f"{up.filename}：SKUの列が見つかりません")
            continue

        max_no = db.query(sa_func.max(Product.no)).scalar() or 0
        for r in range(_TPL_DATA_ROW, ws.max_row + 1):
            sku = str(ws.cell(r, c_sku).value or "").strip()
            if not sku or sku == "ABC123":
                continue
            if c_lvl and str(ws.cell(r, c_lvl).value or "").strip() == "親":
                continue
            name = str(ws.cell(r, c_name).value or "").strip() if c_name else ""
            color = str(ws.cell(r, c_color).value or "").strip() if c_color else ""
            price = ws.cell(r, c_price).value if c_price else None

            p = db.query(Product).filter(Product.sku == sku).first()
            new = p is None
            if new:
                max_no += 1
                p = Product(sku=sku, no=max_no, supplier="タオタロウ")
                db.add(p)
            # 名前・色・売価はExcelが新しい。古い名前が残るので上書きする
            if name:
                p.name = name[:500]
            if color:
                p.color = color
            try:
                if price not in (None, ""):
                    p.selling_price = float(price)
            except (TypeError, ValueError):
                pass
            (made if new else fixed).append(sku)
        db.flush()
    db.commit()
    return {"作った": made, "直した": fixed, "読めなかった": skipped}


@router.post("/images/shrink")
def shrink_images(listing_id: Optional[int] = None, limit: int = 200,
                  db: Session = Depends(get_db)):
    """すでに入れてある画像を、長辺1600pxまで縮める。

    縮める前に入れた画像は大きいままで、Amazonの取得が
    タイムアウトする。入れ直さずに済むよう、ここで縮める。
    listing_id を指定すればその商品だけ。
    """
    q = db.query(AmazonListingImage)
    if listing_id:
        q = q.filter(AmazonListingImage.listing_id == listing_id)
    done = saved = 0
    for img in q.order_by(AmazonListingImage.id).limit(max(1, limit)).all():
        if not img.data:
            continue
        try:
            raw = base64.b64decode(img.data)
        except Exception:
            continue
        out, mime = _shrink_for_amazon(raw, img.mime or "image/jpeg")
        if len(out) >= len(raw):
            continue                       # これ以上小さくならない
        img.data = base64.b64encode(out).decode()
        img.mime = mime
        img.size = len(out)
        done += 1
        saved += len(raw) - len(out)
    db.commit()
    return {"縮めた枚数": done, "減った容量MB": round(saved / 1024 / 1024, 2)}


# 登録が済んだあとに手元へ残す大きさ。どの写真を使ったか分かればよい
ARCHIVE_IMAGE_PX = 320


class ArchiveImagesIn(BaseModel):
    listing_id: Optional[int] = None
    research_id: Optional[str] = None


@router.post("/archive-images")
def archive_images(body: ArchiveImagesIn, db: Session = Depends(get_db)):
    """登録が済んだ出品の画像を、見分けがつく小ささまで落とす。

    画像はDBにbase64で預かっているので、1商品で数MBになる。
    Amazonへ送り終わっていれば、手元には「どの写真を使ったか」が
    分かるだけの大きさがあればよい。
    消さずに縮めるのは、作り直せない写真があるため
    （消すとAmazonが取りに来たときに404になることもある）。
    """
    q = db.query(AmazonListing)
    if body.listing_id:
        q = q.filter(AmazonListing.id == body.listing_id)
    elif (body.research_id or "").strip():
        q = q.filter(AmazonListing.research_id == body.research_id.strip())
    else:
        raise HTTPException(400, "どの出品か分かりません")
    rows = q.all()
    if not rows:
        return {"枚数": 0, "減った容量MB": 0, "note": "出品がありません"}

    done = saved = 0
    for row in rows:
        imgs = (db.query(AmazonListingImage)
                .filter(AmazonListingImage.listing_id == row.id).all())
        for img in imgs:
            if not img.data:
                continue
            try:
                raw = base64.b64decode(img.data)
            except Exception:
                continue
            out = _to_thumb(raw)
            if not out or len(out) >= len(raw):
                continue
            img.data = base64.b64encode(out).decode()
            img.mime = "image/jpeg"
            img.size = len(out)
            done += 1
            saved += len(raw) - len(out)
    db.commit()
    return {"枚数": done, "減った容量MB": round(saved / 1024 / 1024, 2)}


def _to_thumb(blob: bytes) -> bytes:
    """長辺320pxのJPEGにする。できなければ空を返す（元のまま残す）。"""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(blob))
        im.load()
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        im.thumbnail((ARCHIVE_IMAGE_PX, ARCHIVE_IMAGE_PX), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80, optimize=True)
        return buf.getvalue()
    except Exception:
        return b""


@router.delete("/{listing_id:int}/children/{child_id:int}")
def delete_child(listing_id: int, child_id: int,
                 db: Session = Depends(get_db)):
    """出品から子（色）を1つ消す。

    シートから色が消えても、JANを振った子は残す作りにしている
    （番号を宙に浮かせないため）。色の名前を付け替えたときに、
    古い色がここに取り残され、画面からは消せなくなっていた
    （SKUとJANの欄を空にしても、JANは外せないので残り続ける）。

    使ったJANは台帳で取り消しにする。一度どこかへ出した番号を
    別の商品で使い回すと、同じ商品として扱われてしまうため。
    """
    c = db.get(AmazonListingChild, child_id)
    if not c or c.listing_id != listing_id:
        raise HTTPException(404, "ありません")
    if (c.status or "draft") not in ("draft", "failed"):
        raise HTTPException(
            400, "Amazonへ送ったSKUはここからは消せません。"
                 "先にAmazonの在庫管理で終了させてください")
    if c.jan:
        j = db.query(JanCode).filter(JanCode.code == c.jan).first()
        if j is not None:
            j.status = "void"
            j.sku = None
            note = f"{c.sku or '（SKUなし）'} を出品から消したので取り消し"
            j.note = ((j.note + " ／ ") if j.note else "") + note
    db.delete(c)
    db.commit()
    return {"deleted": True}


@router.delete("/images/{image_id:int}")
def delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.get(AmazonListingImage, image_id)
    if not img:
        raise HTTPException(404, "ありません")
    db.delete(img)
    db.commit()
    return {"deleted": True}


class ImageOrderIn(BaseModel):
    ids: list[int]


@router.put("/{listing_id:int}/images/order")
def reorder_images(listing_id: int, body: ImageOrderIn,
                   db: Session = Depends(get_db)):
    """画像の並びをまとめて保存する。渡された順にそのまま並べる。

    1枚ずつ動かすと、途中で止まったときに並びが崩れる。
    画面でドラッグして離した結果を、1回で受け取る。
    """
    imgs = {i.id: i for i in db.query(AmazonListingImage)
            .filter(AmazonListingImage.listing_id == listing_id).all()}
    n = 0
    for order, iid in enumerate(body.ids):
        img = imgs.get(iid)
        if img is None:
            continue
        if img.sort_order != order:
            img.sort_order = order
            n += 1
    db.commit()
    return {"updated": n}


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
    from app.api.routes.amazon_research import (_get_settings, _make_jan,
                                                next_jan_seq)
    st = _get_settings(db)
    prefix = (st.gs1_prefix or "").strip()
    if not prefix.isdigit() or len(prefix) not in (7, 9):
        raise HTTPException(
            400, "先にGS1事業者コード（7桁か9桁）を設定してください")
    seq = next_jan_seq(db)
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

    # 親SKUを直したら、子の頭も付いてくるようにする。
    # 直さないと a06_black と a14_gray のように、1つの商品の中で
    # 頭がばらばらになる（JANはSKUごとなので、結びつきはずれない）
    for c in kids:
        s = (c.sku or "").strip()
        if not s or "_" not in s:
            continue
        old_head, suf = s.split("_", 1)
        if old_head != head:
            c.sku = f"{head}_{suf}"

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
# 出しておきたいが、送信までは止めない案内。
#   ・共通の画像が多い … 溢れたぶんを自動で落として送れる
#   ・SKUと色が食い違う … SKUの付け方から色を推し量っているだけで、
#     当たらないこともある。推測が外れたせいで出品できないのは行き過ぎ
# どちらも止めていたため、気づかないうちに1件も送られていなかった
#   ・GS1に未登録 … 届け出たかどうかはこちらの台帳の記録でしかなく、
#     実際に登録してあっても印が付いていないことがある。本当に未登録なら
#     Amazonが弾いてくれるので、こちらで止めずに送ってみる
_NOT_BLOCKING = ("画像がありません", "共通の画像が", "食い違っています",
                 "GS1に未登録")


def _old_account_jan(code: str, db: Session) -> bool:
    """前のAmazonアカウントで使い切った番号かどうか。

    GS1の一覧で 1〜87 が使用済みで、多くは「GTIN使用中」のまま
    過去のASINに紐づいている。新しい商品に使うと弾かれるか、
    別商品として扱われる（実際、ガラスクロス 4573603980865＝086 が
    ThreeSky Plus のまま登録されていた）。
    発番側は JAN_SEQ_FLOOR で避けているが、手で入れた番号や
    外から取り込んだ番号はここで止める。
    """
    from app.api.routes.amazon_research import JAN_SEQ_FLOOR, _get_settings
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 13:
        return False
    prefix = (_get_settings(db).gs1_prefix or "").strip()
    if not prefix or not code.startswith(prefix):
        return False
    try:
        seq = int(code[len(prefix):12])
    except ValueError:
        return False
    return 0 < seq <= JAN_SEQ_FLOOR


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
    if not _brand_for(db, row).strip():
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

    imgs = _image_rows(db, row.id)
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
        else:
            # 前のAmazonアカウントで使った番号は、GS1に別商品として
            # 登録されていて過去のASINに紐づいている。新しい商品に使うと
            # 弾かれるか、別商品として扱われる。絶対に出してはいけない
            if _old_account_jan(c.jan, db):
                p.append(f"[{who}] JAN {c.jan} は前のAmazonアカウントで"
                         "使った番号です。GS1に別商品として登録されている"
                         "ので、この番号では出せません。発番し直してください")
            # GS1に届け出ていないJANは、Amazonが受け付けない
            j = db.query(JanCode).filter(JanCode.code == c.jan).first()
            if j is not None and j.gs1_registered_at is None:
                p.append(f"[{who}] JAN {c.jan} がGS1に未登録です"
                         "（このツールの記録上）。実際に届け出てあれば"
                         "そのまま出品できます")
    # バリエーションは常に色で登録する（色でないと選択肢ごとの画像が出ない）
    if len(kids) > 1:
        shared = any(i.child_id is None for i in imgs)
        # 同じ色が2つあると、Amazonはバリエーションごと受け付けない
        seen_axis = {}
        for c in kids:
            k = "".join((c.axis1 or "").split()).lower()
            if k:
                seen_axis.setdefault(k, []).append(c.sku or c.title or "")
        for k, who in seen_axis.items():
            if len(who) > 1:
                p.append(f"色「{k}」が{len(who)}件あります"
                         f"（{' / '.join(x for x in who if x)}）。"
                         "色はSKUごとに別の値にしてください")
        # SKUの末尾と色が食い違っていないか。並び替えで入れ替わると、
        # a06_black に白のJANが付いたまま出てしまう
        for c in kids:
            suf = (c.sku or "").split("_", 1)[-1] if "_" in (c.sku or "") else ""
            if suf and (c.axis1 or "").strip() and sku_suffix(c.axis1)                     and not suf.startswith(sku_suffix(c.axis1)):
                p.append(f"[{c.sku}] SKUと色（{c.axis1}）が食い違っています。"
                         "色の並べ替えでずれた可能性があります")
        n_shared = len([i for i in imgs if i.child_id is None])
        if n_shared > AMAZON_IMAGE_SLOTS - 2:
            p.append(f"共通の画像が{n_shared}枚あります。"
                     f"メインとバリエーションを入れると{AMAZON_IMAGE_SLOTS}枚に"
                     f"収まらないので、古いものから送られません"
                     f"（共通は{AMAZON_IMAGE_SLOTS - 2}枚までが目安です）")
        for c in kids:
            who = c.axis1 or c.title[:16] if (c.axis1 or c.title) else c.sku
            if not (c.axis1 or "").strip():
                p.append(f"[{c.title[:16] if c.title else c.sku}] 色が空です")
            # メイン画像は色ごとに要る。共通しか無いと、どの色も
            # 同じ写真になってしまう
            own = [i for i in imgs if i.child_id == c.id]
            if imgs and not any(i.role == "main" for i in own) and not own                     and not shared:
                p.append(f"[{who}] 画像がありません（共通の画像もありません）")
            elif imgs and shared and not any(i.role == "main" for i in own)                     and not own:
                p.append(f"[{who}] メイン画像がありません。"
                         "共通の画像で代用されるので、色ごとの写真を入れてください")
    return p


# ---------- Amazonへ送る ----------

# 自社ブランドのAmazonブランド登録が通ったので、これからは必ず自社ブランドで
# 出す。ノーブランド品では登録しない。
#
# 商品ごとの「ブランド名」は空が既定で、空なら設定のブランド名を使う。
# 設定も空なら、ここの既定に落とす（未設定のまま無ブランドで出ないように）。
DEFAULT_BRAND = "Aqualiora"


def _brand_for(db: Session, row: AmazonListing) -> str:
    st = db.query(AmazonResearchSettings).first()
    own = (st.brand_name if st else "") or ""
    return ((row.brand or "").strip() or own.strip() or DEFAULT_BRAND)


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
    {"name": "is_exclusive_product", "label": "Amazon.co.jp限定商品ですか？",
     "type": "bool", "default": "false"},
    {"name": "distribution_designation", "label": "輸入種別",
     "type": "select", "default": "default",
     "choices": [["default", "正規品"], ["jp_parallel_import", "並行輸入"]]},
    {"name": "supplier_declared_dg_hz_regulation", "label": "危険物の該当性",
     "type": "select", "default": "not_applicable",
     "choices": [["not_applicable", "該当なし"],
                 ["ghs", "GHS（化学品）"],
                 ["storage", "保管の規制あり"],
                 ["transportation", "輸送の規制あり"]]},
]

_COMMON_DEFAULTS = {f["name"]: f["default"] for f in COMMON_FIELDS}
_COMMON_LABELS = {f["name"]: dict(f.get("choices") or [])
                  for f in COMMON_FIELDS}


def _common_label(name: str, value):
    """共通項目の値を、人が読める形にする。"""
    if value is True:
        return "はい"
    if value is False:
        return "いいえ"
    return _COMMON_LABELS.get(name, {}).get(value, value)
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


# ---------- 項目の性質を分ける ----------
#
# Amazonに聞かれる項目は3種類ある。どれに当たるかはこちらで判断し、
# 画面には「毎回入れるもの」だけを出す。
#
#   auto … ツールが決められる（SKU・ブランド名から入る）
#   type … そのカテゴリでは毎回同じ（1度入れれば覚える）
#   item … 商品ごとに違う（毎回入れてもらう）
#
# 判断を間違えることもあるので、画面から type と item を入れ替えられる。

# ツールが決められるもの。値の作り方も一緒に持つ
_AUTO_ATTRS = {
    # 型番は持っていないので、商品ごとに一意なJANを入れる。
    # SKUを入れていたが、JANのほうが商品を指す番号として妥当
    # （必須の商品タイプがある）
    "part_number": "jan",        # メーカー型番 ＝ JAN
    "model_number": "jan",       # 品番・型番 ＝ JAN
    "manufacturer": "brand",     # メーカー名 ＝ ブランド名
    "model_name": "brand",       # モデル ＝ ブランド名
    # メーカー希望小売価格。売価を入れると「参考価格＝売価」になり
    # 値引きが無いのに参考価格があることになる。参考価格なしの0を入れる
    "list_price": "zero",        # メーカー希望小売価格 ＝ 0（なし）
    "item_length_width_height": "dims",   # 品目寸法 ＝ 表の三辺
    # 推奨されるブラウズノード。空だとAmazonの中でどのカテゴリにも
    # 並ばず、客から見つけてもらえない。何番を入れるかは分からないので、
    # 同じ商品を売っているライバルと同じところに置く
    "recommended_browse_nodes": "browse",
}

# 商品ごとに変わるもの。名前に含まれていたら item と見なす
_ITEM_HINTS = (
    "color", "size", "style", "pattern", "flavor", "material",
    "model_name", "length", "width", "height", "weight", "dimension",
    "price", "count", "quantity", "character", "edition", "scent",
    "capacity", "volume", "wattage", "voltage", "age_range", "theme",
)

# カテゴリで毎回同じもの。名前に含まれていたら type と見なす
_TYPE_HINTS = (
    "department", "distribution_designation", "is_exclusive",
    "country", "batteries", "regulation", "warranty", "target_gender",
    "compliance", "certification", "safety", "import",
)


def attr_kind(name: str, override: dict = None) -> str:
    n = (name or "").lower()
    # 「よく聞かれる項目」で全商品ぶん答えているものは、ここでは聞かない
    if n in _COMMON_DEFAULTS:
        return "common"
    if (override or {}).get(n):
        return override[n]
    if n in _AUTO_ATTRS:
        return "auto"
    if any(h in n for h in _TYPE_HINTS):
        return "type"
    if any(h in n for h in _ITEM_HINTS):
        return "item"
    # 迷ったら商品ごと。間違えて覚えるより、毎回聞くほうが安全
    return "item"


def auto_attr_values(db: Session, row, child=None) -> dict:
    """SKUやブランド名から決まる項目。"""
    out = {}
    sku = (child.sku if child is not None else None) or row.parent_sku or ""
    brand = _brand_for(db, row)
    price = (child.price if child is not None and child.price else row.price)
    # 品目寸法。表の三辺（長い順に 長さ・幅・高さ）をそのまま使う
    dims = None
    if all([row.len_a, row.len_b, row.len_c]):
        a, b, c = sorted([row.len_a, row.len_b, row.len_c], reverse=True)
        dims = {"length": a, "width": b, "height": c}
    jan = (child.jan if child is not None else None) or ""
    # ライバルが置かれているブラウズノード。ASINごとに覚えるので、
    # 親と子で何度呼んでも引きに行くのは1回だけ
    browse = amazon_api.fetch_browse_nodes(row.rival_asin or "")
    srcs = {"sku": sku, "brand": brand, "price": price, "dims": dims,
            "jan": jan, "zero": 0,
            "browse": browse[0] if browse else None}
    for name, src in _AUTO_ATTRS.items():
        v = srcs.get(src)
        # 0 は「参考価格なし」として送りたいので、空とは区別する
        if v or v == 0:
            out[name] = v
    return out


# ---------- 商品そのものの寸法を読み取る ----------
#
# Amazonが聞いてくる「品目寸法（L×W×H）」は、商品そのものの大きさ。
# SP-APIから取れるのは梱包サイズなので、そのままでは使えない。
# 競合の商品仕様・商品画像の文字・商品説明に書かれていることが多いので、
# そこから拾って下書きにする（合っているかは人が見る）。

# 「33.1 x 13.1 x 4 cm」「33.1×13.1×4cm」など
_U = r"(?:cm|センチ|mm|ミリ)"
_DIM3 = re.compile(
    r"(\d+(?:\.\d+)?)\s*(" + _U + r")?\s*[×xX✕*]\s*"
    r"(\d+(?:\.\d+)?)\s*(" + _U + r")?\s*[×xX✕*]\s*"
    r"(\d+(?:\.\d+)?)\s*(" + _U + r")?", re.I)

# 「高さ 約31cm」「幅：25cm」など、1つずつ書いてあるとき
_DIM1 = {
    "length": re.compile(r"(?:長さ|奥行き?|全長)\s*[:：]?\s*約?\s*(\d+(?:\.\d+)?)\s*(cm|センチ|mm|ミリ)", re.I),
    "width":  re.compile(r"(?:幅|横)\s*[:：]?\s*約?\s*(\d+(?:\.\d+)?)\s*(cm|センチ|mm|ミリ)", re.I),
    "height": re.compile(r"(?:高さ|縦)\s*[:：]?\s*約?\s*(\d+(?:\.\d+)?)\s*(cm|センチ|mm|ミリ)", re.I),
}


def _to_cm(v: float, unit: str) -> float:
    if (unit or "").lower() in ("mm", "ミリ"):
        return round(v / 10, 2)
    return round(v, 2)


def read_dimensions(texts: list) -> dict:
    """文章から商品そのものの寸法を拾う。見つからなければ空。

    3辺まとめて書いてある形を優先し、無ければ1つずつ拾う。
    """
    for t in texts:
        if not t:
            continue
        m = _DIM3.search(t)
        if m:
            # 単位は数値ごとに付くことも、最後に1つだけのこともある
            units = [m.group(2), m.group(4), m.group(6)]
            last = next((u for u in reversed(units) if u), "cm")
            vals = [float(m.group(i)) for i in (1, 3, 5)]
            a, b, c = (_to_cm(v, units[i] or last) for i, v in enumerate(vals))
            # 大きい順に 長さ・幅・高さ とする
            a, b, c = sorted([a, b, c], reverse=True)
            return {"length": a, "width": b, "height": c,
                    "unit": "centimeters", "source": m.group(0).strip()}

    got, src = {}, []
    for t in texts:
        if not t:
            continue
        for key, rx in _DIM1.items():
            if key in got:
                continue
            m = rx.search(t)
            if m:
                got[key] = _to_cm(float(m.group(1)), m.group(2))
                src.append(m.group(0).strip())
    if got:
        got["unit"] = "centimeters"
        got["source"] = " / ".join(src)
    return got


# 寸法の単位。mm を cm より先に見る（「m」に先に当たらないように）
_DIM_UNITS = (("millimeters", ("mm", "ミリ")),
              ("centimeters", ("cm", "センチ")),
              ("inches", ("inch", "in", "インチ")),
              ("meters", ("メートル",)))

# 枝ごとの書き方。「W40」「幅40」「40」のどれでも読む
_DIM_MARKS = {"length": ("length", "l", "長さ", "長", "奥行", "奥"),
              "width": ("width", "w", "幅"),
              "height": ("height", "h", "高さ", "高")}


def _dim_unit(text) -> str:
    t = str(text or "").lower()
    for unit, words in _DIM_UNITS:
        if any(w in t for w in words):
            return unit
    return "centimeters"


def _dims_from_text(value, keys: list) -> dict:
    """「W40 x H49.5cm」「40×49.5」から枝ごとの数値を読む。

    枝の印（W・幅など）が付いていればそれを優先し、数字だけのときは
    書かれた順に keys へ当てる。
    """
    s = str(value or "")
    out = {}
    for k in keys:
        for mk in _DIM_MARKS[k]:
            m = re.search(re.escape(mk) + r"\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)",
                          s, re.I)
            if m:
                out[k] = float(m.group(1))
                break
    if len(out) < len(keys):
        nums = re.findall(r"[0-9]+(?:\.[0-9]+)?", s)
        if len(nums) >= len(keys):
            out = {k: float(n) for k, n in zip(keys, nums[:len(keys)])}
    return out


def _dim_keys(name: str) -> list:
    """項目名から、入れるべき枝（長さ・幅・高さ）を読む。

    item_length_width / item_width_height / item_length_width_height
    のように、名前そのものが枝を並べている。商品タイプによって
    組み合わせが違う（枕は L×W、ハンガーは W×H）ので決め打ちにしない。
    """
    n = (name or "").lower()
    if not n.startswith("item_"):
        return []
    parts = n[len("item_"):].split("_")
    if len(parts) >= 2 and all(p in _DIM_MARKS for p in parts):
        return parts
    return []


def _wrap_attr(name: str, value, mp: str) -> list:
    """attributes に入れる形にする。

    ふつうは {"value": …} でよいが、品目寸法のように
    枝ごとに値と単位を持つものは、その形で送る。
    """
    # 寸法。枝ごとに値と単位を持つ。文字列をそのまま送ると
    # 「フィールド width に十分な値がありません」で弾かれる。
    # どの枝が要るかは商品タイプで違う（item_length_width /
    # item_width_height / item_length_width_height）ので、
    # 決め打ちにせず項目名から読む
    keys = _dim_keys(name)
    if keys:
        if isinstance(value, dict):
            unit = value.get("unit") or "centimeters"
            got = {k: float(value[k]) for k in keys if value.get(k)}
        else:
            unit = _dim_unit(value)
            got = _dims_from_text(value, keys)
        if got:
            one = {"marketplace_id": mp}
            for k in keys:
                if k in got:
                    one[k] = {"value": got[k], "unit": unit}
            return [one]
        return [{"value": value, "marketplace_id": mp}]

    # ユニット数は「いくつ」と「何の単位で」の2つが要る。
    # value だけ送ると「フィールド type に十分な値がありません」で弾かれる。
    #   value … 数値（文字列だと通らない）
    #   type  … {language_tag, value} の入れ子。単位は自由入力
    # 画面からは数だけ入れてもらい、単位は「個」を既定にする。
    # 「3個」「5 セット」のように単位ごと書かれていたら、それを読む
    if name == "unit_count":
        num, unit = value, "個"
        if isinstance(value, dict):          # すでに形が整っているとき
            num = value.get("value", value.get("count"))
            unit = value.get("type") or value.get("unit") or unit
        else:
            m = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(.*)$", str(value))
            if m:
                num = m.group(1)
                if m.group(2).strip():
                    unit = m.group(2).strip()
        try:
            num = float(num)
            if num == int(num):
                num = int(num)
        except (TypeError, ValueError):
            return [{"value": value, "marketplace_id": mp}]
        return [{"value": num,
                 "type": {"language_tag": "ja_JP", "value": str(unit)},
                 "marketplace_id": mp}]

    return [{"value": value, "marketplace_id": mp}]


def read_material(texts: list, choices: list = None) -> dict:
    """ライバルの商品仕様などから素材を拾う。

    Amazonの選択肢に無い書き方（「PUレザー」「ポリエステル100%」など）も
    あるので、選択肢が渡されていればその中の語に寄せる。
    見つからなければ空を返す（勝手に決めない）。
    """
    words = [c["value"] if isinstance(c, dict) else c for c in (choices or [])]

    def first_hit(text):
        """本文に出てくる選択肢のうち、いちばん先に出るものを返す。

        「PUレザー／裏地ポリエステル」なら、主たる素材である前者を採る。
        """
        best, at = None, None
        for w in words:
            if not w:
                continue
            i = text.find(w)
            if i >= 0 and (at is None or i < at):
                best, at = w, i
        return best

    # 「素材: ポリエステル」のように項目名で書いてあるものが最も確か。
    # 文の途中の「〜な素材を使用」を拾わないよう、行頭か区切りの直後に限り、
    # かつコロンで区切られているものだけを見る
    rx = re.compile(
        r"(?:^|[\n。、／/|｜･・])\s*(?:素材|材質|生地|材料)\s*[:：]\s*([^\n。、]{1,40})",
        re.M)
    for t in texts:
        if not t:
            continue
        m = rx.search(t)
        if not m:
            continue
        said = m.group(1).strip()
        w = first_hit(said)
        if w:
            return {"value": w, "source": m.group(0).strip()}
        # 選択肢に無くても、書いてあること自体は伝える
        return {"value": None, "said": said, "source": m.group(0).strip()}

    # 項目名が無くても、選択肢の語が本文に出ていれば拾う
    for t in texts:
        if not t:
            continue
        w = first_hit(t)
        if w and len(w) >= 3:
            i = t.find(w)
            return {"value": w,
                    "source": t[max(0, i - 12):i + len(w) + 12].strip()}
    return {}


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


def _required_names(schema: dict) -> set:
    """その商品タイプで必須の項目名。定義が取れなければ空。"""
    if not schema.get("ok"):
        return set()
    got = {f.get("name") for f in (schema.get("fields") or [])}
    return {n for n in got if n} | set(schema.get("auto_filled") or [])


def _drop_unknown(attrs: dict, known: set) -> list:
    """その商品タイプに無い項目を落とす。落とした名前を返す。

    型番や品目寸法のように「いつも入れているもの」でも、受け付けない
    商品タイプがある。ハンガー(CLOTHES_HANGER)で model_number と
    item_length_width_height が「商品タイプに属さない」と弾かれた。
    定義が取れなかったときは、何も落とさない（送って確かめる）。
    """
    if not known:
        return []
    gone = [k for k in list(attrs) if k not in known]
    for k in gone:
        attrs.pop(k, None)
    return gone


def _image_rows(db: Session, listing_id: int) -> list:
    """画像の一覧。中身(base64)は読まない。

    公開URLを作るのに要るのは token だけなのに、行ごと読むと
    画像の中身まで全部メモリに載る。親と子で何度も呼ぶので、
    1商品の出品でその何倍も読み込んでいた（出品が返ってこない原因）。
    """
    return (db.query(AmazonListingImage.id, AmazonListingImage.child_id,
                     AmazonListingImage.role, AmazonListingImage.sort_order,
                     AmazonListingImage.public_token,
                     AmazonListingImage.file_name, AmazonListingImage.size)
            .filter(AmazonListingImage.listing_id == listing_id)
            .order_by(AmazonListingImage.sort_order).all())


def _same_image(a, b) -> bool:
    """同じ写真か。ファイル名と大きさで見る（_dedupe_images と同じ基準）。"""
    if a is None or b is None:
        return False
    if not (a.file_name or "").strip() or not a.size:
        return False
    return ((a.file_name or "").strip().lower() == (b.file_name or "").strip().lower()
            and a.size == b.size)


def _dedupe_images(rows: list) -> list:
    """同じ写真を2回送らないようにする。

    共通の欄とメイン（またはバリエーション）の欄に同じ写真を入れると、
    別の行になるのでURLも別になり、Amazonには違う画像として届く。
    実際に商品ページで同じ写真が2枚並んでいた。

    同じ中身かどうかは、ファイル名と大きさで見る。中身(base64)まで
    読むと画像を全部メモリに載せることになるため。
    別名で入れ直した同じ写真までは拾えない。
    """
    out, seen = [], set()
    for r in rows:
        key = ((r.file_name or "").strip().lower(), r.size)
        if key[0] and key[1] and key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _axis_attrs(row: AmazonListing, child: AmazonListingChild) -> dict:
    """子の軸の値。色として送る。"""
    v = (child.axis1 or "").strip()
    return {"color": v} if v else {}


def _attributes(row: AmazonListing, child: AmazonListingChild,
                db: Session, parent_sku: str = None,
                has_variation: bool = None,
                theme: bool = None) -> dict:
    """1SKUぶんの attributes を組み立てる。

    Amazonは項目ごとに [{"value": ..., "marketplace_id": ...}] の形を取る。
    これまで送れていなかった検索キーワード・三辺・重量もここで入れる。
    """
    mp = amazon_api._RESEARCH_MP
    # 共通 → カテゴリで覚えたもの → 商品ごと の順に重ねる。
    # 後のほうが強い（商品ごとの値が最優先）
    extra = dict(common_attrs(db))
    extra.update(auto_attr_values(db, row, child))
    extra.update(memo_values(db, row.product_type))
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

    # 商品のハイライト。商品名が75文字未満のときだけ商品ページに出る短い一言。
    # 項目名は商品タイプによって違うので、定義から探す
    if (row.highlight or "").strip():
        hn = amazon_api.find_attr_name(row.product_type, "highlight")
        if hn:
            a[hn] = one(row.highlight.strip())

    # 検索キーワード。これまで一度も送っていなかった
    if (row.keywords or "").strip():
        a["generic_keyword"] = one(row.keywords.strip())

    if child.jan:
        a["externally_assigned_product_identifier"] = one(child.jan, type="ean")

    price = child.price or row.price
    if price:
        # audience が無いと、誰向けの値段か決まらず申し出として成立しない。
        # 価格が入らないので出品情報が埋まらず、ASINが出ないままになる
        a["purchasable_offer"] = [{
            "marketplace_id": mp, "audience": "ALL", "currency": "JPY",
            "our_price": [{"schedule": [{"value_with_tax": int(price)}]}],
        }]
    # FBAか自己発送か。DEFAULT は自己発送を意味するので、
    # FBAの商品をそのまま送ると出荷方法が食い違ってしまう。
    # 自己発送のときだけ在庫0で作る（実在庫は既存の在庫連携が入れる）。
    if _fulfillment_of(db, row) == "fba":
        a["fulfillment_availability"] = [{
            "fulfillment_channel_code": "AMAZON_JP",
        }]
    else:
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

    # 画像の並び。商品画像の大半は全色で同じなので共通に入れておき、
    # 色で変わるメインとバリエーションだけを色ごとに持たせる。
    #   その色のメイン → 共通の画像すべて → その色のバリエーション画像
    # バリエーション画像はAmazonでも最後尾に出るので、末尾に置く。
    base = _public_base()
    if base:
        imgs = _image_rows(db, row.id)
        shared = [i for i in imgs if i.child_id is None]
        ownall = [i for i in imgs if i.child_id == child.id]
        main = next((i for i in ownall if i.role == "main"), None)
        var = next((i for i in ownall if i.role == "variation"), None)
        rest = [i for i in ownall if i is not main and i is not var]
        if main is None:
            # 役割を決めていない古いデータや、共通しか無い商品に備える
            main = rest.pop(0) if rest else (shared[0] if shared else None)
        mid = rest + [i for i in shared if i is not main]
        # Amazonが受け取れるのはメイン1枚＋サブ8枚の計9枚。溢れるときは
        # 真ん中（共通）から落とす。メインとバリエーションは必ず残す
        # （バリエーション画像は最後尾に出したいので、ここで切られては困る）
        # 共通とメイン・バリエーションに同じ写真が入っていることがある。
        # 先に重複を落としてから枠に収める（落とす前に切ると、
        # 重複のぶんだけ本当に出したい写真が溢れてしまう）
        mid = [i for i in _dedupe_images(mid)
               if i is not main and i is not var
               and not _same_image(i, main) and not _same_image(i, var)]
        room = AMAZON_IMAGE_SLOTS - (1 if main else 0) - (1 if var else 0)
        mine = ([main] if main else []) + mid[:max(0, room)]             + ([var] if var else [])
        urls = [f"{base}/api/amazon-listings/public-image/{i.public_token}"
                for i in mine]
        if urls:
            a["main_product_image_locator"] = [
                {"marketplace_id": mp, "media_location": urls[0]}]
            # サブ画像は other_product_image_locator_1 〜 _8 と、番号付きで
            # 1枚ずつ送る。まとめて other_product_image_locator で送ると
            # 「商品タイプに属さない」と言われ、値ごと無視される
            # （VALIDで通るのにサブ画像が1枚も出なかった原因）
            for n, u in enumerate(urls[1:AMAZON_IMAGE_SLOTS], start=1):
                a[f"other_product_image_locator_{n}"] = [
                    {"marketplace_id": mp, "media_location": u}]

    # バリエーションの子。親との紐づけと、軸の値を入れる
    if parent_sku is not None:
        a["parentage_level"] = one("child")
        a["child_parent_sku_relationship"] = [{
            "marketplace_id": mp, "child_relationship_type": "variation",
            "parent_sku": parent_sku,
        }]
        # バリエーションのときだけテーマと軸の値を送る。
        # 子だけがテーマを送ると、テーマを持たない親と食い違って弾かれる。
        # has_variation が渡っていない呼び出しは、これまでどおり
        # 軸の有無で判断する
        # theme は「商品タイプがテーマを必須にしているか」。
        # 子が1つでも必須なら送る（ハンガーで必須と言われた）
        want = (has_variation is not False) if theme is None else theme
        axis = _axis_attrs(row, child) if want else {}
        if axis or theme:
            a["variation_theme"] = [{"marketplace_id": mp,
                                     "name": VARIATION_THEME}]
        for key, val in axis.items():
            a[key] = one(val)

    # 商品タイプごとの必須項目。画面で入れてもらったもの
    for k, v in extra.items():
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        a[k] = _wrap_attr(k, v, mp)
    return a


def _parent_attributes(row: AmazonListing, has_variation: bool = True,
                       db: Session = None, theme: bool = None) -> dict:
    """親。売り物ではないので価格も在庫も付けない。

    Amazonは単品でも親子で作るのが推奨なので、バリエーションが無くても
    親は出す。そのときはバリエーションテーマを付けない
    （軸が無いのにテーマだけ送ると弾かれるため）。
    ただし商品タイプがテーマを必須にしているときは theme=True で送る。
    """
    mp = amazon_api._RESEARCH_MP
    extra = dict(common_attrs(db)) if db is not None else {}
    if db is not None:
        extra.update(auto_attr_values(db, row))
        extra.update(memo_values(db, row.product_type))
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
    # 子が1つでも、商品タイプがテーマを必須にしているなら送る
    if has_variation if theme is None else theme:
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
    # 商品のハイライト。商品名が75文字未満のときだけ商品ページに出る短い一言。
    # 項目名は商品タイプによって違うので、定義から探す
    if (row.highlight or "").strip():
        hn = amazon_api.find_attr_name(row.product_type, "highlight")
        if hn:
            a[hn] = one(row.highlight.strip())

    # 親の画像。メイン写真は色ごとに持つので、共通には説明画像しか
    # 入っていない。親のメインには最初の色のメイン写真を使い、
    # 残りを共通で埋める（共通にメイン用の写真を置かなくて済むように）
    base = _public_base()
    if db is not None and base:
        imgs = _image_rows(db, row.id)
        shared = [i for i in imgs if i.child_id is None]
        first_main = None
        kid_ids = [c.id for c in db.query(AmazonListingChild)
                   .filter(AmazonListingChild.listing_id == row.id)
                   .order_by(AmazonListingChild.sort_order).all()]
        for cid in kid_ids:
            first_main = next((i for i in imgs
                               if i.child_id == cid and i.role == "main"), None)
            if first_main:
                break
        mine = _dedupe_images(([first_main] if first_main else []) + shared)
        if not mine:
            mine = _dedupe_images(imgs)
        mine = mine[:AMAZON_IMAGE_SLOTS]
        urls = [f"{base}/api/amazon-listings/public-image/{i.public_token}"
                for i in mine]
        if urls:
            a["main_product_image_locator"] = [
                {"marketplace_id": mp, "media_location": urls[0]}]
            # サブ画像は other_product_image_locator_1 〜 _8 と、番号付きで
            # 1枚ずつ送る。まとめて other_product_image_locator で送ると
            # 「商品タイプに属さない」と言われ、値ごと無視される
            # （VALIDで通るのにサブ画像が1枚も出なかった原因）
            for n, u in enumerate(urls[1:AMAZON_IMAGE_SLOTS], start=1):
                a[f"other_product_image_locator_{n}"] = [
                    {"marketplace_id": mp, "media_location": u}]

    for k, v in extra.items():
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        a[k] = _wrap_attr(k, v, mp)
    return a


@router.post("/{listing_id:int}/verify")
def verify_listing(listing_id: int, db: Session = Depends(get_db)):
    """出したあと、Amazonから読み戻して送った内容と突き合わせる。

    送りっぱなしだと「登録はできたのに親子が繋がっていない」
    「画像が入っていない」に気づけない。実際にそうなっていて、
    あとから商品ページを見て分かった。ここで機械的に確かめる。

    画像が正しい色のものかまでは見られない（枚数しか分からない）。
    そこは人が商品ページを見るしかないので、リンクも返す。
    """
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")

    kids = (db.query(AmazonListingChild)
            .filter(AmazonListingChild.listing_id == row.id)
            .order_by(AmazonListingChild.sort_order).all())
    if not kids:
        raise HTTPException(400, "出品するSKUがありません")

    has_variation = len(kids) > 1
    parent_sku = ((row.parent_sku or "").strip()
                  or (kids[0].sku or "").split("_")[0])

    imgs = _image_rows(db, row.id)
    # 色ごとに入れていない画像は「共通」として全SKUに使われる
    shared_rows = [i for i in imgs if i.child_id is None]

    out = []
    ng = 0

    # ---- 親 ----
    if has_variation:
        got = amazon_api.fetch_listing(parent_sku)
        notes = []
        if not got.get("found"):
            notes.append(got.get("error") or "見つかりません")
        else:
            if not got.get("variation_theme"):
                notes.append("バリエーションテーマが入っていません")
            if not got.get("asin"):
                notes.append("ASINがまだ出ていません。"
                             "必須項目が足りないと、受け付けられても商品にならない")
            # 受け付けたあとで見つかった問題は、読み戻さないと分からない。
            # 子だけ拾っていて親を拾っていなかったため、親の不足が
            # 見えず「不足している情報」の理由にたどり着けなかった
            for i in (got.get("issues") or []):
                if i.get("message"):
                    notes.append(f"Amazonからの指摘: {i.get('message')}")
        if notes:
            ng += 1
        out.append({
            "kind": "親", "sku": parent_sku, "ok": not notes,
            "asin": got.get("asin"), "notes": notes,
            "url": (f"https://www.amazon.co.jp/dp/{got['asin']}"
                    if got.get("asin") else None),
        })

    # ---- 子 ----
    for c in kids:
        if not c.sku:
            continue
        got = amazon_api.fetch_listing(c.sku)
        notes = []
        if not got.get("found"):
            notes.append(got.get("error") or "見つかりません")
        else:
            # 親子の繋がり。ここが切れるとバリエーションが崩れる
            if has_variation:
                p = (got.get("parent_sku") or "").strip()
                if not p:
                    req = got.get("requested_parent_sku")
                    notes.append(
                        "親に紐づいていません（単独の商品になっています）"
                        + ("。親SKUは送れているので、Amazon側でまだ"
                           "組まれていません" if req else ""))
                elif p != parent_sku:
                    notes.append(f"別の親に紐づいています（{p}）")
            # 画像。Amazonが持てるのはメイン1枚＋サブ8枚の計9枚なので、
            # 用意した枚数がそれを超えていても、入るのは9枚まで。
            # 用意した枚数と比べると、正常なのに「足りません」と出てしまう
            # 送る枚数は重複を落としたあとの数。落とす前の数で比べると、
            # 正常なのに「画像が足りません」と出てしまう
            own = [i for i in imgs if i.child_id == c.id]
            want = min(len(_dedupe_images(own + shared_rows)),
                       AMAZON_IMAGE_SLOTS)
            have = got.get("image_count") or 0
            if want and not have:
                notes.append(f"画像が1枚も入っていません（送ったのは{want}枚）")
            elif want and have < want:
                notes.append(f"画像が足りません（Amazon {have}枚 / 送ったのは{want}枚）")
            want_price = c.price or row.price
            if want_price and not got.get("price"):
                notes.append(
                    f"値段が入っていません（送ったのは{int(want_price)}円）。"
                    "値段が無いと在庫管理で「出品情報がありません」になり、"
                    "ASINが出ていても売れる状態になりません")
            want_ch = ("AMAZON_JP" if _fulfillment_of(db, row) == "fba"
                       else "DEFAULT")
            got_ch = got.get("fulfillment_channel")
            if got_ch and got_ch != want_ch:
                notes.append(
                    "出荷方法が食い違っています（Amazon "
                    + ("FBA" if got_ch == "AMAZON_JP" else "自己発送")
                    + " / 送ったのは "
                    + ("FBA" if want_ch == "AMAZON_JP" else "自己発送") + "）")
            if not got.get("browse_node"):
                notes.append(
                    "ブラウズノードが入っていません。Amazonの中で"
                    "カテゴリに並ばないので、客から見つけてもらえません")
            if got.get("batteries_required") is None:
                notes.append(
                    "電池の申告が入っていません。これが無いと在庫管理で"
                    "「出品情報がありません」のままになります（Amazonのエラー 90220）")
            # FNSKUはFBAの納品を作ってから出るもので、出品の時点では
            # 出ていなくて当たり前。自己発送なら最後まで出ない。
            # これを「違うところ」に数えていたため、全部うまくいっても
            # 「3件おかしい」と出て、どれが本当の問題か分からなかった
            if not got.get("asin"):
                notes.append("ASINがまだ出ていません。"
                             "必須項目が足りないと、受け付けられても商品にならない")
            for i in (got.get("issues") or []):
                if i.get("severity") in ("ERROR", "WARNING"):
                    notes.append(f"Amazonからの指摘: {i.get('message')}")
        if notes:
            ng += 1
        # 読めたASIN・FNSKUはその場で残す。出すだけだと、再梱包指示や
        # 商品マスタからは永久に見えないままになる（自己発送はFBA在庫の
        # 取り込みにも出てこないので、ここが唯一の入り口になる）
        _keep_ids(db, c, got.get("asin"), got.get("fnsku"))

        out.append({
            "kind": "子" if has_variation else "単品", "sku": c.sku,
            "ok": not notes, "asin": got.get("asin"),
            "fnsku": got.get("fnsku"), "color": got.get("color"),
            "price": got.get("price"),
            "images": got.get("image_count"), "notes": notes,
            "url": (f"https://www.amazon.co.jp/dp/{got['asin']}"
                    if got.get("asin") else None),
        })

    db.commit()

    return {
        "ok": ng == 0, "ng": ng, "items": out,
        "note": ("画像が正しい色のものかまでは分かりません。"
                 "商品ページを開いて目で確かめてください"),
    }


def _keep_ids(db: Session, child: AmazonListingChild,
              asin: str = None, fnsku: str = None) -> None:
    """Amazonから読めたASIN・FNSKUを残す。

    出品の子と、商品マスタ（再梱包指示や発注が見るところ）の両方に入れる。
    自己発送の商品はFBA在庫の取り込みに出てこないので、Amazonから
    読み戻すこの経路が唯一の入り口になる。

    手で直した値を消さないよう、空のときだけ入れる。ASINは一度付けば
    変わらないので、上書きの必要もない。
    """
    asin = (asin or "").strip()
    fnsku = (fnsku or "").strip()
    if not asin and not fnsku:
        return
    if asin and not (child.asin or "").strip():
        child.asin = asin
    sku = (child.sku or "").strip()
    if not sku:
        return
    p = db.query(Product).filter(Product.sku == sku).first()
    if p is None:
        return
    if asin and not (p.asin or "").strip():
        p.asin = asin
    if fnsku and not (p.fnsku or "").strip():
        p.fnsku = fnsku


# 親ができるまで待てる上限（1リクエスト全体で）。
# 画面側の待ち時間は3分なので、それより短くしておく
_PARENT_WAIT_SECONDS = 120
_PARENT_POLL_SECONDS = 10


def _wait_for_parent(sku: str, deadline: float) -> dict:
    """親がAmazonのカタログにできるまで待つ。

    出品のPUTが返す ACCEPTED は「依頼を受け取った」という意味でしかなく、
    カタログに商品ができた印ではない。Amazonの処理は後追いなので、
    受け取った直後に子を送ると、親はまだ存在しない。
    そうすると子は必ず

        商品がカタログにないため、SKUに出品情報を追加できません

    で弾かれる。送る中身をいくら直しても直らなかったのはこれが理由で、
    親子が組めず、子が全滅していた。
    ASINが出たら親ができた合図なので、それまで待ってから子を送る。
    """
    while True:
        got = amazon_api.fetch_listing(sku)
        if got.get("asin"):
            return got
        if time.monotonic() >= deadline:
            return got
        time.sleep(_PARENT_POLL_SECONDS)


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
    # 親待ちの上限は、1回の送信ぜんたいで使い切る。商品ごとに待つと
    # 複数まとめて出したときに画面が待ちきれなくなる
    deadline = time.monotonic() + _PARENT_WAIT_SECONDS
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
        # 商品タイプの定義。送れない項目を落とすのと、テーマが必須か
        # どうかを見るのに使う
        schema0 = amazon_api.fetch_product_type_schema(row.product_type)
        known = set(schema0.get("all_names") or [])
        titles = schema0.get("titles") or {}
        need_theme = "variation_theme" in _required_names(schema0)
        theme = True if (need_theme and not has_variation) else None

        item = {"listing_id": lid, "title": row.title,
                "product_type": row.product_type,
                "problems": problems, "sent": [], "asked": []}

        def remember(r, item=item, known=known, titles=titles,
                     pt=row.product_type):
            # 弾かれたときに「何が足りないと言われたか」を覚える。
            # ここで覚えないと、④で失敗しても入力欄が増えないままになる
            for n in _remember_asked(db, pt, r.get("issues") or [],
                                     known, titles):
                if n not in item["asked"]:
                    item["asked"].append(n)

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
        attrs = _parent_attributes(row, has_variation, db, theme=theme)
        gone = _drop_unknown(attrs, known)
        rec = {"sku": parent_sku, "kind": "親", "attributes": attrs}
        if gone:
            rec["dropped"] = gone
        if body.dry_run:
            rec["dry_run"] = True
            item["sent"].append(rec)
        else:
            r = amazon_api.submit_listing(parent_sku, row.product_type, attrs)
            rec.update(r)
            item["sent"].append(rec)
            if not r.get("ok"):
                remember(r)
                item["ok"] = False
                item["error"] = "親の登録に失敗したので、子は送っていません"
                row.status = "failed"
                db.commit()
                results.append(item)
                continue
            # 親がカタログにできるのを待ってから子を送る。
            # 待たずに送ると、親がまだ無いので子が全部弾かれる
            if has_variation:
                got = _wait_for_parent(parent_sku, deadline)
                rec["parent_asin"] = got.get("asin")
                if not got.get("asin"):
                    item["ok"] = False
                    item["error"] = (
                        f"親 {parent_sku} はAmazonが受け取りましたが、まだ"
                        "カタログにできていません。親のいない子を送ると"
                        "全部弾かれるので、子はまだ送っていません。"
                        "数分おいて、もう一度「④ Amazonへ出品する」を"
                        "押してください。"
                        "この親SKUを最近削除した場合は、削除したSKUは"
                        "しばらく作り直せません（半日〜1日）。"
                        "待てないときは、親SKUを別の名前にしてください")
                    row.status = "submitted"
                    db.commit()
                    results.append(item)
                    continue

        all_ok = True
        for c in kids:
            attrs = _attributes(row, c, db, parent_sku=parent_sku,
                                has_variation=has_variation, theme=theme)
            gone = _drop_unknown(attrs, known)
            rec = {"sku": c.sku, "kind": "子" if has_variation else "単品",
                   "jan": c.jan, "attributes": attrs}
            if gone:
                rec["dropped"] = gone
            if body.dry_run:
                rec["dry_run"] = True
            else:
                r = amazon_api.submit_listing(c.sku, row.product_type, attrs)
                rec.update(r)
                if not r.get("ok"):
                    remember(r)
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
    "highlight": "listingHighlight",
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
        "highlight": src.get("highlight") or "",
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

    # 色で突き合わせる。並び順で突き合わせると、シートの色を入れ替えたり
    # 間に1色足したりしたときに、SKUとJANはそのままで色だけがずれる。
    # a06_black に白のJANが付く、という壊れ方を実際にしていた。
    def key(v):
        return "".join((v or "").split()).lower()

    by_axis = {}
    for c in kids:
        k = key(c.axis1)
        if k:
            by_axis.setdefault(k, []).append(c)

    used = set()
    pairs = []          # (シートの子, こちらの子 or None)
    for sk in sheet_kids:
        k = key(sk.get("axis1"))
        hit = None
        for c in by_axis.get(k, []):
            if id(c) not in used:
                hit = c
                break
        if hit is not None:
            used.add(id(hit))
        pairs.append((sk, hit))

    # 色が付いていない子（単品から育ったものなど）は、順番で引き当てる
    spare = [c for c in kids if id(c) not in used and not key(c.axis1)]
    for i, (sk, hit) in enumerate(pairs):
        if hit is None and spare:
            pairs[i] = (sk, spare.pop(0))
            used.add(id(pairs[i][1]))

    for i, (sk, c) in enumerate(pairs):
        if c is None:
            c = AmazonListingChild(listing_id=row.id)
            db.add(c)
        c.sort_order = i
        c.title = sk.get("title") or ""
        c.axis1 = sk.get("axis1") or ""

    # シートから消えたぶん。まだJANを振っていなければ落とす
    for c in kids:
        if id(c) not in used and not c.jan:
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


# ---------- カテゴリごとに覚える ----------
#
# Amazonの商品タイプは数百あり、必須項目を先に網羅するのは現実的でない。
# 「検証を押す → 足りない項目が出る → 入れる → 覚える」を繰り返し、
# 同じカテゴリの2件目からは入力が要らないようにする。
#
# Amazonが返す issues には、足りない属性の名前が attributeNames で入る。
# 文言だけだと拾えないので、そこを見る。

def _memo_of(db: Session, product_type: str) -> AmazonProductTypeMemo:
    pt = (product_type or "").strip().upper()
    if not pt:
        return None
    row = (db.query(AmazonProductTypeMemo)
           .filter(AmazonProductTypeMemo.product_type == pt).first())
    if row is None:
        row = AmazonProductTypeMemo(product_type=pt)
        db.add(row)
        db.flush()
    return row


def memo_values(db: Session, product_type: str) -> dict:
    """そのカテゴリで覚えている入力値。"""
    row = (db.query(AmazonProductTypeMemo)
           .filter(AmazonProductTypeMemo.product_type ==
                   (product_type or "").strip().upper()).first())
    if row is None or not row.values:
        return {}
    try:
        v = json.loads(row.values)
        if not isinstance(v, dict):
            return {}
        # __kinds__ は分類の上書きなので、出品には混ぜない
        return {k: x for k, x in v.items() if not k.startswith("__")}
    except (ValueError, TypeError):
        return {}


# 指摘の文章で項目名を囲んでいる記号。Amazonは日本語の全角・半角の
# どちらも使ってくる
_QUOTES = "'‘’\"“”「」『』"


def _quoted(text: str) -> list:
    """「'商品の入数' は必須ですが…」の、囲まれている部分を取り出す。"""
    out, buf, open_q = [], None, None
    for ch in str(text or ""):
        if open_q is None:
            if ch in _QUOTES:
                open_q, buf = ch, []
            continue
        if ch in _QUOTES:
            s = "".join(buf).strip()
            if s:
                out.append(s)
            open_q, buf = None, None
            continue
        buf.append(ch)
    return out


def _asked_from(issues: list, titles: dict = None) -> list:
    """Amazonの指摘から、足りない属性の名前を拾う。

    attributeNames が付いていれば、それが一番確か。
    付いていないことがあり（ハンガーの必須4項目がこれだった）、
    そのときは文章の中の「'商品の入数'」のような囲みを拾って、
    日本語の表示名から項目名へ引き直す。
    """
    out = []

    def add(n):
        n = str(n or "").strip()
        if n and n not in out:
            out.append(n)

    for i in (issues or []):
        if not isinstance(i, dict):
            continue
        names = [str(n).strip() for n in (i.get("attributeNames") or [])]
        names = [n for n in names if n]
        for n in names:
            add(n)
        if names:
            continue
        for q in _quoted(i.get("message")):
            add((titles or {}).get(q) or q)
    return out


def _remember_asked(db: Session, product_type: str, issues: list,
                    known: set = None, titles: dict = None) -> list:
    """聞かれた項目をカテゴリに貯める。次回は先回りして欄を出せる。

    Amazonの指摘には、属性名でないもの（SKUそのものなど）も混ざる。
    定義にある項目だけを残さないと、入力欄に妙なものが並ぶ。
    """
    asked = _asked_from(issues, titles)
    if known:
        asked = [a for a in asked if a in known]
    if not asked:
        return []
    row = _memo_of(db, product_type)
    if row is None:
        return []
    try:
        have = json.loads(row.asked) if row.asked else []
        have = have if isinstance(have, list) else []
    except (ValueError, TypeError):
        have = []
    added = [a for a in asked if a not in have]
    if added:
        row.asked = json.dumps(have + added, ensure_ascii=False)
    return added


@router.get("/product-type-schema/{product_type}")
def product_type_schema(product_type: str, name: str = ""):
    """項目の定義をそのまま見る。

    unit_count のように value だけでなく type（単位）も要るものがあり、
    「フィールド type に十分な値がありません」と言われたときに、
    何を送ればよいかを確かめるために使う。name を省くと項目名の一覧。
    """
    return amazon_api.fetch_raw_property(product_type, name)


@router.get("/product-type-memo/{product_type}")
def get_memo(product_type: str, db: Session = Depends(get_db)):
    """そのカテゴリで覚えている値と、これまでに聞かれた項目。"""
    pt = (product_type or "").strip().upper()
    row = (db.query(AmazonProductTypeMemo)
           .filter(AmazonProductTypeMemo.product_type == pt).first())
    if row is None:
        return {"product_type": pt, "values": {}, "asked": [], "used_count": 0}
    def jl(v, d):
        try:
            x = json.loads(v) if v else d
            return x if isinstance(x, type(d)) else d
        except (ValueError, TypeError):
            return d
    vals = jl(row.values, {})
    return {"product_type": pt, "display_name": row.display_name,
            "values": {k: v for k, v in vals.items() if not k.startswith("__")},
            "kinds": vals.get("__kinds__") or {},
            "asked": jl(row.asked, []),
            "used_count": row.used_count or 0,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


class MemoIn(BaseModel):
    values: Optional[dict] = None       # 覚えさせたい値
    kinds: Optional[dict] = None        # 分類の上書き {属性名: "type"|"item"}
    display_name: Optional[str] = None


@router.put("/product-type-memo/{product_type}")
def put_memo(product_type: str, body: MemoIn, db: Session = Depends(get_db)):
    """このカテゴリで毎回同じになる値を覚えさせる。

    覚えるのは「カテゴリで毎回同じ」と分類した項目だけ。
    商品ごとに変わるものは、こちらで判断して外す。
    """
    row = _memo_of(db, (product_type or "").upper())
    if row is None:
        raise HTTPException(400, "商品タイプがありません")
    if body.display_name:
        row.display_name = body.display_name

    now = memo_values(db, row.product_type)
    kinds = dict((get_memo(product_type, db).get("kinds") or {}))
    if body.kinds:
        kinds.update({k: v for k, v in body.kinds.items()
                      if v in ("type", "item")})

    if body.values is not None:
        for k, v in body.values.items():
            if k in _COMMON_DEFAULTS or k in _AUTO_ATTRS:
                continue      # 共通・自動で入るものは覚えない
            if attr_kind(k, kinds) != "type":
                # common・auto・item はここでは覚えない
                now.pop(k, None)
                continue      # 商品ごとに変わるものは覚えない
            if v in (None, ""):
                now.pop(k, None)
            else:
                now[k] = v

    keep = dict(now)
    if kinds:
        keep["__kinds__"] = kinds
    row.values = json.dumps(keep, ensure_ascii=False)
    db.commit()
    return get_memo(product_type, db)


@router.post("/{listing_id:int}/validate")
def validate(listing_id: int, db: Session = Depends(get_db)):
    """Amazonに中身だけ見てもらう。出品はしない。

    カテゴリごとの必須項目は数が多く、先に網羅できない。
    ここで「足りない」と言われたものを覚えておき、
    同じカテゴリの2件目からは先回りして欄を出す。
    """
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "ありません")
    if not row.product_type:
        raise HTTPException(400, "先に「出品の準備」を押してください")

    kids = (db.query(AmazonListingChild)
            .filter(AmazonListingChild.listing_id == row.id)
            .order_by(AmazonListingChild.sort_order).all())
    if not kids:
        raise HTTPException(400, "出品するSKUがありません")

    has_variation = len(kids) > 1
    parent_sku = ((row.parent_sku or "").strip()
                  or (kids[0].sku or "").split("_")[0]
                  or f"a{row.id:02d}")

    # 定義にある項目名。これに無いものは覚えない
    schema0 = amazon_api.fetch_product_type_schema(row.product_type)
    known = set(schema0.get("all_names") or [])
    titles = schema0.get("titles") or {}

    checked = []
    asked_all = []

    def run(sku, attrs, kind):
        if not sku:
            return
        # ④と同じものを送らないと、検証が通ったのに出品で弾かれる
        _drop_unknown(attrs, known)
        r = amazon_api.submit_listing(sku, row.product_type, attrs,
                                      validate_only=True)
        issues = r.get("issues") or []
        added = _remember_asked(db, row.product_type, issues, known, titles)
        asked_all.extend(a for a in added if a not in asked_all)
        checked.append({
            "kind": kind, "sku": sku, "ok": bool(r.get("ok")),
            "status": r.get("status"), "error": r.get("error"),
            "issues": [{"message": i.get("message"),
                        "severity": i.get("severity"),
                        "attributes": i.get("attributeNames") or []}
                       for i in issues if isinstance(i, dict)],
        })

    # 子が1つでも、商品タイプがテーマを必須にしているなら送る
    need_theme = "variation_theme" in _required_names(schema0)
    theme = True if (need_theme and not has_variation) else None
    run(parent_sku, _parent_attributes(row, has_variation, db,
                                       theme=theme), "親")
    for c in kids:
        run(c.sku, _attributes(row, c, db, parent_sku=parent_sku,
                               has_variation=has_variation, theme=theme),
            "子" if has_variation else "単品")

    db.commit()

    # 足りないと言われた項目を、入力欄として出せる形にする
    by_name = {f["name"]: f for f in (schema0.get("fields") or [])}
    memo = get_memo(row.product_type, db)
    # 以前に貯めた中に、属性でないものが混ざっていたら落とす
    if known:
        clean = [n for n in memo["asked"] if n in known]
        if clean != memo["asked"]:
            m = _memo_of(db, row.product_type)
            m.asked = json.dumps(clean, ensure_ascii=False)
            memo["asked"] = clean
    kinds = memo.get("kinds") or {}
    auto = auto_attr_values(db, row, kids[0] if kids else None)
    common = common_attrs(db)

    # 商品そのものの寸法。競合の商品仕様・画像の文字・商品説明から拾う。
    # SP-APIで取れるのは梱包サイズなので、そのままでは使えない
    src2 = None
    for c in sync.candidates(_sheet(db), all_status=True):
        if c["research_id"] == row.research_id:
            src2 = c
            break
    texts = []
    if src2:
        notes = _notes_for(db, [x.get("row_id") for x in (src2.get("rows") or [])
                                if x.get("row_id")])
        for n in notes.values():
            texts += [n.get("spec"), n.get("imgtext")]
    texts.append(row.description)
    dims = read_dimensions(texts)

    # 素材。ライバルの商品仕様などから拾う（無ければ空のまま）
    mat_choices = (by_name.get("material") or {}).get("choices") or []
    material = read_material(texts, mat_choices)

    need = []
    for n in memo["asked"]:
        # 商品名・JAN・価格・画像などツールが埋めるものは、ここでは聞かない
        if n in amazon_api._FILLED_BY_TOOL:
            continue
        f = dict(by_name.get(n) or {"name": n, "label": n, "type": "text",
                                    "choices": []})
        f["kind"] = attr_kind(n, kinds)
        if f["kind"] == "auto":
            f["auto_value"] = auto.get(n)
        elif f["kind"] == "common":
            f["auto_value"] = _common_label(n, common.get(n))
        # 素材も読み取れたものを添える
        if n == "material" and material:
            if material.get("value"):
                f["suggest"] = material["value"]
            elif material.get("said"):
                f["suggest_note"] = f"ライバルの記載: {material['said']}"
            f["suggest_from"] = material.get("source")
        # 寸法は読み取れたものを下書きとして添える
        if n == "item_length_width_height" and dims:
            f["suggest"] = (f"{dims.get('length','')}×{dims.get('width','')}"
                            f"×{dims.get('height','')} cm")
            f["suggest_from"] = dims.get("source")
            f["suggest_values"] = {k: v for k, v in dims.items()
                                   if k in ("length", "width", "height")}
        need.append(f)

    links = _links_of(src2)

    return {"checked": checked,
            "newly_asked": asked_all,
            "need": need,
            "dimensions": dims,
            "material": material,
            "links": links,
            "memo": memo}


# ---------- 商品マスタへの登録 ----------
#
# 出品の準備ができても、これまでツールのAmazon商品マスタには1行も
# 作られていなかった。そのため出品した商品が発注管理にも在庫管理にも
# 出てこない。発注はマスタの情報を使うので、出品を送るより前に作る。
#
# 押す前に必ず対応表を見せる（/master-preview）。仕入URLと入数を
# 推測で埋めると、違うものを違う数だけ発注することになるため。


def _src_of(db: Session, research_id: str) -> dict | None:
    """シートから、その出品の元になったリサーチを引く。

    仕入URL・単価・入数はシートが持っていて、出品レコードには無い。
    採用以外の状態に戻されていても引けるよう all_status で探す。
    """
    for c in sync.candidates(_sheet(db), all_status=True):
        if c["research_id"] == research_id:
            return c
    return None


def _master_rows(db: Session, row: AmazonListing, src: dict) -> dict:
    """商品マスタに作る予定の中身を組み立てる。まだ書き込まない。"""
    parts = src.get("parts") or []
    urls = [u for u in (src.get("urls_1688") or []) if u]
    main = parts[0] if parts else None
    # 付属品は「画像外注へ渡す情報」の欄から取る。部材（単価×入数）は原価の
    # ための入力で、そこには仕入先の言い方が入っていないため、発注先を決められない
    acc = src.get("accessories") or []

    warnings = []
    # 仕入URLの決め方。候補が1本だけなら迷いようがないので入れておく。
    # 2本以上あるときは選んでもらう。黙って先頭を採ると、選んでいない
    # 仕入先に発注してしまう
    buy_url = (src.get("main_url") or "").strip() or (main or {}).get("url") or ""
    if not buy_url:
        if len(urls) == 1:
            buy_url = urls[0]
        elif len(urls) > 1:
            warnings.append(f"仕入URLの候補が{len(urls)}件あります。どれで発注するか選んでください")
        else:
            warnings.append("仕入URLがシートに入っていません。あとで商品マスタに入れてください")
    if not main:
        warnings.append("1688単価がシートに入っていないので、単価と入数は空になります")
    if len(parts) > 1 and not acc:
        warnings.append(
            f"部材が{len(parts)}件ありますが、付属品の欄が空です。"
            "一緒に発注するものがあるなら「画像外注へ渡す情報」の付属品に"
            "中国語名を入れてください")

    # 付属品は在庫連動しない発注用の行。仕入先の言い方（中国語名）が無いと
    # 何を買えばよいか決まらないので、入っていなければ知らせる。
    # URLが空なら本体と同じページから買う
    components = []
    for a in acc:
        if not (a.get("name") or "").strip():
            warnings.append("付属品に中国語名が入っていません。"
                            "何を買うか決められないので入れてください")
        if a.get("price") in (None, "", 0):
            warnings.append(
                f"付属品「{a.get('name') or '名前なし'}」に単価が入っていません。"
                "原価に乗らないので、そのぶん利益を多く見積もります")
        # SKUが無いと、タオタロウへの発注行に番号が入らず紐づけられない。
        # 画面で決めてもらうので、空なら知らせる
        if not (a.get("sku") or "").strip():
            warnings.append(
                f"付属品「{a.get('name') or '名前なし'}」にSKUがありません。"
                "タオタロウへの発注で紐づけられないので、"
                "シートの付属品欄にSKUを入れてください（例: a09_1_tape）")
        components.append({
            "sku": (a.get("sku") or "").strip(), "qty": a.get("qty") or 1,
            "buy_url": (a.get("url") or "").strip() or buy_url,
            # 仕入先の言い方は中国語名。人が読む名前は日本語のほうを使う
            "supplier_spec": a.get("name") or "",
            "name": (a.get("jp_name") or "").strip() or a.get("name") or "",
            "price": a.get("price"),
        })

    kids = (db.query(AmazonListingChild)
            .filter(AmazonListingChild.listing_id == row.id)
            .order_by(AmazonListingChild.sort_order,
                      AmazonListingChild.id).all())
    out = []
    for c in kids:
        if not (c.sku or "").strip():
            continue
        exist = db.query(Product).filter(Product.sku == c.sku).first()
        spec = "／".join([x for x in [c.axis1, c.axis2] if x])
        out.append({
            "sku": c.sku,
            "name": (c.title or row.title or "").strip(),
            "color": c.axis1 or "",
            "size": c.axis2 or "",
            # 仕入先の言い方。発注のとき、どの色の何を買うかの決め手になる。
            # 色ごとに入っていればそれを使う。共通の欄に2色まとめて書かれて
            # いると、どちらのSKUを買うか決められないため
            "spec": ((src.get("cn_names") or {}).get(c.axis1 or "")
                     or (src.get("cn_name") or "").strip() or spec),
            "buy_url": buy_url,
            "price": (main or {}).get("price"),
            "set_size": int((main or {}).get("qty") or 1),
            "selling_price": c.price or row.price,
            "cost_jpy": src.get("cost_jpy"),
            "fba_fee": src.get("fee"),
            "asin": c.asin or "",
            # ⑦で書いた備考。全SKU共通で同じものを入れる
            "note": (row.master_note or "").strip(),
            "delivery_note": (row.delivery_note or "").strip(),
            "exists": bool(exist),
            "exists_name": exist.name if exist else "",
        })
    if not out:
        warnings.append("SKUがまだ決まっていません。先にSKUを採番してください")
    return {"rows": out, "url_choices": urls, "components": components,
            "warnings": warnings,
            "variation_theme": row.variation_theme or "",
            "parent_sku": row.parent_sku or ""}


@router.get("/{listing_id:int}/master-preview")
def master_preview(listing_id: int, db: Session = Depends(get_db)):
    """商品マスタに何を作るかを先に見せる。書き込みはしない。"""
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "見つかりません")
    src = _src_of(db, row.research_id)
    if src is None:
        raise HTTPException(404, "元のリサーチがシートにありません")
    return _master_rows(db, row, src)


class MasterRowIn(BaseModel):
    sku: str
    name: str = ""
    color: str = ""
    size: str = ""
    spec: str = ""
    buy_url: str = ""
    price: Optional[float] = None
    set_size: int = 1
    selling_price: Optional[float] = None
    cost_jpy: Optional[float] = None
    fba_fee: Optional[float] = None
    asin: str = ""
    note: str = ""
    delivery_note: str = ""


class ToMasterIn(BaseModel):
    # 確認画面で直したあとの最終形をそのまま受ける
    rows: list[MasterRowIn]
    components: list[dict] = []


@router.post("/{listing_id:int}/to-master")
def to_master(listing_id: int, body: ToMasterIn, db: Session = Depends(get_db)):
    """商品マスタに作る。既にあるSKUは、空いている欄だけ埋める。

    手で直した値を消さないため、上書きはしない。
    Amazonの親は在庫を持たないダミーなので作らない（子SKUだけ）。
    """
    row = db.get(AmazonListing, listing_id)
    if not row:
        raise HTTPException(404, "見つかりません")
    if not body.rows:
        raise HTTPException(400, "登録するSKUがありません")

    comps = [c for c in (body.components or []) if (c or {}).get("buy_url")]
    comp_json = json.dumps(comps, ensure_ascii=False) if comps else None

    created, updated = [], []
    for r in body.rows:
        sku = (r.sku or "").strip()
        if not sku:
            continue
        p = db.query(Product).filter(Product.sku == sku).first()
        new = p is None
        if new:
            p = Product(sku=sku, supplier="タオタロウ")
            db.add(p)

        def put(field, value):
            if value in (None, "", 0):
                return
            if not getattr(p, field, None):
                setattr(p, field, value)

        put("name", (r.name or "").strip())
        put("color", r.color)
        put("size", r.size)
        put("spec", r.spec)
        put("buy_url", (r.buy_url or "").strip())
        put("price", r.price)
        put("selling_price", r.selling_price)
        put("cost_jpy", r.cost_jpy)
        put("fba_fee", r.fba_fee)
        put("note", (r.note or "").strip())
        put("delivery_note", (r.delivery_note or "").strip())
        if r.asin:
            put("asin", r.asin)
            put("amazon_url", f"https://www.amazon.co.jp/dp/{r.asin}")
        if (r.set_size or 1) > 1 and (p.set_size or 1) <= 1:
            p.set_size = r.set_size
        if comp_json and not p.purchase_components:
            p.purchase_components = comp_json
        (created if new else updated).append(sku)

    # 付属品も、SKUが決まっていれば商品マスタに部材として作る。
    # 作っておかないと、商品マスタの付属品欄（マスタから選ぶ作り）で
    # 選べず、毎回あちらで手当てすることになる。
    # 在庫には連動しない（purchase_components は在庫計算に入らない）
    parts = []
    for c in comps:
        csku = (c.get("sku") or "").strip()
        if not csku:
            continue
        cp = db.query(Product).filter(Product.sku == csku).first()
        if cp is None:
            max_no = db.query(sa_func.max(Product.no)).scalar() or 0
            cp = Product(sku=csku, no=max_no + 1, supplier="タオタロウ",
                         is_component=True)
            db.add(cp)
            parts.append(csku)
        if not (cp.name or "").strip():
            cp.name = (c.get("name") or csku)[:500]
        if not (cp.spec or "").strip():
            cp.spec = c.get("supplier_spec") or ""
        if not (cp.buy_url or "").strip():
            cp.buy_url = c.get("buy_url") or ""
        if not cp.price and c.get("price"):
            cp.price = c["price"]
        cp.is_component = True

    db.commit()
    return {"created": created, "updated": updated,
            "components": len(comps), "parts": parts}
