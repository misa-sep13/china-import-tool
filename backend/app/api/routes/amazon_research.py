"""Amazon競合リサーチ。

1商品1行で候補を並べ、リサーチ段階で手に入る情報だけから原価と粗利率を出す。
計算式は app/services/amazon_research_calc.py にまとめてある（画面ごとに
計算がずれないよう、原価はサーバー側で出して保存する）。
"""
import json
import urllib.parse
import os
import re
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.amazon_research import (
    AmazonResearch, AmazonResearchItem, AmazonResearchSettings,
    AmazonResearchSheet, AmazonResearchSheetBackup, JanCode,
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
    gs1_prefix: Optional[str] = None
    brand_name: Optional[str] = None
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
        "gs1_prefix": s.gs1_prefix,
        "brand_name": s.brand_name,
    }


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    return _settings_out(_get_settings(db))


@router.put("/settings")
def update_settings(data: SettingsIn, db: Session = Depends(get_db)):
    s = _get_settings(db)
    for f in ("exchange_rate", "rate_adjust", "china_fixed", "tariff_rate",
              "pack_factor", "ship_yuan", "ship_mode", "customs_fee_jpy",
              "gs1_prefix", "brand_name"):
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


# ---------- JANコードの採番 ----------
#
# 新規出品にはJANが要る。GS1事業者コードは自社に割り当てられた固定値で、
# 後ろに商品アイテムコードを順番に付け、最後にチェックデジットを足して13桁にする。
# 同じ番号を2回使うと別商品が同一視されるので、発番したものは必ず台帳に残し、
# 取り消しても番号は再利用しない（一度Amazonへ送った可能性があるため）。


def _check_digit(body12: str) -> str:
    """JAN13のチェックデジット。奇数桁×1・偶数桁×3の合計を10の倍数に切り上げる。"""
    total = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(body12))
    return str((10 - total % 10) % 10)


def _make_jan(prefix: str, seq: int) -> str:
    room = 12 - len(prefix)          # 商品アイテムコードに使える桁数
    if room <= 0:
        raise HTTPException(400, "GS1事業者コードの桁数が正しくありません（7桁か9桁）")
    if seq >= 10 ** room:
        raise HTTPException(
            400,
            f"採番できる番号を使い切りました（{len(prefix)}桁の事業者コードでは"
            f"{10 ** room - 1}件まで）")
    body = prefix + str(seq).zfill(room)
    return body + _check_digit(body)


class JanIssueIn(BaseModel):
    sku: Optional[str] = None
    name: Optional[str] = None
    note: Optional[str] = None


def _jan_out(j: JanCode):
    return {"id": j.id, "code": j.code, "item_seq": j.item_seq, "sku": j.sku,
            "asin": j.asin, "name": j.name, "status": j.status, "note": j.note,
            "created_at": j.created_at.isoformat() if j.created_at else None}


