"""商品キープ（被り防止）の窓口。

2人で同じ商品を見ているので、先に登録したほうが独占権を取る。
スプレッドシートでやっていたものを移した。

判定は親ASIN単位。色違い・サイズ違いも同じ商品として扱う（相乗りNG）。
URLだけで見ると、同じ商品でもリンクの形が違って別物に見えてしまうため、
ASINを取り出して突き合わせる。
"""
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.keep_claim import (KEEP_LIMIT_DAYS, KeepClaim, days_elapsed,
                                   days_left)

router = APIRouter(prefix="/keep-claims", tags=["keep-claims"])

# 枠の上限。超えても止めないが、画面で分かるように出す
KEEP_LIMIT = 7


def _asin_from(url: str) -> str:
    """URLからASINを取り出す。

    amzn.asia の短縮URLはたどらないと分からないので、その場合は空で返す
    （呼び出し側でたどる）。
    """
    u = str(url or "")
    for pat in (r"/dp/([A-Z0-9]{10})", r"/gp/product/([A-Z0-9]{10})",
                r"/ASIN/([A-Z0-9]{10})", r"[?&]asin=([A-Z0-9]{10})"):
        m = re.search(pat, u, re.I)
        if m:
            return m.group(1).upper()
    # ASINそのものを貼られた場合。小文字で書かれることもある
    m = re.fullmatch(r"\s*([A-Za-z0-9]{10})\s*", u)
    return m.group(1).upper() if m else ""


# Amazonは素っ気ないUser-Agentを弾く。ブラウザと同じものを名乗る
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _as_url(value: str) -> str:
    """入力をURLに直す。ASINだけ入れられたら商品ページのURLにする。

    そのまま保存すると、一覧のリンクを押しても開けない。
    """
    v = str(value or "").strip()
    if not v:
        return ""
    if re.fullmatch(r"[A-Za-z0-9]{10}", v) and not v.isdigit():
        return f"https://www.amazon.co.jp/dp/{v.upper()}"
    return v


