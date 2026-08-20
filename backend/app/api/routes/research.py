from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
import csv
import io
import re
from app.core.database import get_db
from app.models.research import (
    ResearchTarget, ResearchCandidate, ResearchWatchlistItem, RakutenGenre, NintSales,
)

router = APIRouter(prefix="/research", tags=["リサーチツール"])

JST = timezone(timedelta(hours=9))

# 楽天APIのitemCode（ponopono:10001898）と、商品URL上のコード（ponopono/102622）は
# 体系が違う。Nintは後者を使うので、URLから作ったキーで突き合わせる
_URL_KEY_RE = re.compile(r"item\.rakuten\.co\.jp/([^/?#]+)/([^/?#]+)")


def make_url_key(item_url: Optional[str]) -> Optional[str]:
    """商品URLから "ショップ名/商品コード" を取り出す。末尾のスラッシュや
    クエリ（?rafcid=... など）が付いていても同じキーになる。"""
    if not item_url:
        return None
    m = _URL_KEY_RE.search(item_url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


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

    # ジャンルIDを直接入力して登録した対象は表示名がIDのままになっている。
    # 一覧を返すときにジャンル名へ直す（既存の登録も対象にするため読み取り時に解決する）
    genre_ids = [int(r.value) for r in rows if r.type == "genre" and str(r.value).isdigit()]
    names = {}
    if genre_ids:
        names = {
            g.genre_id: g.name
            for g in db.query(RakutenGenre).filter(RakutenGenre.genre_id.in_(genre_ids)).all()
        }

    out = []
    for r in rows:
        d = _target_dict(r)
        if r.type == "genre" and str(r.value).isdigit() and (not r.label or r.label == r.value):
            d["label"] = names.get(int(r.value), d["label"])
        out.append(d)
    return {"targets": out}


@router.post("/targets")
def create_target(data: TargetIn, db: Session = Depends(get_db)):
    if data.type not in ("keyword", "genre", "shop"):
        raise HTTPException(400, "typeはkeyword / genre / shop のいずれかを指定してください")

    # 商品カードからワンクリックで登録できるようにしたので、同じセラーを
    # 何度も押せてしまう。同じ種類・同じ値なら既存のものを返して二重登録を防ぐ
    existing = db.query(ResearchTarget).filter(
        ResearchTarget.type == data.type,
        ResearchTarget.value == data.value,
    ).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            db.commit()
            db.refresh(existing)
        return _target_dict(existing)

    # ジャンルIDを直接入力された場合、表示名がIDのままだと後から何のジャンルか
    # 分からなくなる。取り込んだジャンル一覧から名前を補う
    label = data.label
    if data.type == "genre" and (not label or label == data.value):
        try:
            g = db.query(RakutenGenre).filter(RakutenGenre.genre_id == int(data.value)).first()
            if g:
                label = g.name
        except (ValueError, TypeError):
            pass

    t = ResearchTarget(type=data.type, value=data.value, label=label)
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

    # 洗い替える前に前回の値を控える。これが「前回から何件レビューが増えたか」の
    # 基準になる（楽天で検索すれば分かる情報だけでは判断材料にならないため）
    previous = {
        c.item_code: (c.review_count, c.fetched_at)
        for c in db.query(ResearchCandidate).filter(
            ResearchCandidate.research_target_id == data.research_target_id
        ).all()
    }

    db.query(ResearchCandidate).filter(
        ResearchCandidate.research_target_id == data.research_target_id
    ).delete()

    for item in data.items:
        prev = previous.get(item.item_code)
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
            url_key=make_url_key(item.item_url),
            prev_review_count=prev[0] if prev else None,
            prev_fetched_at=prev[1] if prev else None,
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

    # ジャンルは1対象で300件超になるため、複数対象を横断すると500件では足りない
    LIMIT = 1500

    if sort in ("review_delta", "review_delta_rate"):
        # 増加数・増加率はDB上に列が無い（毎回引き算する）ので、
        # SQLでソートせずPython側で並べ替える
        calc = _review_delta_rate if sort == "review_delta_rate" else _review_delta
        rows = q.limit(LIMIT).all()
        # 未計測（初回取得や母数不足）は数字がある商品より後ろに置く
        rows.sort(key=lambda c: (calc(c) is not None, calc(c) if calc(c) is not None else 0),
                  reverse=(order == "desc"))
    else:
        sort_col = {
            "review_count": ResearchCandidate.review_count,
            "price": ResearchCandidate.item_price,
            "review_average": ResearchCandidate.review_average,
            "rank": ResearchCandidate.rank,
        }.get(sort, ResearchCandidate.review_count)
        q = q.order_by(sort_col.desc() if order == "desc" else sort_col.asc())
        rows = q.limit(LIMIT).all()

    picked_codes = {
        r[0] for r in db.query(ResearchWatchlistItem.item_code).all()
    }

    nint = build_nint_map(db, [r.url_key for r in rows])

    # Nint由来の並べ替えは、値がDBの列に無いのでPython側で行う
    if sort in ("nint_units", "nint_growth"):
        field = "units" if sort == "nint_units" else "growth_rate"

        def nint_val(c):
            v = (nint.get(c.url_key) or {}).get(field)
            return v if v is not None else None

        rows.sort(key=lambda c: (nint_val(c) is not None, nint_val(c) or 0),
                  reverse=(order == "desc"))

    return {
        "candidates": [
            _candidate_dict(r, picked=r.item_code in picked_codes, nint=nint.get(r.url_key))
            for r in rows
        ],
        # 上限で切れたまま黙って表示すると「全部見た」と誤解するので伝える
        "truncated": len(rows) >= LIMIT,
        "limit": LIMIT,
    }


# ---------- Nintの売上CSV取り込み ----------

# "202604売上指数" / "202604販売個数（個）" のような列名から年月を拾う
_NINT_AMOUNT_RE = re.compile(r"^(\d{6})売上指数")
_NINT_UNITS_RE = re.compile(r"^(\d{6})販売個数")


@router.post("/nint/import")
async def import_nint_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """NintのCSV書き出しを取り込む。

    楽天APIは販売数を返さないので、売上はNintの提供機能で書き出したCSVから取る。
    月の列は書き出した期間によって変わるため、列名のパターンから拾う。
    商品詳細（1行）でも商品一覧（複数行）でも同じ形式なのでどちらも通る。
    """
    raw = await file.read()
    text = None
    # Excel経由だとShift_JISで保存されることがあるので順に試す
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(400, "CSVの文字コードを判別できませんでした")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "CSVの見出し行が読み取れませんでした")

    months = {}   # 年月 -> {"amount": 列名, "units": 列名}
    for col in reader.fieldnames:
        col = (col or "").strip()
        m = _NINT_AMOUNT_RE.match(col)
        if m:
            months.setdefault(m.group(1), {})["amount"] = col
            continue
        m = _NINT_UNITS_RE.match(col)
        if m:
            months.setdefault(m.group(1), {})["units"] = col

    if not months:
        raise HTTPException(400, "売上指数・販売個数の列が見つかりません。Nintの書き出しCSVか確認してください")

    def to_int(v):
        v = (v or "").strip().replace(",", "")
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return None

    imported_items = 0
    imported_rows = 0
    skipped = []

    for row in reader:
        item_url = (row.get("url") or "").strip()
        url_key = make_url_key(item_url)
        if not url_key:
            name = (row.get("商品名") or "")[:30]
            skipped.append(name or "(商品名なし)")
            continue

        item_name = (row.get("商品名") or "").strip()
        shop_name = (row.get("ショップ名") or "").strip()
        image_url = (row.get("画像URL") or "").strip()

        # 同じ商品を入れ直したときに重複しないよう、一度消してから入れる
        db.query(NintSales).filter(NintSales.url_key == url_key).delete()

        for ym, cols in months.items():
            amount = to_int(row.get(cols.get("amount", ""))) if cols.get("amount") else None
            units = to_int(row.get(cols.get("units", ""))) if cols.get("units") else None
            if amount is None and units is None:
                continue
            db.add(NintSales(
                url_key=url_key,
                ym=ym,
                sales_amount=amount,
                units=units,
                item_name=item_name,
                shop_name=shop_name,
                item_url=item_url,
                image_url=image_url,
            ))
            imported_rows += 1
        imported_items += 1

    db.commit()
    return {
        "imported_items": imported_items,
        "imported_months": imported_rows,
        "months": sorted(months.keys()),
        "skipped": skipped[:10],
    }


