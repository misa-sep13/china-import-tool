"""Amazon競合リサーチ。

1商品1行で候補を並べ、リサーチ段階で手に入る情報だけから原価と粗利率を出す。
計算式は app/services/amazon_research_calc.py にまとめてある（画面ごとに
計算がずれないよう、原価はサーバー側で出して保存する）。
"""
import json
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.amazon_research import (
    AmazonResearch, AmazonResearchItem, AmazonResearchSettings,
    AmazonResearchSheet, AmazonResearchSheetBackup,
)
from app.services import amazon_research_calc as calc

router = APIRouter(prefix="/amazon-research", tags=["amazon-research"])


@router.get("/asin")
def research_asin(asin: str, price: Optional[float] = None):
    """リサーチシートの1行ぶんをSP-APIから取る。

    以前は手元の中継サーバー(127.0.0.1:8765)が担っていたが、入れた人しか
    使えず実際には誰も動かしていなかった。SP-APIは正規のAPIなので
    サーバーから叩ける。ここに寄せて、外注さんの画面でも埋まるようにする。
    """
    from app.services import amazon_api
    return amazon_api.fetch_research_asin(asin, price)


# ---------- 設定 ----------

class SettingsIn(BaseModel):
    exchange_rate: Optional[float] = None
    rate_adjust: Optional[float] = None
    china_fixed: Optional[float] = None
    tariff_rate: Optional[float] = None
    pack_factor: Optional[int] = None
    ship_yuan: Optional[float] = None
    ship_mode: Optional[str] = None
    customs_fee_jpy: Optional[float] = None


