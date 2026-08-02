from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import io
import uuid
import time
import threading
from app.core.database import get_db, SessionLocal
from app.models.product import Product
from app.models.settings import OrderSettings
from app.models.order_history import OrderHistory
from app.services.calc import CalcSettings, calc_order_qty, growth_rate_pct
from app.services.excel_export import build_taotaro_excel

router = APIRouter(prefix="/orders", tags=["orders"])


def _not_shipped():
    """発注済みとして数えるべき行の条件。

    FBAへ納品済み(status='shipped')の発注は、その分がSP-APIの在庫側に
    現れるため、発注済みとしても数えると二重計上になり在庫過多と判定されて
    発注が漏れる。status未設定(NULL)の古いデータは未納品として扱う。"""
    return (OrderHistory.status == None) | (OrderHistory.status != "shipped")  # noqa: E711


# バックグラウンドジョブ管理（メモリ内）
_jobs: dict = {}
_jobs_lock = threading.Lock()


def _prune_jobs():
    """古い・完了済みのジョブをメモリから掃除する。
    ジョブは結果（全商品リスト）を保持したまま_jobsに残り続けるため、
    定期取得(cron)やユーザー操作のたびに溜まってメモリリークになる。
    フェッチは長くても数分で終わるので、20分より古いものと、上限30件を超えた古い分を削除する。"""
    now = time.time()
    with _jobs_lock:
        for jid in [j for j, v in _jobs.items() if now - v.get("started_at", now) > 1200]:
            _jobs.pop(jid, None)
        if len(_jobs) > 30:
            for jid, _ in sorted(_jobs.items(), key=lambda kv: kv[1].get("started_at", 0))[:-30]:
                _jobs.pop(jid, None)

class OrderItem(BaseModel):
    product_id: int
    sku: str
    name: str
    asin: str
    fnsku: str
    buy_url: str
    photo_url: str
    color: str
    size: str
    spec: str = ""
    customer_memo: str = ""
    price: float
    repack: str
    note: str
    amazon_url: str
    set_size: int
    available: int
    inbound: int
    sales_7: float
    sales_15: float
    sales_30: float
    sales_60: float
    days_left: int
    daily: float
    stock: int
    recommended_qty: int
    qty: int  # 最終発注数（ユーザーが調整可能）

class ExportRequest(BaseModel):
    items: List[OrderItem]


class OrderRecordItem(BaseModel):
    """発注ボタン用：発注履歴に記録する最小限の項目"""
    sku: str
    name: str = ""
    color: str = ""
    size: str = ""
    qty: int
    price: float = 0
    buy_url: str = ""
    photo_url: str = ""
    asin: str = ""
    fnsku: str = ""
    note: str = ""


class OrderRecordRequest(BaseModel):
    items: List[OrderRecordItem]