class NintMonth(BaseModel):
    ym: str
    sales_amount: Optional[int] = None
    units: Optional[int] = None


class NintCaptureItem(BaseModel):
    url_key: Optional[str] = None
    item_url: Optional[str] = None
    item_name: Optional[str] = None
    shop_name: Optional[str] = None
    image_url: Optional[str] = None
    months: list[NintMonth] = []


class NintCaptureIn(BaseModel):
    items: list[NintCaptureItem]


@router.post("/nint/capture")
def capture_nint(data: NintCaptureIn, db: Session = Depends(get_db)):
    """拡張機能が、利用者が開いているNintの画面から読み取った内容を受け取る。

    Nintへのアクセスを増やさないため、拡張機能はページが既に取得済みの
    データを見るだけで、自分から追加のリクエストは出さない。
    一覧画面を開けばその画面分がまとめて入るので、1商品ずつにはならない。
    """
    saved, skipped = 0, 0
    for item in data.items:
        url_key = item.url_key or make_url_key(item.item_url)
        if not url_key or not item.months:
            skipped += 1
            continue

        db.query(NintSales).filter(NintSales.url_key == url_key).delete()
        for m in item.months:
            if m.sales_amount is None and m.units is None:
                continue
            db.add(NintSales(
                url_key=url_key,
                ym=m.ym,
                sales_amount=m.sales_amount,
                units=m.units,
                item_name=item.item_name,
                shop_name=item.shop_name,
                item_url=item.item_url,
                image_url=item.image_url,
            ))
        saved += 1

    db.commit()
    return {"saved": saved, "skipped": skipped}


