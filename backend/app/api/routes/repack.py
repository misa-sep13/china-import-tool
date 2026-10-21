"""代行会社へ渡す再梱包指示書。

採用した商品を、代行会社が日本向けにどう詰め直すか。

リサーチシートの中に欄を作っていたが、シートは1枚のJSONを丸ごと
読み書きするため、指示を1文字直すだけでシート全体の保存が走る。
採用したあとの作業の話で、リサーチそのものとは別物なので、
表を分けて単独の画面にした。

代行会社にはシートもこの画面も見せない。原価・競合・売価が
全部見えてしまうため、渡してよい項目だけを読み取り専用の口から出す。
"""
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.amazon_research import AmazonResearchSettings, AmazonResearchSheet
from app.models.amazon_listing import AmazonListing, AmazonListingChild
from app.models.repack_instruction import RepackInstruction
from app.services import amazon_listing_sync as sync

router = APIRouter(prefix="/repack", tags=["repack"])


def _settings(db: Session) -> AmazonResearchSettings:
    st = db.query(AmazonResearchSettings).first()
    if st is None:
        st = AmazonResearchSettings()
        db.add(st)
        db.flush()
    return st


def _sheet(db: Session, workspace: str = "default") -> dict:
    import json
    row = (db.query(AmazonResearchSheet)
           .filter(AmazonResearchSheet.workspace == workspace).first())
    if row is None or not row.data:
        return {}
    try:
        return json.loads(row.data)
    except (ValueError, TypeError):
        return {}


def _skus_by_research(db: Session) -> dict:
    """SKUとJANは出品側に持っている。現物と伝票を突き合わせるのに要る。

    1件ずつ引くと商品数ぶん問い合わせることになるので、まとめて集める。
    """
    out = {}
    rows = (db.query(AmazonListing.research_id, AmazonListingChild.sku,
                     AmazonListingChild.jan, AmazonListingChild.axis1)
            .join(AmazonListingChild,
                  AmazonListingChild.listing_id == AmazonListing.id)
            .order_by(AmazonListingChild.sort_order).all())
    for rid, sku, jan, axis1 in rows:
        out.setdefault(rid, []).append(
            {"name": (axis1 or "").strip(), "sku": (sku or "").strip(),
             "jan": (jan or "").strip()})
    return out


def _items(db: Session, only_written: bool = False) -> list:
    """採用した商品の一覧。再梱包に要るものだけを返す。

    粗利率・販売個数・競合は出さない。詰め直す人には要らないうえ、
    代行会社の画面にも同じ形で出すため、最初から持たない。
    """
    cands = sync.candidates(_sheet(db))
    notes = {n.research_id: n for n in db.query(RepackInstruction).all()}
    kids = _skus_by_research(db)

    out = []
    for c in cands:
        rid = c["research_id"]
        n = notes.get(rid)
        note = (n.note or "").strip() if n else ""
        box = (n.box_note or "").strip() if n else ""
        if only_written and not (note or box):
            continue
        ch = kids.get(rid) or []
        if not ch:
            # まだ出品側を作っていないものは、シートの子の名前だけ出す
            ch = [{"name": (k.get("axis1") or "").strip(), "sku": "", "jan": ""}
                  for k in (c.get("children") or [])]
        out.append({
            "research_id": rid,
            "name": c.get("title") or c.get("research_title") or "",
            "research_title": c.get("research_title") or "",
            "image": c.get("rival_image") or "",
            "status_label": c.get("status_label") or "",
            "children": [k for k in ch if k["name"] or k["sku"]],
            "note": note,
            "box_note": box,
            "updated_at": (n.updated_at.date().isoformat()
                           if n and n.updated_at else ""),
        })
    return out


class NoteIn(BaseModel):
    note: Optional[str] = None
    box_note: Optional[str] = None


@router.get("/items")
def list_items(db: Session = Depends(get_db)):
    """画面用。採用した商品を全部出す（指示が空のものも並べる）。"""
    items = _items(db)
    return {"items": items,
            "written": len([i for i in items if i["note"] or i["box_note"]])}


@router.put("/items/{research_id}")
def save_note(research_id: str, body: NoteIn, db: Session = Depends(get_db)):
    """指示を保存する。無ければ作る。"""
    row = (db.query(RepackInstruction)
           .filter(RepackInstruction.research_id == research_id).first())
    if row is None:
        row = RepackInstruction(research_id=research_id)
        db.add(row)
    if body.note is not None:
        row.note = body.note
    if body.box_note is not None:
        row.box_note = body.box_note
    db.commit()
    return {"ok": True}


@router.get("/link")
def link(db: Session = Depends(get_db)):
    """代行会社へ渡すURLの鍵を出す。無ければその場で作る。"""
    st = _settings(db)
    if not (st.repack_token or "").strip():
        st.repack_token = secrets.token_urlsafe(24)
        db.commit()
    return {"token": st.repack_token, "count": len(_items(db, only_written=True))}


@router.post("/reset-link")
def reset_link(db: Session = Depends(get_db)):
    """鍵を作り直す。前のURLはその場で開けなくなる。"""
    st = _settings(db)
    st.repack_token = secrets.token_urlsafe(24)
    db.commit()
    return {"token": st.repack_token}


@router.get("/public/{token}")
def public(token: str, db: Session = Depends(get_db)):
    """代行会社が開く口。認証なしで読めるが、書き換えはできない。

    指示を書いたものだけを出す。書いていないものを見せても、
    何をすればよいか分からないだけなので。
    """
    st = db.query(AmazonResearchSettings).first()
    want = (st.repack_token or "").strip() if st else ""
    if not want or not secrets.compare_digest(token or "", want):
        raise HTTPException(404, "ありません")
    return {"items": _items(db, only_written=True),
            "updated_at": datetime.now(timezone.utc).isoformat()}