def _run_preview_job(job_id: str):
    """バックグラウンドでSP-APIデータを取得して推奨発注数を計算"""
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "result": None, "error": None, "started_at": time.time()}

    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.is_active == True).all()
        if not products:
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["result"] = []
            return

        settings_row = db.query(OrderSettings).first()
        s = _build_calc_settings(settings_row)

        from app.core.config import settings as app_settings
        if app_settings.SP_API_REFRESH_TOKEN:
            from app.services.amazon_api import fetch_inventory, fetch_all_sales
            from concurrent.futures import ThreadPoolExecutor
            asin_list = [p.asin for p in products if p.asin]
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_inv   = ex.submit(fetch_inventory)
                f_sales = ex.submit(fetch_all_sales, asin_list, getattr(settings_row, 'order_qty_cap', 0) or 0)
            inventory = f_inv.result()
            sales_7, sales_15, sales_30, sales_60, sales_90 = f_sales.result()
        else:
            inventory = {}
            sales_7 = sales_15 = sales_30 = sales_60 = sales_90 = {}

        from sqlalchemy import func as sqlfunc
        ordered_qty_by_sku = dict(
            db.query(OrderHistory.sku, sqlfunc.sum(OrderHistory.qty))
            .filter(OrderHistory.is_deleted == False)
            .filter(_not_shipped())
            .group_by(OrderHistory.sku)
            .all()
        )

        result = []
        for p in products:
            inv = inventory.get(p.fnsku, {})
            available   = inv.get("available", 0)
            inbound     = inv.get("inbound", 0)
            processing  = inv.get("processing", 0)
            ordered     = ordered_qty_by_sku.get(p.sku, 0)
            s7  = sales_7.get(p.asin, 0)
            s15 = sales_15.get(p.asin, 0)
            s30 = sales_30.get(p.asin, 0)
            s60 = sales_60.get(p.asin, 0)
            s90 = sales_90.get(p.asin, 0)

            calc = calc_order_qty(
                available=available, inbound=inbound + ordered, processing=processing,
                extra_stock=p.extra_stock or 0,
                sales_7=s7, sales_15=s15, sales_30=s30, sales_60=s60,
                set_size=p.set_size or 1, s=s, sales_90=s90,
            )
            result.append({
                "product_id": p.id,
                "sku": p.sku or "",
                "name": p.name or "",
                "asin": p.asin or "",
                "fnsku": p.fnsku or "",
                "buy_url": p.buy_url or "",
                "photo_url": p.photo_url or "",
                "color": p.color or "",
                "size": p.size or "",
                "spec": p.spec or "",
                "customer_memo": p.customer_memo or "",
                "price": p.price or 0,
                "repack": p.repack or "",
                "note": p.note or "",
                "category": p.category or "標準",
                "amazon_url": p.amazon_url or (f"https://www.amazon.co.jp/dp/{p.asin}" if p.asin else ""),
                "set_size": p.set_size or 1,
                "available": available,
                "inbound": inbound,
                "processing": processing,
                "ordered": ordered,
                "sales_7": s7,
                "sales_15": s15,
                "sales_30": s30,
                "sales_60": s60,
                "sales_90": s90,
                "days_left": calc.days_left,
                "daily": calc.daily,
                "stock": calc.stock,
                "recommended_qty": calc.qty,
                "qty": calc.qty,
                "needs_order": calc.qty > 0,
                "growth_rate": growth_rate_pct(s7, s15, s90),
            })

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
    finally:
        db.close()


def _run_stock_job(job_id: str):
    """全在庫一覧用バックグラウンドジョブ（推奨発注数マイナス含む全商品）"""
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "result": None, "error": None, "started_at": time.time()}

    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.is_active == True).all()
        if not products:
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["result"] = []
            return

        settings_row = db.query(OrderSettings).first()
        s = _build_calc_settings(settings_row)

        from app.core.config import settings as app_settings
        if app_settings.SP_API_REFRESH_TOKEN:
            from app.services.amazon_api import fetch_inventory, fetch_all_sales
            from concurrent.futures import ThreadPoolExecutor
            asin_list = [p.asin for p in products if p.asin]
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_inv   = ex.submit(fetch_inventory)
                f_sales = ex.submit(fetch_all_sales, asin_list, getattr(settings_row, 'order_qty_cap', 0) or 0)
            inventory = f_inv.result()
            sales_7, sales_15, sales_30, sales_60, sales_90 = f_sales.result()
        else:
            inventory = {}
            sales_7 = sales_15 = sales_30 = sales_60 = sales_90 = {}

        from sqlalchemy import func as sqlfunc
        ordered_qty_by_sku = dict(
            db.query(OrderHistory.sku, sqlfunc.sum(OrderHistory.qty))
            .filter(OrderHistory.is_deleted == False)
            .filter(_not_shipped())
            .group_by(OrderHistory.sku)
            .all()
        )

        result = []
        for p in products:
            inv = inventory.get(p.fnsku, {})
            available  = inv.get("available", 0)
            inbound    = inv.get("inbound", 0)
            processing = inv.get("processing", 0)
            ordered    = ordered_qty_by_sku.get(p.sku, 0)
            s7  = sales_7.get(p.asin, 0)
            s15 = sales_15.get(p.asin, 0)
            s30 = sales_30.get(p.asin, 0)
            s60 = sales_60.get(p.asin, 0)
            s90 = sales_90.get(p.asin, 0)

            calc = calc_order_qty(
                available=available, inbound=inbound + ordered, processing=processing,
                extra_stock=p.extra_stock or 0,
                sales_7=s7, sales_15=s15, sales_30=s30, sales_60=s60,
                set_size=p.set_size or 1, s=s, sales_90=s90,
            )

            # 全商品を表示。在庫充足の場合はneeded_piecesをマイナスで計算
            from app.services.calc import weighted_daily
            daily = weighted_daily(s7, s15, s30, s60, s90, s)
            stock = available + inbound + ordered + processing + (p.extra_stock or 0)
            from app.services.calc import calc_sale_extra_days
            needed_pieces = round(daily * calc.growth * (s.lead_days + calc_sale_extra_days(s)) - stock) if daily > 0 else 0

            result.append({
                "product_id": p.id,
                "sku": p.sku or "",
                "name": p.name or "",
                "asin": p.asin or "",
                "fnsku": p.fnsku or "",
                "buy_url": p.buy_url or "",
                "photo_url": p.photo_url or "",
                "color": p.color or "",
                "size": p.size or "",
                "spec": p.spec or "",
                "customer_memo": p.customer_memo or "",
                "price": p.price or 0,
                "repack": p.repack or "",
                "note": p.note or "",
                "category": p.category or "標準",
                "amazon_url": p.amazon_url or (f"https://www.amazon.co.jp/dp/{p.asin}" if p.asin else ""),
                "set_size": p.set_size or 1,
                "available": available,
                "inbound": inbound,
                "processing": processing,
                "ordered": ordered,
                "sales_7": s7,
                "sales_15": s15,
                "sales_30": s30,
                "sales_60": s60,
                "sales_90": s90,
                "days_left": calc.days_left,
                "daily": round(daily, 2),
                "stock": stock,
                "recommended_qty": calc.qty,
                "recommended_pieces": needed_pieces,
                "qty": max(0, calc.qty),
            })

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
    finally:
        db.close()