def _resolve_short(url: str) -> str:
    """amzn.asia / amzn.to の短縮URLをたどって本来のURLにする。

    HEADだと404が返るので（Amazon側がHEADを受け付けない）GETでたどる。
    たどれなければ元のURLをそのまま返す（登録は通す）。
    """
    u = str(url or "").strip()
    if not re.search(r"amzn\.(asia|to)/", u):
        return u
    try:
        req = urllib.request.Request(u, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.geturl() or u
    except Exception:
        return u


def _catalog(asin: str) -> dict:
    """商品名と画像を取る。取れなくても登録は止めない。

    SP-APIのCatalog APIは権限が無く「Access to requested resource is
    denied」になるため、商品ページから拾う。ここで欲しいのは
    「どの商品か見て分かる」ことだけなので、これで足りる。
    """
    asin = (asin or "").strip().upper()
    if not asin:
        return {}
    try:
        req = urllib.request.Request(
            f"https://www.amazon.co.jp/dp/{asin}",
            headers={"User-Agent": _UA, "Accept-Language": "ja-JP,ja;q=0.9"})
        with urllib.request.urlopen(req, timeout=20) as res:
            html = res.read().decode("utf-8", "replace")
    except Exception:
        return {}

    out = {}
    # メイン画像。ページの中に大きい版のURLが入っている
    m = re.search(r'"large":"(https://m\.media-amazon\.com/images/I/[^"]+)"',
                  html)
    if not m:
        m = re.search(r'"hiRes":"(https://m\.media-amazon\.com/images/I/[^"]+)"',
                      html)
    if m:
        out["image_url"] = m.group(1)

    t = re.search(r'<span id="productTitle"[^>]*>\s*([^<]+)', html)
    if t:
        out["title"] = t.group(1).strip()[:200]
    return out


def _out(r: KeepClaim, today: date = None) -> dict:
    return {
        "id": r.id, "owner": r.owner, "url": r.url, "asin": r.asin,
        "title": r.title, "image_url": r.image_url, "status": r.status,
        "claimed_at": r.claimed_at.isoformat() if r.claimed_at else None,
        "shipped_at": str(r.shipped_at) if r.shipped_at else None,
        "supplier_url": r.supplier_url, "memo": r.memo,
        "research_id": r.research_id,
        "days_elapsed": days_elapsed(r, today),
        "days_left": days_left(r, today),
        "limit_days": KEEP_LIMIT_DAYS,
    }


def _expire_overdue(db: Session) -> int:
    """60日を過ぎたキープを期限切れにする。

    消さずに印だけ付ける。誰がいつ何を見ていたかは残しておきたい。
    """
    today = date.today()
    n = 0
    for r in db.query(KeepClaim).filter(KeepClaim.status == "keep").all():
        if days_elapsed(r, today) > KEEP_LIMIT_DAYS:
            r.status = "expired"
            n += 1
    if n:
        db.commit()
    return n


@router.get("")
def list_claims(status: Optional[str] = None,
                owner: Optional[str] = None,
                db: Session = Depends(get_db)):
    """一覧。開くたびに期限切れを反映する。"""
    _expire_overdue(db)
    q = db.query(KeepClaim)
    if status:
        q = q.filter(KeepClaim.status == status)
    if owner:
        q = q.filter(KeepClaim.owner == owner)
    # 新しく登録したものが上。あとから登録した分を探し回らずに済む
    rows = q.order_by(KeepClaim.claimed_at.desc(), KeepClaim.id.desc()).all()
    today = date.today()
    items = [_out(r, today) for r in rows]
    # キープ中を先に、その中も新しい順。終わったものは下へ送る
    keeping = [x for x in items if x["status"] == "keep"]
    others = [x for x in items if x["status"] != "keep"]

    # 枠の残り。人ごとに数える
    by_owner: dict = {}
    for x in keeping:
        by_owner[x["owner"]] = by_owner.get(x["owner"], 0) + 1

    return {
        "items": keeping + others,
        "limit": KEEP_LIMIT,
        "limit_days": KEEP_LIMIT_DAYS,
        "used": by_owner,
        "counts": {
            "keep": len(keeping),
            "shipped": len([x for x in items if x["status"] == "shipped"]),
            "expired": len([x for x in items if x["status"] == "expired"]),
        },
    }


class ClaimIn(BaseModel):
    owner: str
    url: str
    title: str = ""
    image_url: str = ""
    supplier_url: str = ""
    memo: str = ""


@router.post("/check")
def check(data: ClaimIn, db: Session = Depends(get_db)):
    """登録する前に、被っていないか調べる。

    先に取られていたら、誰がいつ取ったかを返す。
    親ASIN単位で見るので、色違いのページでも同じ商品として当たる。
    """
    _expire_overdue(db)
    url = _resolve_short(_as_url(data.url))
    asin = _asin_from(url)
    if not asin:
        return {"asin": "", "taken": False,
                "warning": "URLからASINを読み取れませんでした。"
                           "被りの判定ができないので、URLを確かめてください"}
    hit = (db.query(KeepClaim)
           .filter(KeepClaim.asin == asin,
                   KeepClaim.status.in_(["keep", "shipped"]))
           .order_by(KeepClaim.claimed_at).first())
    return {
        "asin": asin, "url": url,
        "taken": bool(hit),
        "by": _out(hit) if hit else None,
    }


@router.post("")
def create(data: ClaimIn, force: bool = False, db: Session = Depends(get_db)):
    """キープする。先に取られていたら断る（force で押し切れる）。"""
    _expire_overdue(db)
    if not data.owner.strip():
        raise HTTPException(status_code=400, detail="担当者を入れてください")
    url = _resolve_short(_as_url(data.url))
    asin = _asin_from(url)

    if asin and not force:
        hit = (db.query(KeepClaim)
               .filter(KeepClaim.asin == asin,
                       KeepClaim.status.in_(["keep", "shipped"]))
               .order_by(KeepClaim.claimed_at).first())
        if hit:
            when = hit.claimed_at.strftime("%Y/%m/%d %H:%M") if hit.claimed_at else ""
            raise HTTPException(
                status_code=409,
                detail=f"すでに {hit.owner} さんが {when} にキープしています")

    title = data.title.strip()
    image = data.image_url.strip()
    # 商品名と画像は手で入れるものではない。ASINが分かれば取ってくる
    if asin and (not title or not image):
        info = _catalog(asin)
        title = title or (info.get("title") or "")
        image = image or (info.get("image_url") or "")

    r = KeepClaim(
        owner=data.owner.strip(), url=url, asin=asin or None,
        title=title or None, image_url=image or None,
        supplier_url=data.supplier_url.strip() or None,
        memo=data.memo.strip() or None,
        status="keep",
    )
    db.add(r)
    db.commit()
    return _out(r)


class UpdateIn(BaseModel):
    owner: Optional[str] = None
    title: Optional[str] = None
    image_url: Optional[str] = None
    supplier_url: Optional[str] = None
    memo: Optional[str] = None
    status: Optional[str] = None
    shipped_at: Optional[date] = None


@router.put("/{cid:int}")
def update(cid: int, data: UpdateIn, db: Session = Depends(get_db)):
    r = db.query(KeepClaim).filter(KeepClaim.id == cid).first()
    if not r:
        raise HTTPException(status_code=404, detail="そのキープがありません")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    # 発送済みにしたら日付を入れる。枠が空くのはこのとき
    if r.status == "shipped" and not r.shipped_at:
        r.shipped_at = date.today()
    db.commit()
    return _out(r)


@router.post("/{cid:int}/ship")
def ship(cid: int, on: Optional[date] = None, db: Session = Depends(get_db)):
    """発送済みにして枠を空ける。"""
    r = db.query(KeepClaim).filter(KeepClaim.id == cid).first()
    if not r:
        raise HTTPException(status_code=404, detail="そのキープがありません")
    r.status = "shipped"
    r.shipped_at = on or date.today()
    db.commit()
    return _out(r)


@router.post("/{cid:int}/release")
def release(cid: int, db: Session = Depends(get_db)):
    """自分から手放す。相手が仕入れられるようになる。"""
    r = db.query(KeepClaim).filter(KeepClaim.id == cid).first()
    if not r:
        raise HTTPException(status_code=404, detail="そのキープがありません")
    r.status = "released"
    db.commit()
    return _out(r)


@router.delete("/{cid:int}")
def delete(cid: int, db: Session = Depends(get_db)):
    r = db.query(KeepClaim).filter(KeepClaim.id == cid).first()
    if not r:
        raise HTTPException(status_code=404, detail="そのキープがありません")
    db.delete(r)
    db.commit()
    return {"deleted": cid}

@router.post("/sync-adopted")
def sync_adopted(workspace: str = "default", owner: str = "Y",
                 db: Session = Depends(get_db)):
    """リサーチシートで採用にしたものを、キープとして取り込む。

    自分が採用した商品は、相手にも「これは押さえた」と伝わっている
    必要がある。シートを見に行って、採用以降の状態になっている枠を
    こちらへ写す。すでにあるASINは飛ばすので、何度呼んでもよい。
    """
    import json
    from app.models.amazon_research import AmazonResearchSheet
    from app.services.amazon_listing_sync import ADOPTED_STATUS

    row = (db.query(AmazonResearchSheet)
           .filter(AmazonResearchSheet.workspace == workspace).first())
    if not row or not row.data:
        return {"added": 0, "items": [], "detail": "リサーチシートが空です"}
    try:
        data = json.loads(row.data)
    except (ValueError, TypeError):
        return {"added": 0, "items": [], "detail": "リサーチシートを読めませんでした"}

    have_asin = {a for (a,) in db.query(KeepClaim.asin).all() if a}
    have_url = {u for (u,) in db.query(KeepClaim.url).all() if u}

    added = []
    for research in (data.get("researches") or []):
        if not isinstance(research, dict):
            continue
        if (research.get("status") or "") not in ADOPTED_STATUS:
            continue

        # 候補商品の1行目をライバルとして見る。シートの作りに合わせる
        rows = [x for x in (research.get("rows") or []) if isinstance(x, dict)]
        if not rows:
            continue
        first = rows[0]
        asin = (first.get("asin") or "").strip().upper()
        url = (first.get("url") or "").strip()
        if not url and asin:
            url = f"https://www.amazon.co.jp/dp/{asin}"
        if not url:
            continue
        if (asin and asin in have_asin) or url in have_url:
            continue

        title = (research.get("title") or "").strip()
        image = (first.get("image") or "").strip()
        if asin and not image:
            info = _catalog(asin)
            image = info.get("image_url") or ""
            title = title or (info.get("title") or "")

        r = KeepClaim(
            owner=owner, url=url, asin=asin or None,
            title=title or None, image_url=image or None,
            supplier_url=(first.get("buyUrl") or "").strip() or None,
            memo=(first.get("note") or "").strip() or None,
            status="keep",
            research_id=research.get("id"),
            adopted_at=datetime.now(timezone.utc),
        )
        db.add(r)
        added.append({"asin": asin, "title": title, "url": url})
        if asin:
            have_asin.add(asin)
        have_url.add(url)

    db.commit()
    return {"added": len(added), "items": added}


@router.post("/{cid:int}/fill")
def fill(cid: int, db: Session = Depends(get_db)):
    """商品名と画像を取り直す。取り込んだ古い行を埋めるため。"""
    r = db.query(KeepClaim).filter(KeepClaim.id == cid).first()
    if not r:
        raise HTTPException(status_code=404, detail="そのキープがありません")
    if not r.asin:
        raise HTTPException(status_code=400, detail="ASINが分からないので取れません")
    info = _catalog(r.asin)
    r.title = r.title or info.get("title") or None
    r.image_url = info.get("image_url") or r.image_url
    db.commit()
    return _out(r)


@router.post("/fill-missing")
def fill_missing(limit: int = 30, db: Session = Depends(get_db)):
    """画像が入っていない行をまとめて埋める。

    APIを1件ずつ叩くので、一度に扱う数は絞る。
    """
    rows = (db.query(KeepClaim)
            .filter(KeepClaim.asin.isnot(None), KeepClaim.image_url.is_(None))
            .limit(limit).all())
    filled = 0
    for r in rows:
        info = _catalog(r.asin)
        if info.get("image_url"):
            r.image_url = info["image_url"]
            filled += 1
        if not r.title and info.get("title"):
            r.title = info["title"]
    db.commit()
    return {"targets": len(rows), "filled": filled}


class ImportRow(BaseModel):
    """スプレッドシートの1行。列の並びはあちらに合わせてある。"""
    claimed_at: str = ""      # 記入日時。早い者勝ちの根拠なので、そのまま持ってくる
    owner: str = ""
    url: str = ""
    status: str = ""          # ⏳キープ中 / ✅発送済（枠解放） / ❌期限切れ（消滅）
    shipped_at: str = ""
    supplier_url: str = ""
    memo: str = ""


class ImportIn(BaseModel):
    rows: List[ImportRow]
    dry_run: bool = True


_STATUS_MAP = {
    "キープ": "keep",
    "発送": "shipped",
    "期限切れ": "expired",
    "消滅": "expired",
}


def _parse_status(text: str) -> str:
    t = str(text or "")
    for key, val in _STATUS_MAP.items():
        if key in t:
            return val
    return "keep"


def _parse_dt(text: str):
    """「2026/05/10 8:27:42」「2026/05/10」を読む。"""
    t = str(text or "").strip()
    if not t:
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


@router.post("/import")
def import_rows(body: ImportIn, db: Session = Depends(get_db)):
    """スプレッドシートから移してくる。

    既定は dry_run。何が入るかを見てから、あらためて実行する。
    同じURLがすでにあれば飛ばす（二重に入れない）。

    記入日時はあちらの値をそのまま使う。早い者勝ちの根拠なので、
    取り込んだ日時に置き換えてしまうと順番が狂う。
    """
    added, skipped, errors = [], [], []
    seen_urls = {r.url for r in db.query(KeepClaim.url).all()}

    for i, row in enumerate(body.rows):
        url = _resolve_short(_as_url(row.url))
        if not url:
            continue
        if url in seen_urls:
            skipped.append({"row": i + 1, "url": url, "reason": "すでにあります"})
            continue

        asin = _asin_from(url)
        status = _parse_status(row.status)
        claimed = _parse_dt(row.claimed_at)
        shipped = _parse_dt(row.shipped_at)

        item = {
            "owner": row.owner.strip() or "?",
            "url": url, "asin": asin or None,
            "status": status,
            "claimed_at": claimed.isoformat() if claimed else None,
            "shipped_at": str(shipped.date()) if shipped else None,
            "supplier_url": row.supplier_url.strip() or None,
            "memo": row.memo.strip() or None,
        }
        if not asin:
            item["warning"] = "ASINを読み取れませんでした（被り判定ができません）"

        if body.dry_run:
            added.append(item)
            seen_urls.add(url)
            continue

        r = KeepClaim(
            owner=item["owner"], url=url, asin=asin or None,
            status=status,
            shipped_at=shipped.date() if shipped else None,
            supplier_url=item["supplier_url"], memo=item["memo"],
        )
        db.add(r)
        db.flush()
        # server_default があるので、入れたあとに上書きする
        if claimed:
            r.claimed_at = claimed
        added.append(item)
        seen_urls.add(url)

    if not body.dry_run:
        db.commit()
        _expire_overdue(db)

    return {
        "dry_run": body.dry_run,
        "added": len(added), "skipped": len(skipped),
        "items": added, "skipped_items": skipped, "errors": errors,
    }

# 移行元のスプレッドシート。1回きりの取り込みなので、URLはここに持つ
_SHEET_CSV = ("https://docs.google.com/spreadsheets/d/"
              "1-81x0JKUzZ_RqESiEx5e0WfJRAOLnQs0QLsDxTxUmDI/"
              "gviz/tq?tqx=out:csv&gid=1776725859")


@router.post("/import-sheet")
def import_sheet(dry_run: bool = True, db: Session = Depends(get_db)):
    """スプレッドシートを読んで取り込む。移行のための1回きりの口。

    列の並びはあちらに合わせてある:
      0 記入日時 / 1 担当 / 3 URL / 5 ステータス / 6 発送日
      7 仕入先URL / 8 メモ
    """
    import csv
    import io as _io

    try:
        req = urllib.request.Request(_SHEET_CSV, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=60) as res:
            text = res.read().decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"スプレッドシートを読めませんでした（{type(e).__name__}）")

    rows = list(csv.reader(_io.StringIO(text)))
    out = []
    for r in rows[3:]:          # 3行目までは見出しと枠数
        if len(r) < 7 or not r[3].strip():
            continue
        out.append(ImportRow(
            claimed_at=r[0], owner=r[1], url=r[3], status=r[5],
            shipped_at=r[6],
            supplier_url=(r[7] if len(r) > 7 else ""),
            memo=(r[8] if len(r) > 8 else ""),
        ))
    return import_rows(ImportIn(rows=out, dry_run=dry_run), db)