def _get_settings(db: Session) -> AmazonResearchSettings:
    row = db.query(AmazonResearchSettings).first()
    if row is None:
        # 初期値はタオタロウの実測（もらったツールはラクマート実績だった）
        row = AmazonResearchSettings(
            id=1, exchange_rate=None, rate_adjust=6, china_fixed=0.50,
            tariff_rate=15.4, pack_factor=100, ship_yuan=7.0,
            ship_mode="sea", customs_fee_jpy=2000,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _settings_out(s: AmazonResearchSettings) -> dict:
    return {
        "exchange_rate": s.exchange_rate,
        "rate_adjust": s.rate_adjust,
        "china_fixed": s.china_fixed,
        "tariff_rate": s.tariff_rate,
        "pack_factor": s.pack_factor,
        "ship_yuan": s.ship_yuan,
        "ship_mode": s.ship_mode,
        "customs_fee_jpy": s.customs_fee_jpy,
        "settle_rate": round(calc.settle_rate(s), 4) if s.exchange_rate else None,
        "rate_updated_at": s.rate_updated_at.isoformat() if s.rate_updated_at else None,
    }


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    return _settings_out(_get_settings(db))


@router.put("/settings")
def update_settings(data: SettingsIn, db: Session = Depends(get_db)):
    s = _get_settings(db)
    for f in ("exchange_rate", "rate_adjust", "china_fixed", "tariff_rate",
              "pack_factor", "ship_yuan", "ship_mode", "customs_fee_jpy"):
        v = getattr(data, f, None)
        if v is not None:
            setattr(s, f, v)
    if data.exchange_rate is not None:
        s.rate_updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    # 前提が変わると全行の原価が変わるので、まとめて計算し直す
    _recalc_all(db, s)
    return _settings_out(s)


# ---------- リサーチ ----------

class ResearchIn(BaseModel):
    name: Optional[str] = None
    note: Optional[str] = None
    is_archived: Optional[bool] = None


@router.get("/researches")
def list_researches(include_archived: bool = False, db: Session = Depends(get_db)):
    q = db.query(AmazonResearch)
    if not include_archived:
        q = q.filter(AmazonResearch.is_archived == False)
    rows = q.order_by(AmazonResearch.id.desc()).all()
    counts = {}
    for r in db.query(AmazonResearchItem).all():
        counts[r.research_id] = counts.get(r.research_id, 0) + 1
    return {"researches": [{
        "id": r.id, "name": r.name, "note": r.note,
        "is_archived": r.is_archived, "item_count": counts.get(r.id, 0),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}


@router.post("/researches")
def create_research(data: ResearchIn, db: Session = Depends(get_db)):
    if not (data.name or "").strip():
        raise HTTPException(400, "リサーチ名を入れてください")
    row = AmazonResearch(name=data.name.strip(), note=data.note or "")
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "note": row.note, "item_count": 0}


@router.patch("/researches/{research_id:int}")
def update_research(research_id: int, data: ResearchIn, db: Session = Depends(get_db)):
    row = db.query(AmazonResearch).filter(AmazonResearch.id == research_id).first()
    if not row:
        raise HTTPException(404, "リサーチが見つかりません")
    for f in ("name", "note", "is_archived"):
        v = getattr(data, f, None)
        if v is not None:
            setattr(row, f, v)
    db.commit()
    return {"id": row.id, "name": row.name, "is_archived": row.is_archived}


@router.delete("/researches/{research_id:int}")
def delete_research(research_id: int, db: Session = Depends(get_db)):
    row = db.query(AmazonResearch).filter(AmazonResearch.id == research_id).first()
    if not row:
        raise HTTPException(404, "リサーチが見つかりません")
    db.query(AmazonResearchItem).filter(
        AmazonResearchItem.research_id == research_id).delete()
    db.delete(row)
    db.commit()
    return {"deleted": research_id}


# ---------- 候補商品 ----------

class ItemIn(BaseModel):
    research_id: Optional[int] = None
    sort_order: Optional[int] = None
    asin: Optional[str] = None
    image_url: Optional[str] = None
    competitor_name: Optional[str] = None
    monthly_sales: Optional[int] = None
    review_count: Optional[int] = None
    review_rate: Optional[float] = None
    winning_factors: Optional[list] = None
    note: Optional[str] = None
    len_a: Optional[float] = None
    len_b: Optional[float] = None
    len_c: Optional[float] = None
    weight: Optional[float] = None
    size_type: Optional[str] = None
    price: Optional[float] = None
    fulfill: Optional[str] = None
    fee: Optional[float] = None
    seller_count: Optional[int] = None
    spec: Optional[str] = None
    rank_text: Optional[str] = None
    urls_1688: Optional[list] = None
    parts: Optional[list] = None
    options: Optional[list] = None
    pack_factor: Optional[int] = None
    status: Optional[str] = None


_JSON_FIELDS = ("winning_factors", "urls_1688", "parts", "options")


def _item_out(r: AmazonResearchItem, c: dict | None = None) -> dict:
    def jload(v):
        if not v:
            return []
        try:
            d = json.loads(v)
            return d if isinstance(d, list) else []
        except (ValueError, TypeError):
            return []

    d = {
        "id": r.id, "research_id": r.research_id, "sort_order": r.sort_order,
        "asin": r.asin, "image_url": r.image_url,
        "competitor_name": r.competitor_name,
        "monthly_sales": r.monthly_sales, "review_count": r.review_count,
        "review_rate": r.review_rate,
        "winning_factors": jload(r.winning_factors), "note": r.note,
        "len_a": r.len_a, "len_b": r.len_b, "len_c": r.len_c, "weight": r.weight,
        "size_type": r.size_type, "price": r.price, "fulfill": r.fulfill,
        "fee": r.fee, "seller_count": r.seller_count,
        "spec": r.spec, "rank_text": r.rank_text,
        "urls_1688": jload(r.urls_1688), "parts": jload(r.parts),
        "options": jload(r.options), "pack_factor": r.pack_factor,
        "status": r.status,
    }
    if c:
        d.update({
            "billable_kg": c["billable_kg"], "vol_kg": c["vol_kg"],
            "tier": c["tier"], "tier_label": c["tier_label"],
            "missing": c["missing"], "warns": c["warns"],
            "china_jpy": c["china_jpy"], "ship_jpy": c["ship_jpy"],
            "cost_jpy": c["cost_jpy"], "profit_jpy": c["profit_jpy"],
            "profit_rate": c["profit_rate"], "ship_share": c["ship_share"],
        })
    return d


def _apply(row: AmazonResearchItem, data: ItemIn):
    for f, v in data.model_dump(exclude_unset=True).items():
        if v is None:
            continue
        if f in _JSON_FIELDS:
            setattr(row, f, json.dumps(v, ensure_ascii=False))
        else:
            setattr(row, f, v)


def _save_calc(row: AmazonResearchItem, c: dict):
    """計算結果を行にも保存する。並べ替えや絞り込みに使うため"""
    row.billable_kg = c["billable_kg"]
    row.china_jpy = c["china_jpy"]
    row.ship_jpy = c["ship_jpy"]
    row.cost_jpy = c["cost_jpy"]
    row.profit_jpy = c["profit_jpy"]
    row.profit_rate = c["profit_rate"]


def _recalc_all(db: Session, s: AmazonResearchSettings):
    for row in db.query(AmazonResearchItem).all():
        _save_calc(row, calc.compute(row, s))
    db.commit()


@router.get("/items")
def list_items(
    research_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    s = _get_settings(db)
    q = db.query(AmazonResearchItem)
    if research_id:
        q = q.filter(AmazonResearchItem.research_id == research_id)
    if status:
        q = q.filter(AmazonResearchItem.status == status)
    rows = q.all()
    rows.sort(key=lambda r: (r.sort_order or 0, r.id))
    items = [_item_out(r, calc.compute(r, s)) for r in rows]
    return {"items": items, "settings": _settings_out(s)}


@router.post("/items")
def create_item(data: ItemIn, db: Session = Depends(get_db)):
    if not data.research_id:
        raise HTTPException(400, "リサーチを選んでください")
    s = _get_settings(db)
    n = db.query(AmazonResearchItem).filter(
        AmazonResearchItem.research_id == data.research_id).count()
    row = AmazonResearchItem(research_id=data.research_id, sort_order=n,
                             status="researching")
    _apply(row, data)
    c = calc.compute(row, s)
    _save_calc(row, c)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _item_out(row, calc.compute(row, s))


@router.patch("/items/{item_id:int}")
def update_item(item_id: int, data: ItemIn, db: Session = Depends(get_db)):
    row = db.query(AmazonResearchItem).filter(AmazonResearchItem.id == item_id).first()
    if not row:
        raise HTTPException(404, "候補商品が見つかりません")
    s = _get_settings(db)
    # 空文字での消去も受けたいので、明示的に送られた項目はそのまま入れる
    for f, v in data.model_dump(exclude_unset=True).items():
        if f in _JSON_FIELDS:
            setattr(row, f, json.dumps(v or [], ensure_ascii=False))
        else:
            setattr(row, f, v)
    c = calc.compute(row, s)
    _save_calc(row, c)
    db.commit()
    db.refresh(row)
    return _item_out(row, calc.compute(row, s))


@router.delete("/items/{item_id:int}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    row = db.query(AmazonResearchItem).filter(AmazonResearchItem.id == item_id).first()
    if not row:
        raise HTTPException(404, "候補商品が見つかりません")
    db.delete(row)
    db.commit()
    return {"deleted": item_id}


@router.post("/items/bulk")
def bulk_create_items(data: List[ItemIn], db: Session = Depends(get_db)):
    """セラースカウトなどから複数まとめて入れる。

    同じリサーチに同じASINが既にあれば、行を増やさず空欄だけ埋める
    （手入力を上書きしないため）。
    """
    s = _get_settings(db)
    created = updated = 0
    for d in data:
        if not d.research_id:
            continue
        asin = (d.asin or "").strip()
        row = None
        if asin:
            row = db.query(AmazonResearchItem).filter(
                AmazonResearchItem.research_id == d.research_id,
                AmazonResearchItem.asin == asin).first()
        if row is None:
            n = db.query(AmazonResearchItem).filter(
                AmazonResearchItem.research_id == d.research_id).count()
            row = AmazonResearchItem(research_id=d.research_id, sort_order=n,
                                     status="researching")
            db.add(row)
            created += 1
            _apply(row, d)
        else:
            # 既にある行は空欄だけ埋める
            for f, v in d.model_dump(exclude_unset=True).items():
                if v is None or f in ("research_id", "sort_order"):
                    continue
                cur = getattr(row, f, None)
                if cur in (None, "", 0) or (f in _JSON_FIELDS and not cur):
                    if f in _JSON_FIELDS:
                        setattr(row, f, json.dumps(v, ensure_ascii=False))
                    else:
                        setattr(row, f, v)
            updated += 1
        _save_calc(row, calc.compute(row, s))
    db.commit()
    return {"created": created, "updated": updated}


# ============================================================
# 競合リサーチシート（HTML版）の保存先
#
# もらったHTMLは1枚で完結していて、状態を丸ごとJSONで持っている。
# そのHTMLをそのまま埋め込み、保存先だけ localStorage からここへ差し替える。
# ブラウザの5MB制限を受けず、別のPCからも同じシートが見える。
# ============================================================

_BACKUP_KEEP = 60          # 残す世代の数
_BACKUP_INTERVAL_SEC = 600 # この間隔を空けて世代を作る（保存のたびだと増えすぎる）


class SheetIn(BaseModel):
    data: dict | list | None = None
    workspace: Optional[str] = None


@router.get("/sheet")
def get_sheet(workspace: str = "default", db: Session = Depends(get_db)):
    row = db.query(AmazonResearchSheet).filter(
        AmazonResearchSheet.workspace == workspace).first()
    if row is None or not row.data:
        return {"data": None, "updated_at": None, "size_bytes": 0}
    try:
        data = json.loads(row.data)
    except (ValueError, TypeError):
        data = None
    return {
        "data": data,
        "size_bytes": row.size_bytes or 0,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.put("/sheet")
def put_sheet(body: SheetIn, workspace: str = "default", db: Session = Depends(get_db)):
    """シート全体を保存する。丸ごと上書きなので、間隔を空けて世代も残す。"""
    if body.data is None:
        raise HTTPException(400, "データがありません")
    ws = (body.workspace or workspace or "default").strip() or "default"
    raw = json.dumps(body.data, ensure_ascii=False)

    row = db.query(AmazonResearchSheet).filter(
        AmazonResearchSheet.workspace == ws).first()
    if row is None:
        row = AmazonResearchSheet(workspace=ws)
        db.add(row)

    # 前回の世代から間隔が空いていれば、上書き前の中身を控える
    now = datetime.now(timezone.utc)
    last = (db.query(AmazonResearchSheetBackup)
            .filter(AmazonResearchSheetBackup.workspace == ws)
            .order_by(AmazonResearchSheetBackup.created_at.desc())
            .first())
    should_backup = row.data and (
        last is None
        or last.created_at is None
        or (now - last.created_at).total_seconds() >= _BACKUP_INTERVAL_SEC
    )
    if should_backup:
        db.add(AmazonResearchSheetBackup(
            workspace=ws, data=row.data, size_bytes=row.size_bytes or 0))
        # 古い世代を落とす
        olds = (db.query(AmazonResearchSheetBackup)
                .filter(AmazonResearchSheetBackup.workspace == ws)
                .order_by(AmazonResearchSheetBackup.created_at.desc())
                .offset(_BACKUP_KEEP).all())
        for o in olds:
            db.delete(o)

    row.data = raw
    row.size_bytes = len(raw.encode("utf-8"))
    db.commit()
    db.refresh(row)
    return {
        "saved": True,
        "size_bytes": row.size_bytes,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/sheet/backups")
def list_sheet_backups(workspace: str = "default", db: Session = Depends(get_db)):
    rows = (db.query(AmazonResearchSheetBackup)
            .filter(AmazonResearchSheetBackup.workspace == workspace)
            .order_by(AmazonResearchSheetBackup.created_at.desc())
            .limit(_BACKUP_KEEP).all())
    return {"backups": [{
        "id": r.id,
        "size_bytes": r.size_bytes or 0,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}


@router.get("/sheet/backups/{backup_id:int}")
def get_sheet_backup(backup_id: int, db: Session = Depends(get_db)):
    row = db.query(AmazonResearchSheetBackup).filter(
        AmazonResearchSheetBackup.id == backup_id).first()
    if not row:
        raise HTTPException(404, "控えが見つかりません")
    try:
        data = json.loads(row.data)
    except (ValueError, TypeError):
        raise HTTPException(500, "控えを読めませんでした")
    return {"data": data,
            "created_at": row.created_at.isoformat() if row.created_at else None}