@router.post("/stock/start")
def start_stock(background_tasks: BackgroundTasks, force: bool = False):
    """全在庫一覧取得をバックグラウンドで開始"""
    _prune_jobs()
    if force:
        from app.services.amazon_api import _cache
        _cache.clear()
    job_id = str(uuid.uuid4())
    background_tasks.add_task(_run_stock_job, job_id)
    return {"job_id": job_id}


@router.post("/preview/start")
def start_preview(background_tasks: BackgroundTasks, force: bool = False):
    """SP-APIデータ取得をバックグラウンドで開始し、job_idを返す。force=TrueでキャッシュをクリアしてからAPIを叩く"""
    _prune_jobs()
    if force:
        from app.services.amazon_api import _cache
        _cache.clear()
    job_id = str(uuid.uuid4())
    background_tasks.add_task(_run_preview_job, job_id)
    return {"job_id": job_id}


@router.get("/preview/status/{job_id}")
def get_preview_status(job_id: str):
    """ジョブの状態と結果を返す"""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {
        "status": job["status"],   # "running" | "done" | "error"
        "result": job["result"],
        "error": job["error"],
        "elapsed": round(time.time() - job["started_at"], 1),
    }


@router.get("/preview")
def preview_orders(db: Session = Depends(get_db)):
    """後方互換：同期でSP-APIデータ取得（キャッシュ済みなら高速）"""
    products = db.query(Product).filter(Product.is_active == True).all()
    if not products:
        return []

    settings_row = db.query(OrderSettings).first()
    s = _build_calc_settings(settings_row)

    from app.core.config import settings as app_settings
    if app_settings.SP_API_REFRESH_TOKEN:
        from app.services.amazon_api import fetch_inventory, fetch_all_sales
        from concurrent.futures import ThreadPoolExecutor
        asin_list = [p.asin for p in products if p.asin]
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_inv   = ex.submit(fetch_inventory)
            f_sales = ex.submit(fetch_all_sales, asin_list, getattr(settings_row, 'order_qty_cap', 0) or 0)
        inventory = f_inv.result()
        sales_7, sales_15, sales_30, sales_60, sales_90 = f_sales.result()
    else:
        inventory = {}
        sales_7 = sales_15 = sales_30 = sales_60 = sales_90 = {}

    from sqlalchemy import func as sqlfunc
    ordered_qty_by_sku = dict(
        db.query(OrderHistory.sku, sqlfunc.sum(OrderHistory.qty))
        .filter(OrderHistory.is_deleted == False)
        .filter(_not_shipped())
        .group_by(OrderHistory.sku)
        .all()
    )

    result = []
    for p in products:
        inv = inventory.get(p.fnsku, {})
        available   = inv.get("available", 0)
        inbound     = inv.get("inbound", 0)
        processing  = inv.get("processing", 0)
        ordered     = ordered_qty_by_sku.get(p.sku, 0)
        s7  = sales_7.get(p.asin, 0)
        s15 = sales_15.get(p.asin, 0)
        s30 = sales_30.get(p.asin, 0)
        s60 = sales_60.get(p.asin, 0)
        s90 = sales_90.get(p.asin, 0)

        calc = calc_order_qty(
            available=available, inbound=inbound + ordered, processing=processing,
            extra_stock=p.extra_stock or 0,
            sales_7=s7, sales_15=s15, sales_30=s30, sales_60=s60,
            set_size=p.set_size or 1, s=s, sales_90=s90,
        )
        result.append({
            "product_id": p.id,
            "sku": p.sku or "",
            "name": p.name or "",
            "asin": p.asin or "",
            "fnsku": p.fnsku or "",
            "buy_url": p.buy_url or "",
            "photo_url": p.photo_url or "",
            "color": p.color or "",
            "size": p.size or "",
            "spec": p.spec or "",
            "customer_memo": p.customer_memo or "",
            "price": p.price or 0,
            "repack": p.repack or "",
            "note": p.note or "",
            "category": p.category or "標準",
            "amazon_url": p.amazon_url or (f"https://www.amazon.co.jp/dp/{p.asin}" if p.asin else ""),
            "set_size": p.set_size or 1,
            "available": available,
            "inbound": inbound,
            "processing": processing,
            "ordered": ordered,
            "sales_7": s7,
            "sales_15": s15,
            "sales_30": s30,
            "sales_60": s60,
            "sales_90": s90,
            "days_left": calc.days_left,
            "daily": calc.daily,
            "stock": calc.stock,
            "recommended_qty": calc.qty,
            "qty": calc.qty,
            "needs_order": calc.qty > 0,
            "growth_rate": growth_rate_pct(s7, s15, s90),
        })

    return result