@router.get("/nint/summary")
def nint_summary(db: Session = Depends(get_db)):
    """取り込み済みNintデータの概要。画面で状況を出すために使う。"""
    total = db.query(NintSales.url_key).distinct().count()
    latest = db.query(NintSales.ym).order_by(NintSales.ym.desc()).first()
    return {"items": total, "latest_month": latest[0] if latest else None}


# ---------- ジャンル一覧（画面からジャンルIDを選ぶため） ----------

class GenreItem(BaseModel):
    genre_id: int
    name: str
    level: int
    parent_id: Optional[int] = None
    path: Optional[str] = None


class GenreBulkIn(BaseModel):
    genres: list[GenreItem]


@router.post("/genres/bulk")
def bulk_import_genres(data: GenreBulkIn, db: Session = Depends(get_db)):
    """ローカルバッチ用。ジャンル階層を丸ごと入れ替える。"""
    db.query(RakutenGenre).delete()
    for g in data.genres:
        db.add(RakutenGenre(
            genre_id=g.genre_id,
            name=g.name,
            level=g.level,
            parent_id=g.parent_id,
            path=g.path,
        ))
    db.commit()
    return {"imported": len(data.genres)}


@router.get("/genres")
def list_genres(
    parent_id: Optional[int] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """keyword指定なら名前で横断検索、なければparent_id直下の子を返す
    （未指定なら最上位）。画面での絞り込みと階層辿りの両方に使う。"""
    q = db.query(RakutenGenre)
    if keyword:
        q = q.filter(RakutenGenre.name.ilike(f"%{keyword}%"))
        rows = q.order_by(RakutenGenre.level, RakutenGenre.name).limit(200).all()
    else:
        q = q.filter(RakutenGenre.parent_id == parent_id) if parent_id \
            else q.filter(RakutenGenre.level == 1)
        rows = q.order_by(RakutenGenre.name).all()

    return {
        "genres": [
            {
                "genre_id": g.genre_id,
                "name": g.name,
                "level": g.level,
                "parent_id": g.parent_id,
                "path": g.path,
            }
            for g in rows
        ],
        "total": db.query(RakutenGenre).count(),
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
        url_key=make_url_key(data.item_url),
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
    nint = build_nint_map(db, [r.url_key for r in rows])
    return {"items": [_watchlist_dict(r, nint=nint.get(r.url_key)) for r in rows]}


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


def build_nint_map(db: Session, url_keys: list) -> dict:
    """url_keyごとに、直近月の売上・販売個数と、少し前と比べた伸びをまとめる。

    Nintは14ヶ月分の履歴を一度に書き出せるので、レビューのように
    数十日待たなくても、取り込んだ時点で伸びが分かる。
    """
    keys = [k for k in url_keys if k]
    if not keys:
        return {}

    rows = db.query(NintSales).filter(NintSales.url_key.in_(keys)).all()

    by_key = {}
    for r in rows:
        by_key.setdefault(r.url_key, []).append(r)

    out = {}
    for key, items in by_key.items():
        items.sort(key=lambda x: x.ym)          # 年月の昇順
        latest = items[-1]
        # 3ヶ月前と比べる。単月は変動が大きく、伸びているかの判断に使いにくい
        base = items[-4] if len(items) >= 4 else items[0]

        growth = None
        if base.units and latest.units is not None and base is not latest:
            growth = round((latest.units - base.units) / base.units * 100, 1)

        out[key] = {
            "latest_month": latest.ym,
            "units": latest.units,
            "sales_amount": latest.sales_amount,
            "growth_rate": growth,
            "base_month": base.ym if base is not latest else None,
            "history": [
                {"ym": i.ym, "units": i.units, "sales_amount": i.sales_amount}
                for i in items
            ],
        }
    return out


def _review_delta(c: ResearchCandidate):
    """前回バッチからのレビュー増加数。前回のデータが無ければNone（初回取得）。"""
    if c.prev_review_count is None:
        return None
    return (c.review_count or 0) - c.prev_review_count


# 母数が小さいと伸び率が跳ねる（1件→3件で+200%）。ノイズになるので、
# ある程度レビューが付いている商品だけ伸び率を出す
MIN_BASE_FOR_RATE = 5


def _review_delta_rate(c: ResearchCandidate):
    """前回バッチからのレビュー増加率。増加数だけだと大手の定番商品が
    常に上位に来てしまい、伸びている新商品が埋もれるため併せて出す。"""
    prev = c.prev_review_count
    if prev is None or prev < MIN_BASE_FOR_RATE:
        return None
    delta = (c.review_count or 0) - prev
    return round(delta / prev * 100, 1)


def _candidate_dict(c: ResearchCandidate, picked: bool = False, nint: dict = None) -> dict:
    return {
        "id": c.id,
        "url_key": c.url_key,
        "nint": nint,
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
        "review_delta": _review_delta(c),
        "review_delta_rate": _review_delta_rate(c),
        "prev_review_count": c.prev_review_count,
        "prev_fetched_at": c.prev_fetched_at.isoformat() if c.prev_fetched_at else None,
        "picked": picked,
    }


def _watchlist_dict(w: ResearchWatchlistItem, nint: dict = None) -> dict:
    return {
        "id": w.id,
        "url_key": w.url_key,
        "nint": nint,
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