@router.get("/jan")
def list_jan(status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(JanCode)
    if status:
        q = q.filter(JanCode.status == status)
    rows = q.order_by(JanCode.item_seq.desc()).limit(500).all()
    st = _get_settings(db)
    return {"rows": [_jan_out(x) for x in rows],
            "gs1_prefix": st.gs1_prefix,
            "issued": db.query(JanCode).count()}


@router.post("/jan/issue")
def issue_jan(data: JanIssueIn, db: Session = Depends(get_db)):
    """次の番号を1つ発番して台帳に残す。"""
    st = _get_settings(db)
    prefix = (st.gs1_prefix or "").strip()
    if not prefix.isdigit() or len(prefix) not in (7, 9):
        raise HTTPException(400, "先にGS1事業者コード（7桁か9桁）を設定してください")

    last = db.query(JanCode).order_by(JanCode.item_seq.desc()).first()
    seq = (last.item_seq or 0) + 1 if last else 1
    code = _make_jan(prefix, seq)
    if db.query(JanCode).filter(JanCode.code == code).first():
        raise HTTPException(409, "その番号はすでに使われています")

    row = JanCode(code=code, item_seq=seq, sku=(data.sku or None),
                  name=(data.name or None), note=(data.note or None), status="issued")
    db.add(row)
    db.commit()
    return _jan_out(row)


class JanPatchIn(BaseModel):
    sku: Optional[str] = None
    asin: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None


@router.patch("/jan/{jan_id:int}")
def update_jan(jan_id: int, data: JanPatchIn, db: Session = Depends(get_db)):
    row = db.query(JanCode).filter(JanCode.id == jan_id).first()
    if not row:
        raise HTTPException(404, "見つかりません")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    db.commit()
    return _jan_out(row)


class JanImportIn(BaseModel):
    """GS1側で採番済みの番号を台帳に取り込む。

    ツールを使う前に発番した分。ここを入れておかないと、次の採番が
    1番から始まって既存商品と衝突する。
    """
    code: str
    name: Optional[str] = None
    sku: Optional[str] = None
    asin: Optional[str] = None
    note: Optional[str] = None


@router.post("/jan/import")
def import_jan(data: JanImportIn, db: Session = Depends(get_db)):
    code = (data.code or "").strip()
    if not code.isdigit() or len(code) != 13:
        raise HTTPException(400, "JANは13桁の数字で入れてください")
    if _check_digit(code[:12]) != code[-1]:
        raise HTTPException(400, "チェックデジットが合いません。桁の写し間違いがないか確認してください")

    st = _get_settings(db)
    prefix = (st.gs1_prefix or "").strip()
    if not prefix or not code.startswith(prefix):
        raise HTTPException(400, "自社のGS1事業者コードで始まっていません")

    if db.query(JanCode).filter(JanCode.code == code).first():
        raise HTTPException(409, "その番号はすでに台帳にあります")

    row = JanCode(code=code, item_seq=int(code[len(prefix):12]),
                  name=(data.name or None), sku=(data.sku or None),
                  asin=(data.asin or None), status="used",
                  note=(data.note or "ツール導入前にGS1で採番済み"))
    db.add(row)
    db.commit()
    return _jan_out(row)


# ---------- 出品カテゴリ（商品タイプ） ----------
#
# Amazonは商品タイプごとに必須項目が違う。何を入れればよいかは
# 決め打ちできないので、Amazonから定義を取ってきて画面に出す。
# 競合のASINが分かっていれば、その商品タイプをそのまま使うのが確実
# （同じ棚に並べたいのだから、競合と同じ型でよい）。


@router.get("/product-type")
def product_type_of_asin(asin: str):
    """競合ASINの商品タイプを調べる。"""
    from app.services import amazon_api
    return amazon_api.fetch_product_type(asin)


@router.get("/product-type/{product_type}/schema")
def product_type_schema(product_type: str):
    """その商品タイプで何を入れないといけないかを返す。"""
    from app.services import amazon_api
    return amazon_api.fetch_product_type_schema(product_type)


# ---------- Amazonサジェスト ----------
#
# 検索窓に出る入力候補。実際に検索されている言い回しなので、そのまま
# 需要の証拠になる。Amazonの補完APIは公開されていて、鍵は要らない。
#
# もともと手元のPCで動かすサーバーに置いていたが、起動していないと
# 使えず、外注さんのPCでも動かない。ここに移して常に使えるようにした。

_SUGGEST_URL = "https://completion.amazon.co.jp/api/2017/suggestions"
# 深掘りで足す文字。ひらがな・英字・数字を後ろに付けて総当たりする
_DEEP_SUFFIX = ([chr(c) for c in range(ord("あ"), ord("ん") + 1)]
                + [chr(c) for c in range(ord("a"), ord("z") + 1)]
                + [str(n) for n in range(10)])


# ブラウザを名乗らないと、200は返るが候補が空になる（実測）
_SUGGEST_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


async def _fetch_suggest(client, word: str) -> list:
    """1語ぶんの候補を取る。人気順で返ってくる。"""
    params = {
        "limit": 11, "prefix": word, "suggestion-type": "KEYWORD",
        "page-type": "Gateway", "alias": "aps", "site-variant": "desktop",
        "version": 3, "event": "onKeyPress", "wc": "", "lop": "ja_JP",
        "last-prefix": "", "avg-ks-time": 0, "fb": 1, "session-id": "000-0000000-0000000",
        "request-id": "SUGGEST", "mid": "A1VC38T7YXB528", "plain-mid": 1,
        "client-info": "amazon-search-ui",
    }
    try:
        r = await client.get(_SUGGEST_URL, params=params, timeout=10,
                             headers={"User-Agent": _SUGGEST_UA,
                                      "Accept": "application/json"})
        if r.status_code != 200:
            return []
        return [s.get("value") for s in (r.json().get("suggestions") or [])
                if s.get("value")]
    except Exception:
        return []


@router.get("/suggest/debug")
async def suggest_debug(q: str = "ガーゼハンカチ"):
    """サジェストが空で返る原因を見る。応答をそのまま返す。

    Amazonはデータセンターからの通信を弾くことがあり、その場合は
    200で中身が空になる（403やエラーにはならない）ので判別しづらい。
    """
    import httpx
    params = {
        "limit": 11, "prefix": q, "suggestion-type": "KEYWORD",
        "page-type": "Gateway", "alias": "aps", "site-variant": "desktop",
        "version": 3, "event": "onKeyPress", "lop": "ja_JP",
        "mid": "A1VC38T7YXB528", "client-info": "amazon-search-ui",
    }
    async with httpx.AsyncClient() as client:
        r = await client.get(_SUGGEST_URL, params=params, timeout=15,
                             headers={"User-Agent": _SUGGEST_UA,
                                      "Accept": "application/json"})
    return {"status": r.status_code, "body": r.text[:600],
            "sent_ua": _SUGGEST_UA[:40]}


@router.get("/suggest")
async def suggest(q: str, deep: int = 0):
    """検索窓の入力候補。カンマか改行で複数語を渡せる（5語まで）。

    deep=1 で「語＋あ〜ん／a〜z／0〜9」の総当たり。10倍ほど広く集まるが
    時間がかかり、関係ない語も混ざる。
    """
    import httpx

    seeds = [w.strip() for w in re.split(r"[,\n、]", q or "") if w.strip()][:5]
    if not seeds:
        return {"ok": False, "error": "元の語がありません"}

    groups = []
    async with httpx.AsyncClient() as client:
        for seed in seeds:
            # まず素の語。これが人気順の本命
            found = await _fetch_suggest(client, seed)
            seen = set(found)

            if deep:
                # 総当たり。順番は保ちつつ、重複は落とす
                import asyncio
                tasks = [_fetch_suggest(client, f"{seed}{s}") for s in _DEEP_SUFFIX]
                for res in await asyncio.gather(*tasks):
                    for v in res:
                        if v not in seen:
                            seen.add(v)
                            found.append(v)

            groups.append({"seed": seed, "suggestions": found})

    # 全体でも返す。古い呼び方をしている画面のため
    flat = []
    for g in groups:
        flat.extend(g["suggestions"])
    return {"ok": True, "groups": groups, "suggestions": flat[:300]}


# ---------- 商品画像の文字 ----------
#
# 競合のメイン画像・サブ画像に書かれている文字を、そのまま書き出す。
# 画像の中の文言は検索では拾えないが、売り文句がそのまま出ているので
# 分析や商品説明を作るときの材料になる。
#
# 画像はSP-APIのカタログから取る（A+の画像は取れないので対象外）。

@router.get("/imgtext")
async def image_text(asin: str):
    """競合の商品画像に書かれている文字を書き出す。

    1商品あたり1〜3円ほどのAPI利用料がかかる。
    """
    import base64 as _b64
    import httpx
    from app.services import amazon_api
    from app.services import copywriter

    asin = (asin or "").strip().upper()
    if not asin:
        return {"ok": False, "error": "ASINがありません"}
    if not copywriter.is_enabled():
        return {"ok": False,
                "error": "ANTHROPIC_API_KEY が未設定です。Renderの環境変数に入れてください"}

    # カタログから画像のURLを取る
    try:
        params = urllib.parse.urlencode({
            "marketplaceIds": "A1VC38T7YXB528",
            "includedData": "images",
        })
        data = amazon_api._call_sp_api(f"/catalog/2022-04-01/items/{asin}?{params}")
    except Exception as e:
        return {"ok": False, "error": f"画像を取れませんでした: {type(e).__name__}"}

    urls = []
    for grp in (data.get("images") or []):
        for im in (grp.get("images") or []):
            # 大きすぎると重いので、程よい大きさのものを選ぶ
            if im.get("link") and 300 <= (im.get("width") or 0) <= 1200:
                urls.append(im["link"])
    # 同じ画像が複数サイズで返るので、重複を落とす
    seen, picked = set(), []
    for u in urls:
        key = u.rsplit("/", 1)[-1].split("._")[0]
        if key not in seen:
            seen.add(key)
            picked.append(u)
    picked = picked[:7]          # メイン＋サブ6枚まで
    if not picked:
        return {"ok": False, "error": "この商品の画像が取れませんでした"}

    # 画像を読み込んでAIに渡す
    content = []
    async with httpx.AsyncClient(timeout=30) as client:
        for u in picked:
            try:
                r = await client.get(u)
                if r.status_code != 200:
                    continue
                content.append({
                    "type": "image",
                    "source": {"type": "base64",
                               "media_type": r.headers.get("content-type", "image/jpeg"),
                               "data": _b64.b64encode(r.content).decode()},
                })
            except Exception:
                continue
    if not content:
        return {"ok": False, "error": "画像を読み込めませんでした"}

    content.append({"type": "text", "text": (
        "これはAmazonの商品画像です。画像の中に書かれている日本語の文字を、"
        "そのまま書き出してください。\n"
        "・言い換えや要約はせず、原文のまま写してください\n"
        "・画像ごとに「1枚目」「2枚目」と見出しを付けてください\n"
        "・文字が無い画像は「（文字なし）」と書いてください\n"
        "・あなたの感想や説明は要りません")})

    payload = {
        "model": "claude-haiku-4-5-20251001",   # 画像の読み取りは軽いモデルで足りる
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {"x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
               "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post("https://api.anthropic.com/v1/messages",
                                json=payload, headers=headers)
    if res.status_code != 200:
        return {"ok": False, "error": f"読み取りに失敗しました（{res.status_code}）: "
                                      f"{res.text[:200]}"}
    text = "".join(b.get("text", "") for b in res.json().get("content", [])
                   if b.get("type") == "text").strip()
    return {"ok": True, "asin": asin, "images": len(content) - 1, "text": text}