@router.post("/export")
def export_excel(req: ExportRequest, db: Session = Depends(get_db)):
    """発注リストをタオタロウ形式のExcelとしてダウンロードし、発注履歴に保存"""
    if not req.items:
        raise HTTPException(status_code=400, detail="発注リストが空です")

    items_data = []
    for item in req.items:
        if item.qty <= 0:
            continue
        items_data.append({
            "sku": item.sku,
            "name": item.name,
            "amazon_url": item.amazon_url,
            "buy_url": item.buy_url,
            "photo_url": item.photo_url,
            "color": item.color,
            "size": item.size,
            "spec": item.spec,
            "customer_memo": item.customer_memo,
            "qty": item.qty,
            "price": item.price,
            "repack": item.repack,
            "note": item.note,
            "set_size": item.set_size,
            "asin": item.asin,
            "fnsku": item.fnsku,
        })

    if not items_data:
        raise HTTPException(status_code=400, detail="発注数が0の商品しかありません")

    for item in items_data:
        db.add(OrderHistory(
            sku=item["sku"],
            name=item["name"],
            color=item["color"],
            size=item["size"],
            qty=item["qty"],
            price=item["price"],
            buy_url=item["buy_url"],
            photo_url=item["photo_url"],
            asin=item["asin"],
            fnsku=item["fnsku"],
            note=item["note"],
        ))
    db.commit()

    from datetime import date
    excel_bytes = build_taotaro_excel(items_data)
    filename = f"{date.today().strftime('%Y%m%d')}_order.xlsx"

    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/order")
def record_order(req: OrderRecordRequest, db: Session = Depends(get_db)):
    """発注ボタン用：Excelを生成せず、指定商品だけを発注履歴に記録する。
    （Excelダウンロードは全選択分をまとめて記録するのに対し、こちらは押した商品のみ）"""
    recorded = 0
    for item in req.items:
        if item.qty <= 0:
            continue
        db.add(OrderHistory(
            sku=item.sku,
            name=item.name,
            color=item.color,
            size=item.size,
            qty=item.qty,
            price=item.price,
            buy_url=item.buy_url,
            photo_url=item.photo_url,
            asin=item.asin,
            fnsku=item.fnsku,
            note=item.note,
        ))
        recorded += 1
    if recorded == 0:
        raise HTTPException(status_code=400, detail="発注数が1以上の商品がありません")
    db.commit()
    return {"recorded": recorded}


@router.get("/history")
def get_order_history(db: Session = Depends(get_db)):
    """発注済みリストを取得（未削除・新しい順）"""
    rows = db.query(OrderHistory).filter(OrderHistory.is_deleted == False).order_by(OrderHistory.ordered_at.desc()).all()
    return [
        {
            "id": r.id,
            "ordered_at": r.ordered_at.isoformat() if r.ordered_at else None,
            "sku": r.sku,
            "name": r.name,
            "color": r.color,
            "size": r.size,
            "qty": r.qty,
            "price": r.price,
            "buy_url": r.buy_url,
            "photo_url": r.photo_url,
            "asin": r.asin,
            "fnsku": r.fnsku,
            "note": r.note,
            "status": getattr(r, "status", None) or "ordered",
        }
        for r in rows
    ]


# 消し込みに使う納品の基準日。これより前の納品は突合しない。
# 過去の発注データと実際の納品数には食い違いがあり（7/02は発注black60/blue40に対し
# 納品black48/blue60）、そこまで遡って自動で辻褄を合わせようとすると誤って
# 消し込んでしまう。運用を始めた2026-07-27の納品以降だけを対象にする。
DELIVERY_MATCH_SINCE = "2026-07-27"


def _drop_same_day_duplicates(shipments: List[dict]) -> List[dict]:
    """同じ日・同じ数量の納品は作り直しとみなして1件に寄せる。

    Send to Amazonでは納品を作り直すと、キャンセルした分とは別に同内容の納品が
    複数できる（2026-07-28にy84_black 70個が WORKING と READY_TO_SHIP で2件）。
    両方数えると実際の倍になるため、受領済みを優先して1件だけ残す。
    """
    best: dict = {}
    for s in shipments:
        key = (s["shipped_at"], s["shipped"])
        cur = best.get(key)
        # 受領済みの実績がある方を残す（同条件なら先勝ち）
        if cur is None or (s.get("received") or 0) > (cur.get("received") or 0):
            best[key] = s
    return list(best.values())


@router.get("/delivery-candidates")
def get_delivery_candidates(db: Session = Depends(get_db)):
    """FBAへの実発送実績と突合し、納品済みとみなせる発注の候補を返す。

    根拠は「実際にFBAへ発送した数量」（v0 getShipments の QuantityShipped）。
    納品プランは作り直すと古いものがACTIVEのまま残り実態と合わないため使わない。

    発注日より前の納品は別ロットなので数えない。同じSKUを繰り返し発注・納品して
    いるため、累計で突合すると過去の納品で新しい発注まで消えてしまう。

    自動では消さない。画面で確認してから確定する。
    """
    from app.core.config import settings as app_settings
    if not app_settings.SP_API_REFRESH_TOKEN:
        return {"candidates": [], "error": "SP-API未設定"}

    from app.services.amazon_api import fetch_inbound_shipments
    try:
        by_sku = fetch_inbound_shipments()
    except Exception as e:
        return {"candidates": [], "error": f"納品実績の取得に失敗しました: {e}"}

    orders = (
        db.query(OrderHistory)
        .filter(OrderHistory.is_deleted == False)
        .filter(_not_shipped())
        .order_by(OrderHistory.ordered_at.asc())  # 古い発注から消し込む（先入先出）
        .all()
    )

    # SKUごとに「割り当て可能な納品」を用意する。1つの納品を複数の発注へ
    # 二重に充当しないよう、割り当てた分を各納品から減らしていく。
    pool: dict = {}
    for sku, rec in by_sku.items():
        rows = [
            dict(s) for s in rec["shipments"]
            if s["shipped_at"] and s["shipped_at"] >= DELIVERY_MATCH_SINCE
        ]
        rows = _drop_same_day_duplicates(rows)
        for r in rows:
            r["left"] = r["shipped"]
        pool[sku] = sorted(rows, key=lambda x: x["shipped_at"])

    candidates = []
    for o in orders:
        rows = pool.get(o.sku) or []
        ordered_day = o.ordered_at.date().isoformat() if o.ordered_at else ""
        need = o.qty or 0
        assigned = []
        for s in rows:
            if need <= 0:
                break
            if s["left"] <= 0:
                continue
            # 発注より前に発送されたものは別ロットなので充当しない
            if ordered_day and s["shipped_at"] < ordered_day:
                continue
            take = min(s["left"], need)
            s["left"] -= take
            need -= take
            assigned.append({
                "date": s["shipped_at"],
                "qty": take,
                "shipment_qty": s["shipped"],
                "received": s["received"],
                "status": s["status"],
                "shipment_id": s["shipment_id"],
            })
        if not assigned:
            continue
        covered = sum(a["qty"] for a in assigned)
        candidates.append({
            "id": o.id,
            "sku": o.sku,
            "name": o.name,
            "qty": o.qty,
            "ordered_at": o.ordered_at.isoformat() if o.ordered_at else None,
            "covered_qty": covered,
            "full_match": covered >= (o.qty or 0),
            # 受領が終わっていない納品を含む場合は、まだFBA在庫に反映されていない
            "pending_receive": any(a["received"] < a["shipment_qty"] for a in assigned),
            "shipments": sorted(assigned, key=lambda x: x["date"], reverse=True),
        })

    return {"candidates": candidates, "match_since": DELIVERY_MATCH_SINCE}


class MarkShippedRequest(BaseModel):
    ids: List[int]


@router.post("/mark-shipped")
def mark_orders_shipped(req: MarkShippedRequest, db: Session = Depends(get_db)):
    """指定した発注を納品済み(shipped)にする。発注済みの集計から外れる。"""
    if not req.ids:
        return {"ok": True, "updated": 0}
    rows = db.query(OrderHistory).filter(OrderHistory.id.in_(req.ids)).all()
    updated = 0
    for r in rows:
        if getattr(r, "status", None) != "shipped":
            r.status = "shipped"
            updated += 1
    db.commit()
    return {"ok": True, "updated": updated}


@router.delete("/history/{history_id}")
def delete_order_history(history_id: int, db: Session = Depends(get_db)):
    """発注済みレコードを削除（FBA納品プラン作成後に呼ぶ）"""
    row = db.query(OrderHistory).filter(OrderHistory.id == history_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="レコードが見つかりません")
    row.is_deleted = True
    db.commit()
    return {"ok": True}


def _build_calc_settings(row: Optional[OrderSettings]) -> CalcSettings:
    if not row:
        return CalcSettings()
    return CalcSettings(
        lead_days=getattr(row, 'lead_days', 75) or 75,
        weight_d7=row.weight_d7,
        weight_d15=row.weight_d15,
        weight_d30=row.weight_d30,
        weight_d60=row.weight_d60,
        weight_d90=getattr(row, 'weight_d90', 0.30) or 0.30,
        growth_ratio_threshold=row.growth_ratio_threshold,
        growth_multiplier=min(row.growth_multiplier, 1.0),
        decline_ratio_threshold=row.decline_ratio_threshold,
        decline_multiplier=max(row.decline_multiplier, 0.5),
        min_order_qty=row.min_order_qty,
        sale_enabled=row.sale_enabled,
        sale_start=row.sale_start,
        sale_end=row.sale_end,
        sale_multiplier=getattr(row, 'sale_multiplier', 3.0) or 3.0,
        # 後方互換
        threshold_days=row.threshold_days,
        target_days_normal=row.target_days_normal,
        target_days_sale=row.target_days_sale,
    )
