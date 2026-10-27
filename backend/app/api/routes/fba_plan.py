from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
import io
import uuid
import time
import threading
import logging
import shutil
import tempfile

from app.core.database import get_db, SessionLocal
from app.models.product import Product
from app.models.settings import OrderSettings
from app.models.order_history import OrderHistory
from app.services import taotaro
from app.services.calc import CalcSettings, weighted_daily, growth_mult, calc_sale_extra_days

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fba-plan", tags=["fba-plan"])

_jobs: dict = {}
_jobs_lock = threading.Lock()


def _prune_jobs():
    now = time.time()
    with _jobs_lock:
        for jid in [j for j, v in _jobs.items() if now - v.get("started_at", now) > 1200]:
            _jobs.pop(jid, None)
        if len(_jobs) > 30:
            for jid, _ in sorted(_jobs.items(), key=lambda kv: kv[1].get("started_at", 0))[:-30]:
                _jobs.pop(jid, None)


def _build_settings(row: Optional[OrderSettings]):
    if not row:
        return {
            "lt_order_to_warehouse": 7,
            "lt_shipping_request": 7,
            "lt_sea_to_fba": 18,
            "lt_air_to_fba": 10,
            "free_storage_days": 90,
            "air_threshold_days": 18,
            "hold_daily_threshold": 0.1,
            "fba_target_days": 0,
        }
    return {
        "lt_order_to_warehouse": getattr(row, "lt_order_to_warehouse", 7) or 7,
        "lt_shipping_request": getattr(row, "lt_shipping_request", 7) or 7,
        "lt_sea_to_fba": getattr(row, "lt_sea_to_fba", 18) or 18,
        "lt_air_to_fba": getattr(row, "lt_air_to_fba", 10) or 10,
        "free_storage_days": getattr(row, "free_storage_days", 90) or 90,
        "air_threshold_days": getattr(row, "air_threshold_days", 18) or 18,
        "hold_daily_threshold": getattr(row, "hold_daily_threshold", 0.1) or 0.1,
        "fba_target_days": getattr(row, "fba_target_days", 0) or 0,
    }


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
    )


def _run_plan_job(job_id: str, only_skus: Optional[list] = None):
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "result": None, "error": None, "started_at": time.time()}

    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.is_active == True).all()
        if only_skus:
            # 便の商品だけに絞る。売上はASIN1件ずつ取りに行くので、
            # 76件ぶん待たされていたのが十数件で済む
            keep = set(only_skus)
            products = [p for p in products if p.sku in keep]
        if not products:
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["result"] = {"items": [], "settings": {}}
            return

        settings_row = db.query(OrderSettings).first()
        plan_settings = _build_settings(settings_row)
        cs = _build_calc_settings(settings_row)

        from app.core.config import settings as app_settings
        if app_settings.SP_API_REFRESH_TOKEN:
            from app.services.amazon_api import fetch_inventory, fetch_all_sales
            from concurrent.futures import ThreadPoolExecutor
            asin_list = [p.asin for p in products if p.asin]
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_inv = ex.submit(fetch_inventory)
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
            .group_by(OrderHistory.sku)
            .all()
        )

        free_days = plan_settings["free_storage_days"]
        lt_sea_total = plan_settings["lt_order_to_warehouse"] + plan_settings["lt_shipping_request"] + plan_settings["lt_sea_to_fba"]
        lt_air_total = plan_settings["lt_order_to_warehouse"] + plan_settings["lt_shipping_request"] + plan_settings["lt_air_to_fba"]
        air_threshold = plan_settings["air_threshold_days"]
        hold_threshold = plan_settings["hold_daily_threshold"]
        # 既定は無料保管日数から出すが、船便の間隔に合わせて
        # 決め直したいことがあるので、設定があればそちらを使う
        target_stock_days = ((plan_settings.get("fba_target_days") or 0)
                             or (free_days
                                 - plan_settings["lt_order_to_warehouse"]))
        sale_extra = calc_sale_extra_days(cs)

        result = []
        for p in products:
            inv = inventory.get(p.fnsku, {})
            available = inv.get("available", 0)
            inbound = inv.get("inbound", 0)
            processing = inv.get("processing", 0)
            ordered = ordered_qty_by_sku.get(p.sku, 0)
            extra = p.extra_stock or 0

            s7 = sales_7.get(p.asin, 0)
            s15 = sales_15.get(p.asin, 0)
            s30 = sales_30.get(p.asin, 0)
            s60 = sales_60.get(p.asin, 0)
            s90 = sales_90.get(p.asin, 0)

            daily = weighted_daily(s7, s15, s30, s60, s90, cs)
            g = growth_mult(s7, s15, s90, cs)

            fba_stock = available
            pipeline_stock = available + inbound + processing + ordered + extra
            fba_days = int(fba_stock / daily) if daily > 0 else 9999
            pipeline_days = int(pipeline_stock / daily) if daily > 0 else 9999

            # 配送方法判定
            #
            # 「日販が少ない→保留」は売れている商品の話。
            # 新商品はまだ売っていないので日販0だが、
            # これから売るために仕入れたものなので止めてはいけない。
            # FBA在庫も実績も無い＝初回納品とみて、保留から外す
            # （15件すべてが保留になり、合計出荷数が0個になっていた）
            is_new = (available == 0 and (s90 or 0) == 0)
            if daily < hold_threshold and not is_new:
                ship_method = "hold"
            elif pipeline_days <= air_threshold:
                ship_method = "air"
            else:
                ship_method = "sea"

            # 推奨納品数 = 目標日数 × 日販 × 成長補正 + セール上乗せ − パイプライン在庫
            target = round(daily * g * (target_stock_days + sale_extra))
            recommended = max(0, target - pipeline_stock)
            set_size = max(1, p.set_size or 1)
            recommended_sets = -(-recommended // set_size) if recommended > 0 else 0

            result.append({
                "product_id": p.id,
                "sku": p.sku or "",
                "fnsku": p.fnsku or "",
                "asin": p.asin or "",
                "name": p.name or "",
                "photo_url": p.photo_url or "",
                "color": p.color or "",
                "size": p.size or "",
                "set_size": set_size,
                "price": p.price or 0,
                "category": p.category or "標準",
                "buy_url": p.buy_url or "",
                # 販売データ
                "sales_7": s7,
                "sales_15": s15,
                "sales_30": s30,
                "sales_60": s60,
                "sales_90": s90,
                "daily": round(daily, 2),
                "growth": round(g, 2),
                # 在庫データ
                "fba_available": available,
                "fba_inbound": inbound,
                "fba_processing": processing,
                "ordered": ordered,
                "extra_stock": extra,
                "pipeline_stock": pipeline_stock,
                # 残日数
                "fba_days": fba_days,
                "pipeline_days": pipeline_days,
                # 判定結果
                "ship_method": ship_method,
                "target_stock": target,
                "recommended_sets": recommended_sets,
                "recommended_pieces": recommended_sets * set_size,
                "plan_qty": recommended_sets,
            })

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = {
                "items": result,
                "settings": plan_settings,
                "sale_extra_days": round(sale_extra, 1),
                "target_stock_days": target_stock_days,
                "lt_sea_total": lt_sea_total,
                "lt_air_total": lt_air_total,
            }

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
    finally:
        db.close()


@router.post("/start")
def start_plan(background_tasks: BackgroundTasks, force: bool = False,
               skus: str = ""):
    """skus を渡すと、その商品だけ在庫と売上を取りに行く（便で絞ったとき）。"""
    _prune_jobs()
    if force:
        from app.services.amazon_api import _cache
        # 在庫は消す。売上はASINごとに持っていて、消すと取り直しに
        # 何分もかかるので残す
        _cache.pop("inventory", None)
    job_id = str(uuid.uuid4())
    only = [x for x in (skus or "").split(",") if x.strip()]
    background_tasks.add_task(_run_plan_job, job_id, only)
    return {"job_id": job_id}


@router.get("/status/{job_id}")
def get_plan_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return {"status": "not_found"}
    return {
        "status": job["status"],
        "result": job["result"],
        "error": job["error"],
        "elapsed": round(time.time() - job["started_at"], 1),
    }


class PlanExportItem(BaseModel):
    sku: str
    fnsku: str
    plan_qty: int
    set_size: int = 1


class PlanExportRequest(BaseModel):
    items: list[PlanExportItem]


@router.post("/create-inbound-plan")
def create_inbound_plan_api(req: PlanExportRequest, db: Session = Depends(get_db)):
    """画面で決めた納品数でAmazonにFBA納品プランを作成する。

    作れるのはSKUと数量まで。梱包（何箱に分けるか）や配送業者はタオタロウが
    決めるため、ここでは確定しない。作成後はセラーセントラルで商品ラベルを
    ダウンロードしてWeChatへ送る運用になる。
    """
    from app.core.config import settings as app_settings
    if not app_settings.SP_API_REFRESH_TOKEN:
        raise HTTPException(status_code=400, detail="SP-APIが設定されていません")
    if not req.items:
        raise HTTPException(status_code=400, detail="納品する商品がありません")

    from app.services.amazon_api import (
        create_inbound_plan, fetch_default_source_address,
    )

    try:
        source = fetch_default_source_address()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"発送元住所を読めませんでした（{e}）",
        )
    if not source:
        raise HTTPException(
            status_code=400,
            detail="発送元住所を持った納品プランがありません。セラーセントラルで一度納品プランを作ると、その住所を引き継げます",
        )

    # plan_qtyはセット数なのでピース数に直して送る
    items = [
        {"sku": it.sku, "qty": it.plan_qty * max(1, it.set_size)}
        for it in req.items
        if it.plan_qty > 0
    ]
    if not items:
        raise HTTPException(status_code=400, detail="納品数が1以上の商品がありません")

    try:
        result = create_inbound_plan(
            items,
            source_address=source,
            name=f"FBA納品 {date.today().strftime('%Y/%m/%d')}",
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"納品プランの作成に失敗しました: {e}")

    return {
        "ok": True,
        "inbound_plan_id": result["inbound_plan_id"],
        "operation_id": result["operation_id"],
        "total_pieces": sum(i["qty"] for i in items),
        "sku_count": len(items),
        # セラーセントラルの納品管理画面（ここで商品ラベルをDLする）
        "seller_central_url": "https://sellercentral.amazon.co.jp/fba/sendtoamazon",
    }


@router.get("/inbound-operation/{operation_id}")
def get_inbound_operation(operation_id: str):
    """createInboundPlanは非同期なので、完了したかを確認する。"""
    from app.core.config import settings as app_settings
    if not app_settings.SP_API_REFRESH_TOKEN:
        raise HTTPException(status_code=400, detail="SP-APIが設定されていません")
    from app.services.amazon_api import get_inbound_operation_status
    try:
        d = get_inbound_operation_status(operation_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "status": d.get("operationStatus") or "",
        "errors": d.get("operationProblems") or [],
    }


# ---------- 納品先を決める（placement） ----------
#
# Amazonの新しい流れでは、納品プランを作ったあとすぐに
# 「どのFCに、いくつの納品に分けて送るか」を決める。
# これを確定しないと納品（FBA番号）ができず、セラセンにも
# 出てこないし、箱の中身も入れられない。

def _fee_total(option: dict) -> tuple:
    total, cur = 0.0, ""
    for f in option.get("fees") or []:
        v = f.get("value") or {}
        try:
            total += float(v.get("amount") or 0)
        except Exception:
            pass
        cur = v.get("code") or cur
    return round(total, 2), cur


@router.get("/placement/{plan_id}")
def placement_options(plan_id: str):
    """納品先の候補を出す。安い順に並べる。"""
    from app.services import amazon_api
    try:
        options = amazon_api.list_placement_options(plan_id)
    except Exception as e:
        raise HTTPException(400, f"納品先の候補が取れませんでした（{e}）")

    out = []
    for o in options:
        fee, cur = _fee_total(o)
        out.append({
            "placement_option_id": o.get("placementOptionId") or "",
            "shipment_ids": o.get("shipmentIds") or [],
            "shipment_count": len(o.get("shipmentIds") or []),
            "fee": fee,
            "currency": cur,
            "status": o.get("status") or "",
            "expires_at": o.get("expiration") or "",
        })
    out.sort(key=lambda x: (x["fee"], x["shipment_count"]))
    return {"plan_id": plan_id, "options": out}


class ConfirmPlacementIn(BaseModel):
    plan_id: str
    placement_option_id: str


@router.post("/placement/confirm")
def confirm_placement(req: ConfirmPlacementIn):
    """納品先を確定して、できた納品を返す。"""
    from app.services import amazon_api
    try:
        amazon_api.confirm_placement_option(
            req.plan_id, req.placement_option_id)
    except Exception as e:
        raise HTTPException(400, f"納品先を確定できませんでした（{e}）")

    shipments = []
    try:
        for sh in amazon_api.list_plan_shipments(req.plan_id):
            shipments.append({
                "shipment_id": sh.get("shipmentId") or "",
                # FBAで始まる番号。セラセンで探すときはこれ
                "confirmation_id": sh.get("shipmentConfirmationId") or "",
                "destination": ((sh.get("destination") or {})
                                .get("warehouseId") or ""),
                "name": sh.get("name") or "",
            })
    except Exception:
        pass
    return {"ok": True, "shipments": shipments}


@router.post("/export-excel")
def export_plan_excel(req: PlanExportRequest, db: Session = Depends(get_db)):
    if not req.items:
        return {"error": "エクスポートする商品がありません"}

    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "納品プラン"

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin'),
    )

    ws.merge_cells("A1:B1")
    ws["A1"] = "Default prep owner"
    ws["C1"] = "Seller"
    ws.merge_cells("A2:B2")
    ws["A2"] = "Default labeling owner"
    ws["C2"] = "Seller"

    headers = ["Merchant SKU", "Quantity", "Prep owner", "Labeling owner",
               "Units per box", "Number of boxes", "Box length (cm)",
               "Box width (cm)", "Box height (cm)", "Box weight (kg)", "", "FNSKU", "出荷数", "セット数"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = border

    total_qty = 0
    row = 5
    for item in req.items:
        if item.plan_qty <= 0:
            continue
        pieces = item.plan_qty * item.set_size
        ws.cell(row=row, column=1, value=item.sku).border = border
        ws.cell(row=row, column=2, value=pieces).border = border
        ws.cell(row=row, column=12, value=item.fnsku).border = border
        ws.cell(row=row, column=13, value=pieces).border = border
        ws.cell(row=row, column=14, value=item.set_size).border = border
        total_qty += pieces
        row += 1

    ws.cell(row=row, column=1, value="合計")
    ws.cell(row=row, column=2, value=total_qty)
    ws.cell(row=row, column=2).font = Font(bold=True)

    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["L"].width = 16
    ws.column_dimensions["M"].width = 10
    ws.column_dimensions["N"].width = 10

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"fba_plan_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/orders")
def get_fba_orders(db: Session = Depends(get_db)):
    rows = (
        db.query(OrderHistory)
        .filter(OrderHistory.is_deleted == False)
        .filter(
            (OrderHistory.asin != None) & (OrderHistory.asin != "")
            | (OrderHistory.fnsku != None) & (OrderHistory.fnsku != "")
        )
        .order_by(OrderHistory.ordered_at.desc())
        .all()
    )
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
            "arrived_at": r.arrived_at.isoformat() if getattr(r, "arrived_at", None) else None,
            "taotaro_order_id": getattr(r, "taotaro_order_id", None),
        }
        for r in rows
    ]


@router.post("/orders/{order_id}/status")
def update_order_status(order_id: int, body: dict, db: Session = Depends(get_db)):
    row = db.query(OrderHistory).filter(OrderHistory.id == order_id).first()
    if not row:
        return {"error": "not found"}
    new_status = body.get("status", "ordered")
    if new_status not in ("ordered", "arrived", "shipped"):
        return {"error": "invalid status"}
    row.status = new_status
    if new_status == "arrived" and not row.arrived_at:
        row.arrived_at = datetime.now(timezone.utc)
    if new_status == "shipped":
        row.is_deleted = True
    db.commit()
    return {"ok": True, "status": row.status}


def _normalize_1688_url(url: str) -> str:
    if not url:
        return ""
    import re
    m = re.search(r'(\d{10,})', url)
    return m.group(1) if m else url.strip().rstrip("/")


@router.post("/import-taotaro")
async def import_taotaro_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    import openpyxl

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    try:
        content = await file.read()
        tmp.write(content)
        tmp.close()

        wb = openpyxl.load_workbook(tmp.name)
        ws = wb.active

        headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
        col_map = {}
        for i, h in enumerate(headers):
            if h:
                col_map[h] = i + 1

        taotaro_items = []
        for r in range(2, ws.max_row + 1):
            def val(col_name):
                c = col_map.get(col_name)
                return ws.cell(r, c).value if c else None

            buy_url = val("商品URL") or ""
            taotaro_items.append({
                "taotaro_order_id": str(val("オーダー番号") or ""),
                "buy_url": buy_url,
                "buy_url_id": _normalize_1688_url(buy_url),
                "name_cn": val("商品名") or "",
                "color": val("色") or "",
                "size": val("サイズ") or "",
                "qty": val("数量") or 0,
                "unit_price": val("単価") or 0,
                "arrived_at": val("到着時間") or "",
                "status_text": val("状態") or "",
            })

        orders = (
            db.query(OrderHistory)
            .filter(OrderHistory.is_deleted == False)
            .filter(OrderHistory.status != "shipped")
            .all()
        )

        matched = 0
        unmatched_items = []
        for ti in taotaro_items:
            ti_id = ti["buy_url_id"]
            if not ti_id:
                unmatched_items.append(ti)
                continue

            found = False
            for oh in orders:
                oh_id = _normalize_1688_url(oh.buy_url or "")
                if oh_id == ti_id and oh.status != "arrived":
                    oh.status = "arrived"
                    if ti["arrived_at"]:
                        try:
                            oh.arrived_at = datetime.fromisoformat(str(ti["arrived_at"]))
                        except Exception:
                            oh.arrived_at = datetime.now(timezone.utc)
                    else:
                        oh.arrived_at = datetime.now(timezone.utc)
                    oh.taotaro_order_id = ti["taotaro_order_id"]
                    matched += 1
                    found = True
                    break
            if not found:
                unmatched_items.append(ti)

        db.commit()

        return {
            "matched": matched,
            "total_excel_rows": len(taotaro_items),
            "unmatched": [
                {
                    "name_cn": u["name_cn"],
                    "color": u["color"],
                    "size": u["size"],
                    "qty": u["qty"],
                    "buy_url": u["buy_url"],
                    "taotaro_order_id": u["taotaro_order_id"],
                }
                for u in unmatched_items
            ],
        }
    finally:
        import os
        os.unlink(tmp.name)


@router.post("/sync-arrived")
def sync_arrived(db: Session = Depends(get_db)):
    """タオタロウで入庫済みになった注文を、発注済みリストに反映する。

    これまではタオタロウのサイトでExcelを落として、この画面へ
    アップロードし直していた。APIで同じものが取れるので、
    ボタン1つで済むようにする（落とす・上げるが要らない）。

    state 4＝入庫済み。1688のURLで発注済みリストと突き合わせる。
    """
    orders = (
        db.query(OrderHistory)
        .filter(OrderHistory.is_deleted == False)
        .filter(OrderHistory.status != "shipped")
        .all()
    )
    by_url = {}
    for oh in orders:
        key = _normalize_1688_url(oh.buy_url or "")
        if key:
            by_url.setdefault(key, []).append(oh)

    matched = 0
    already = 0
    unmatched = []
    seen = 0
    for page in range(1, 6):
        try:
            d = taotaro.list_orders(page=page, limit=100)
        except Exception as e:
            raise HTTPException(400, f"タオタロウから取れませんでした（{e}）")
        items = d.get("items") or []
        for o in items:
            # 4＝入庫済み。ここに来て初めて「届いた」と言える
            if o.get("state") != 4:
                continue
            seen += 1
            key = _normalize_1688_url(o.get("url") or "")
            hit = None
            for oh in by_url.get(key, []):
                if oh.status != "arrived":
                    hit = oh
                    break
            if not hit and by_url.get(key):
                # URLでは見つかったが、もう全部「到着済」になっている。
                # 「発注済みリストに見当たらず」と出すと誤解を招く
                already += 1
                continue
            if not hit:
                unmatched.append({
                    "name_cn": o.get("title") or "",
                    "color": " / ".join(
                        str(p.get("value")) for p in (o.get("sku_props") or [])),
                    "size": "",
                    "qty": o.get("quantity") or 0,
                    "buy_url": o.get("url") or "",
                    "taotaro_order_id": str(o.get("oid") or ""),
                })
                continue
            hit.status = "arrived"
            hit.arrived_at = datetime.now(timezone.utc)
            hit.taotaro_order_id = str(o.get("oid") or "")
            matched += 1
        if not d.get("has_more_pages"):
            break

    db.commit()
    return {"matched": matched, "already": already,
            "total_excel_rows": seen, "unmatched": unmatched}


@router.get("/packing/{sid:int}")
def packing(sid: int, source: str = "auto", db: Session = Depends(get_db)):
    """箱ごとの中身を返す。APIで取れるならAPIから、だめならインボイスから。

    2026-10-27版から、インボイスができると配送依頼APIに箱の情報が入る
    （箱の3辺・重量・どの箱に何が何個）。Excelを読むより確実で速い。
    取れないとき（古い便など）はインボイスから読む。
    """
    if source != "invoice":
        try:
            out = _packing_from_api(sid, db)
            if out:
                return out
        except Exception as e:
            logger.warning(f"[packing] APIから取れず、インボイスに切り替え: {e}")
    return packing_from_invoice(sid, db)


def _packing_from_api(sid: int, db: Session) -> Optional[dict]:
    """配送依頼APIの箱の情報から、箱ごとの中身を組み立てる。"""
    d = taotaro.send_order_boxes(sid)
    if not d.get("boxes_ready") or not d.get("boxes"):
        return None

    prods = {p.sku: p for p in
             db.query(Product).filter(Product.is_active == True).all()}
    by_url = {}
    for oh in db.query(OrderHistory).filter(
            OrderHistory.is_deleted == False).all():
        key = _normalize_1688_url(oh.buy_url or "")
        if key and oh.sku:
            by_url.setdefault(key, oh.sku)

    out_boxes, unknown = [], []
    for b in d["boxes"]:
        rows = []
        for it in b["items"]:
            sku = it["sku"]
            if sku not in prods:
                # 自社SKUを入れずに発注した古い注文。URLで引く
                sku = by_url.get(_normalize_1688_url(it["buy_url"]), "")
            p = prods.get(sku)
            row = {
                "sku": sku, "qty": it["qty"],
                "name": (p.name if p else "") or it["name_cn"],
                "asin": (p.asin if p else "") or it["asin"],
                "fnsku": (p.fnsku if p else "") or it["fnsku"],
            }
            if not p:
                unknown.append(row)
            rows.append(row)
        out_boxes.append({
            "box_no": b["box_no"],
            "length_cm": b["length_cm"], "width_cm": b["width_cm"],
            "height_cm": b["height_cm"], "weight_kg": b["weight_kg"],
            "items": rows,
        })

    return {
        "sid": d["sid"],
        "box_count": len(out_boxes),
        "boxes": out_boxes,
        "unknown_count": len(unknown),
        "source": "api",
        # 箱が決まっていない注文。あるとAmazonに入れる数が足りなくなる
        "unassigned": d.get("unassigned") or [],
    }


def packing_from_invoice(sid: int, db: Session = Depends(get_db)):
    """便のインボイスから、箱ごとの中身を読んで返す。

    Amazonの納品プランは「何箱か」「各箱の3辺と重量」「どの箱に
    何が何個入っているか」が要る。タオタロウの配送依頼APIには
    箱の項目が無いが、インボイスの箱シートには全部入っている。

    インボイスの明細行には商品ID（箱单と同じキー）とASINが並んでいるので、
    箱单（箱→商品ID→数量）と突き合わせれば、箱ごとのSKUが出せる。
    """
    import io as _io
    import openpyxl
    from app.services import invoice_calc

    try:
        raw = taotaro.invoice_workbook(sid)
    except taotaro.TaotaroError as e:
        raise HTTPException(400, f"インボイスを取れませんでした（{e.message}）")
    except Exception:
        raise HTTPException(400, "インボイスを取れませんでした")

    try:
        wb = openpyxl.load_workbook(_io.BytesIO(raw))
    except Exception:
        raise HTTPException(400, "インボイスを開けませんでした")

    bd = invoice_calc.parse_box_sheets(wb)
    boxes = bd.get("boxes") or {}
    contents = bd.get("contents") or []
    if not boxes or not contents:
        # 小さい便は「箱规重量」だけの簡単な形で、箱ごとの中身が無い
        raise HTTPException(
            400,
            "この便のインボイスには箱ごとの中身がありません"
            "（1箱だけの便などで起きます）。Amazonの画面で入れてください")

    # 商品ID → ASIN。インボイスの明細行から拾う
    asin_of: dict = {}
    # 商品ID → 1688のURL（インボイスのL列）。
    # ASIN列は空のことが多いので、URLでも照らせるようにする
    url_of: dict = {}
    name_of: dict = {}
    for name in wb.sheetnames:
        if name not in ("发票", "invoice", "Invoice", "INVOICE"):
            continue
        ws = wb[name]
        col_asin = None
        for r in range(1, min(ws.max_row, 30) + 1):
            for c in range(1, min(ws.max_column, 30) + 1):
                v = ws.cell(row=r, column=c).value
                if v and "ASIN" in str(v).upper():
                    col_asin = c
                    break
            if col_asin:
                break
        for r in range(1, ws.max_row + 1):
            gid = ws.cell(row=r, column=13).value      # M列＝商品ID
            if not gid:
                continue
            key = str(gid).strip()
            if key.replace(".", "").isdigit():
                key = str(int(float(key)))
            if col_asin:
                a = ws.cell(row=r, column=col_asin).value
                if a:
                    asin_of[key] = str(a).strip()
            nm = ws.cell(row=r, column=2).value
            if nm:
                name_of[key] = str(nm).strip()
            u = ws.cell(row=r, column=12).value      # L列＝1688リンク
            if u:
                url_of[key] = str(u).strip()

    # 自社の商品（SKU・FNSKU）を ASIN と 1688URL の両方で引けるようにする
    def _offer(u: str) -> str:
        """1688のURLから offer 番号だけを抜く。末尾の?以降は毎回変わる"""
        import re
        m = re.search(r"offer/(\d+)", str(u or ""))
        return m.group(1) if m else ""

    # 削除済みの行も残っているので、生きているものだけで突き合わせる
    prods = db.query(Product).filter(Product.is_active == True).all()
    by_asin, by_offer = {}, {}
    for p in prods:
        if p.asin:
            by_asin.setdefault(str(p.asin).strip().upper(), p)
        o = _offer(getattr(p, "buy_url", ""))
        if o:
            by_offer.setdefault(o, p)

    out_boxes = []
    unknown = []
    for bno in sorted(boxes.keys()):
        b = boxes[bno]
        rows = []
        for c in contents:
            if c["box"] != bno:
                continue
            gid = str(c["goods_id"])
            asin = asin_of.get(gid, "")
            p = by_asin.get(asin.upper()) if asin else None
            if not p:
                # ASINが空のことが多いので、1688のURLでも探す
                p = by_offer.get(_offer(url_of.get(gid, "")))
            if p and not asin:
                asin = p.asin or ""
            row = {
                "goods_id": gid,
                "asin": asin,
                "name": name_of.get(gid, ""),
                "qty": int(c["qty"]),
                "sku": p.sku if p else "",
                "fnsku": (p.fnsku or "") if p else "",
            }
            if not p:
                unknown.append(row)
            rows.append(row)
        out_boxes.append({
            "box_no": bno,
            "length_cm": b.get("l"), "width_cm": b.get("w"), "height_cm": b.get("h"),
            "weight_kg": b.get("actual_weight"),
            "items": rows,
        })

    return {
        "sid": sid,
        "box_count": len(out_boxes),
        "boxes": out_boxes,
        # 商品マスタに無い・ASINが空のもの。CSVには出すが印を付ける
        "unknown_count": len(unknown),
    }


# ---------- タオタロウの納品依頼Excelに、納品時の備考を入れる ----------
#
# タオタロウから落としてくるFBA指示書の備考欄には、買付のときの指示
# （全量開封検品・写真撮影・動画撮影など）がそのまま残っている。
# 納品の段階ではもう終わっている作業なので、現場が迷う。
# 商品マスタの「納品時の備考」で置き換える。
#
# 突き合わせはタオタロウの商品IDが最優先。FNSKUとASINは使えない。
# 本体と付属品を同じ商品ページとして納品するため、同じ番号が2行に出る
# （付け髭 5825743 とシール 5839353 がどちらも X001EV26HT / B0HNJHL821）。

def _norm_spec(v: str) -> str:
    """仕様の表記ゆれを吸収する。

    タオタロウの「商品情報」は「颜色: 帽子盒黑色【42*22*17cm】」のように
    項目名が前に付く。区切りも「;」「、」「,」が混ざる。
    """
    s = str(v or "").strip()
    # 「颜色:」「规格型号:」などの頭を外す（全角・半角どちらのコロンも）
    for sep in ("：", ":"):
        if sep in s:
            s = s.split(sep, 1)[1]
    for a, b in (("；", ""), (";", ""), ("、", ""), (",", ""),
                 ("　", ""), (" ", "")):
        s = s.replace(a, b)
    return s


class _NoteMatcher:
    """FBA指示書の行を、商品マスタの商品に当てる。

    上から順に試す：
      1. タオタロウの商品ID（覚えてあれば一発）
      2. 商品情報（仕様）の文字
      3. FNSKU、次にASIN。ただしその番号を持つ商品が1つだけのとき

    3を最後に回しているのは、本体と付属品が同じ番号を持つことがある
    ため（付け髭とシールがどちらも X001EV26HT）。付属品はそもそも
    候補から外し、残った中で番号が1つに決まるときだけ使う。

    2か3で当たったら、商品IDを覚えて次から一発で当たるようにする。
    """

    def __init__(self, db: Session):
        prods = (db.query(Product)
                 .filter(Product.is_active == True)
                 .filter(Product.is_component != True)
                 .all())
        self.by_tid = {str(p.taotaro_product_id): p for p in prods
                       if p.taotaro_product_id}
        self.by_spec = {}
        for p in prods:
            k = _norm_spec(p.spec)
            if k:
                self.by_spec.setdefault(k, p)
        self.by_fnsku = self._unique(prods, "fnsku")
        self.by_asin = self._unique(prods, "asin")

    @staticmethod
    def _unique(prods, field):
        seen = {}
        for p in prods:
            v = (getattr(p, field, "") or "").strip().upper()
            if v:
                seen.setdefault(v, []).append(p)
        return {k: v[0] for k, v in seen.items() if len(v) == 1}

    def find(self, tid: str, info: str, fnsku: str = "", asin: str = ""):
        p = self.by_tid.get(str(tid or "").strip())
        if p is not None:
            return p
        for cand in (self.by_spec.get(_norm_spec(info)),
                     self.by_fnsku.get((fnsku or "").strip().upper()),
                     self.by_asin.get((asin or "").strip().upper())):
            if cand is not None:
                tid = str(tid or "").strip()
                if tid and not cand.taotaro_product_id:
                    cand.taotaro_product_id = tid
                return cand
        return None


@router.post("/fill-taotaro-note")
async def fill_taotaro_note(file: UploadFile = File(...),
                            db: Session = Depends(get_db)):
    """納品依頼Excelの備考を、商品マスタの「納品時の備考」で置き換える。

    当たらなかった行は触らない（消すと、手で書いたものまで消えるため）。
    """
    import json
    import urllib.parse
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(await file.read()))
    except Exception:
        raise HTTPException(400, "Excelとして読めませんでした")
    ws = wb.active

    # 見出しの行を探す。「備考」と「FNSKU番号」が並ぶ行が表の先頭
    head_row = None
    cols = {}
    for r in range(1, min(ws.max_row, 40) + 1):
        row = {str(ws.cell(r, c).value or "").strip(): c
               for c in range(1, ws.max_column + 1)}
        if "備考" in row and any("FNSKU" in k for k in row):
            head_row, cols = r, row
            break
    if head_row is None:
        raise HTTPException(400, "「備考」の列が見つかりませんでした")

    c_note = cols["備考"]
    c_id = next((v for k, v in cols.items() if "商品ID" in k), None)
    c_info = next((v for k, v in cols.items() if "商品情報" in k), None)
    c_fnsku = next((v for k, v in cols.items() if "FNSKU" in k), None)
    c_asin = next((v for k, v in cols.items() if "ASIN" in k), None)

    matcher = _NoteMatcher(db)

    def _cell(r, c):
        return str(ws.cell(r, c).value or "").strip() if c else ""

    filled, cleared, missed = [], [], []
    for r in range(head_row + 1, ws.max_row + 1):
        tid = _cell(r, c_id)
        info = _cell(r, c_info)
        if not tid and not info:
            continue
        p = matcher.find(tid, info, _cell(r, c_fnsku), _cell(r, c_asin))
        if p is None:
            missed.append(f"{r}行目 {tid or info[:24]}")
            continue
        note = (p.delivery_note or "").strip()
        ws.cell(r, c_note).value = note or None
        (filled if note else cleared).append(p.sku)
    db.commit()          # 当たった行の商品IDを覚えておく

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    report = urllib.parse.quote(json.dumps(
        {"入れた": filled, "空にした": cleared, "当たらなかった": missed},
        ensure_ascii=False))
    # HTTPヘッダーはASCIIしか通らない。日本語のファイル名を選ばれると
    # ここで落ちるので、通らない字は落として既定の名前にする
    name = (file.filename or "taotaro.xlsx").rsplit(".", 1)[0]
    name = name.encode("ascii", "ignore").decode().strip() or "taotaro"
    return StreamingResponse(
        buf,
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"),
        headers={"Content-Disposition":
                 f'attachment; filename="{name}_note.xlsx"',
                 "X-Fill-Report": report})


@router.post("/read-taotaro-note")
async def read_taotaro_note(file: UploadFile = File(...),
                            db: Session = Depends(get_db)):
    """納品依頼Excelに手で書いてある備考を、商品マスタの
    「納品時の備考」に取り込む（fill-taotaro-note の逆）。

    一度マスタに入れておけば、次の便からは ④ で入れ直せる。
    空欄の行はマスタを触らない（消すと、過去に入れたものが消えるため）。
    商品IDで当たらず仕様で当たった行は、ついでに商品IDを覚える。
    """
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(await file.read()))
    except Exception:
        raise HTTPException(400, "Excelとして読めませんでした")
    ws = wb.active

    head_row = None
    cols = {}
    for r in range(1, min(ws.max_row, 40) + 1):
        row = {str(ws.cell(r, c).value or "").strip(): c
               for c in range(1, ws.max_column + 1)}
        if "備考" in row and any("FNSKU" in k for k in row):
            head_row, cols = r, row
            break
    if head_row is None:
        raise HTTPException(400, "「備考」の列が見つかりませんでした")

    c_note = cols["備考"]
    c_id = next((v for k, v in cols.items() if "商品ID" in k), None)
    c_info = next((v for k, v in cols.items() if "商品情報" in k), None)

    c_fnsku = next((v for k, v in cols.items() if "FNSKU" in k), None)
    c_asin = next((v for k, v in cols.items() if "ASIN" in k), None)
    matcher = _NoteMatcher(db)

    def _cell(r, c):
        return str(ws.cell(r, c).value or "").strip() if c else ""

    saved, same, missed, blank = [], [], [], 0
    for r in range(head_row + 1, ws.max_row + 1):
        note = str(ws.cell(r, c_note).value or "").strip()
        if not note:
            blank += 1
            continue
        tid = _cell(r, c_id)
        info = _cell(r, c_info)
        p = matcher.find(tid, info, _cell(r, c_fnsku), _cell(r, c_asin))
        if p is None:
            missed.append(f"{r}行目 {tid or info[:24]}：{note[:40]}")
            continue
        if (p.delivery_note or "").strip() == note:
            same.append(p.sku)
            continue
        p.delivery_note = note
        saved.append(f"{p.sku}：{note[:40]}")
    db.commit()

    return {"入れた": saved, "元から同じ": same,
            "当たらなかった": missed, "備考が空の行": blank}


# ---------- 箱の中身をAmazonへ直接入れる ----------
#
# これまでは箱の中身をCSVに落として、セラーセントラルの「輸送の詳細」に
# 手で貼っていた。同じことがSP-APIでできるので、画面を行き来せずに済ませる。
# 箱の3辺・重量・中身はタオタロウのインボイスから読む（手入力はしない）。

class SendPackingIn(BaseModel):
    plan_id: str
    sid: int


@router.post("/packing/send")
def send_packing(req: SendPackingIn, db: Session = Depends(get_db)):
    """インボイスの箱情報を、そのまま納品プランへ登録する。"""
    from app.services import amazon_api

    packed = packing(req.sid, "auto", db)
    boxes = packed.get("boxes") or []
    if not boxes:
        raise HTTPException(400, "インボイスから箱が読めませんでした")

    try:
        options = amazon_api.list_packing_options(req.plan_id)
    except Exception as e:
        raise HTTPException(400, f"梱包オプションが取れませんでした（{e}）")
    if not options:
        raise HTTPException(400, "Amazon側に梱包オプションがありません")

    # 確定済みがあればそれを使う。無ければ最初のものを確定する
    chosen = next((o for o in options
                   if (o.get("status") or "").upper() == "ACCEPTED"), None)
    if chosen is None:
        chosen = options[0]
        try:
            amazon_api.confirm_packing_option(
                req.plan_id, chosen.get("packingOptionId") or "")
        except Exception as e:
            raise HTTPException(400, f"梱包オプションを確定できませんでした（{e}）")

    # どのSKUがどのグループかはAmazonが決める。箱はグループをまたげない
    group_of = {}
    for g in (chosen.get("packingGroups") or []):
        gid = g if isinstance(g, str) else (g.get("packingGroupId") or "")
        if not gid:
            continue
        for it in amazon_api.list_packing_group_items(req.plan_id, gid):
            msku = it.get("msku") or ""
            if msku:
                group_of[msku] = gid

    groups, split, unknown = {}, [], []
    skipped = 0
    parts = {p.sku for p in db.query(Product)
             .filter(Product.is_component == True).all()}
    for b in boxes:
        items = [it for it in (b.get("items") or [])
                 if it.get("sku") and (it.get("qty") or 0) > 0
                 and it["sku"] not in parts]   # 付属品は本体に含まれる
        if not items:
            skipped += 1
            continue
        missing = [it["sku"] for it in items if not group_of.get(it["sku"])]
        if missing and len(missing) == len(items):
            # 箱まるごと今回の納品プランに入っていない。便には他の便ぶんも
            # 載るので、これは普通のこと。黙って飛ばす
            skipped += 1
            continue
        if missing:
            # プランの商品と、そうでない商品が同じ箱に入っている。
            # 現物の箱と納品内容が食い違うので、人が見るしかない
            unknown.append({"box_no": b.get("box_no"), "skus": missing})
            continue
        gids = {group_of.get(it["sku"], "") for it in items}
        if len(gids) > 1:
            # 1箱に別グループのSKUが混ざっている。Amazonは受け付けない
            split.append({"box_no": b.get("box_no"),
                          "skus": [it["sku"] for it in items]})
            continue
        gid = gids.pop()
        groups.setdefault(gid, []).append({
            "l": b.get("length_cm"), "w": b.get("width_cm"),
            "h": b.get("height_cm"), "weight_kg": b.get("weight_kg"),
            "items": [{"sku": it["sku"], "qty": it["qty"]} for it in items],
        })

    if unknown or split:
        return {"ok": False, "unknown": unknown, "split": split,
                "skipped_boxes": skipped, "sent_boxes": 0}
    if not groups:
        raise HTTPException(
            400, "この便に、納品プランの商品が入った箱がありませんでした")

    bad = [b for gs in groups.values() for b in gs
           if not all([b["l"], b["w"], b["h"], b["weight_kg"]])]
    if bad:
        raise HTTPException(
            400, "3辺か重量が入っていない箱があります（インボイスを確認してください）")

    try:
        amazon_api.set_packing_information(
            req.plan_id,
            [{"packing_group_id": gid, "boxes": gs}
             for gid, gs in groups.items()])
    except Exception as e:
        raise HTTPException(400, f"Amazonへ登録できませんでした（{e}）")

    return {"ok": True, "sent_boxes": sum(len(gs) for gs in groups.values()),
            "groups": len(groups), "skipped_boxes": skipped}


# ---------- 配送依頼に載っている商品を出す ----------
#
# 納品プランの候補を「到着済」の印で絞っていたが、到着済はタオタロウの
# 倉庫に届いただけで、FBAへ送るかどうかとは別。何を送るかは配送依頼を
# 出した時点で決まっているので、そちらで絞るほうが分かりやすい。

@router.get("/send-order/{sid:int}/skus")
def send_order_skus(sid: int, db: Session = Depends(get_db)):
    """配送依頼1件に載っている商品を、自社SKUにして返す。

    発注時に out_id（自社SKU）を入れてあればそれをそのまま使う。
    入っていない古い発注は、1688のURLで発注済みリストから引く。
    """
    try:
        d = taotaro.send_order_rows(sid)
    except Exception as e:
        raise HTTPException(400, f"配送依頼が読めませんでした（{e}）")

    prods = {p.sku: p for p in
             db.query(Product).filter(Product.is_active == True).all()}
    by_url = {}
    for oh in db.query(OrderHistory).filter(
            OrderHistory.is_deleted == False).all():
        key = _normalize_1688_url(oh.buy_url or "")
        if key and oh.sku:
            by_url.setdefault(key, oh.sku)

    # 付属品の1688 URL。付属品を本体のSKUで発注してしまうことがあり
    # （a09_1のテープを a09_1 で発注）、そのままだと本体に足される。
    #
    # ただし「URLでSKUを引く」のは間違い。色違いは同じURLを共有して
    # いるので（a05_black / a05_black_meisai / a05_black_stripe など）、
    # 全部が1つの色にまとめられて消える。
    # そこでURLは「付属品かどうか」の判定にだけ使う。
    component_offers = set()
    for pp in prods.values():
        if getattr(pp, "is_component", False):
            k = _normalize_1688_url(getattr(pp, "buy_url", "") or "")
            if k:
                component_offers.add(k)

    found, qty_of, unknown, odd = [], {}, [], []
    for r in d.get("rows") or []:
        sku = (r.get("customer_memo") or "").strip()
        offer = _normalize_1688_url(r.get("buy_url") or "")
        # 付属品のURLなら、管理番号が本体になっていても数えない
        if offer and offer in component_offers:
            continue
        if sku not in prods:
            sku = by_url.get(offer, "")
        p = prods.get(sku)
        if p is not None and not p.is_component:
            if sku not in found:
                found.append(sku)
            # 配送依頼の数は仕入単位。画面は販売単位（セット）で扱う。
            # 割り切れないときは切り捨てる。切り上げると、実際に
            # 作れない数をAmazonに伝えてしまい、受領差異になる
            # （59個・2個1セットなっ29セット。余る1個は次の便へ）
            n = int(getattr(p, "set_size", 1) or 1)
            units = int(r.get("units") or 0)
            qty_of[sku] = qty_of.get(sku, 0) + (units // n if n > 1 else units)
            if n > 1 and units % n:
                odd.append({"sku": sku, "units": units, "set_size": n,
                            "sets": units // n, "left": units % n})
        elif p is not None:
            pass                      # 付属品は本体に含まれるので数えない
        else:
            unknown.append({"name_cn": r.get("name_cn") or "",
                            "color": r.get("supplier_spec") or "",
                            "qty": r.get("units") or 0})

    return {"sid": d.get("sid"), "sn": d.get("sn"),
            "state_label": d.get("state_label") or "",
            "skus": found, "qty": qty_of, "unknown": unknown,
            # 入数で割り切れなかったもの
            "odd": odd}


# ---------- 商品ラベル（FNSKU） ----------
#
# これまではセラーセントラルで納品プランを作らないとラベルが落とせず、
# 代行会社へ渡すのが遅れていた。FNSKUはSKUごとに決まっていて納品プランとは
# 関係ないので、配送依頼に載っている商品ぶんをここで刷ってしまう。

@router.get("/send-order/{sid:int}/labels")
def send_order_labels(sid: int, skip: int = 0, db: Session = Depends(get_db)):
    """配送依頼に載っている商品の商品ラベルPDFを返す。

    skip は使いかけのラベルシートで、何枚ぶん空けてから刷るか。
    """
    from app.services.fnsku_labels import build_pdf

    try:
        d = taotaro.send_order_rows(sid)
    except Exception as e:
        raise HTTPException(400, f"配送依頼が読めませんでした（{e}）")

    prods = {p.sku: p for p in
             db.query(Product).filter(Product.is_active == True).all()}
    by_url = {}
    for oh in db.query(OrderHistory).filter(
            OrderHistory.is_deleted == False).all():
        key = _normalize_1688_url(oh.buy_url or "")
        if key and oh.sku:
            by_url.setdefault(key, oh.sku)

    items, missing = [], []
    for r in d.get("rows") or []:
        sku = (r.get("customer_memo") or "").strip()
        if sku not in prods:
            sku = by_url.get(_normalize_1688_url(r.get("buy_url") or ""), "")
        p = prods.get(sku)
        qty = int(r.get("units") or 0)
        if p is None:
            missing.append(f"{r.get('name_cn') or ''}（SKU不明）")
            continue
        if p.is_component:
            # 付属品は本体の箱の中に入るもので、単独では出品していない。
            # FNSKUが入っていても、それは本体のものを取り違えている
            continue
        if not (p.fnsku or "").strip():
            missing.append(f"{p.sku}（FNSKUが入っていません）")
            continue
        # 配送依頼の数は仕入単位（バラの個数）。ラベルは販売単位に1枚なので、
        # セット数で割る（6枚組のクリップボード240枚なら40枚）。
        # 割り切れないときは多いほうに倒す。足りないほうが現場で困る
        n = int(getattr(p, "set_size", 1) or 1)
        if n > 1:
            qty = -(-qty // n)
        # 同じSKUが複数行に分かれて載ることがあるのでまとめる
        hit = next((x for x in items if x["sku"] == p.sku), None)
        if hit:
            hit["qty"] += qty
        else:
            items.append({"fnsku": p.fnsku.strip(), "sku": p.sku,
                          "name": p.name or "", "qty": qty})

    if not items:
        raise HTTPException(
            400, "刷れる商品がありませんでした：" + "／".join(missing[:5]))

    try:
        pdf = build_pdf(items, skip=max(0, int(skip or 0)))
    except Exception as e:
        raise HTTPException(400, f"ラベルを作れませんでした（{e}）")

    import json
    import urllib.parse
    report = urllib.parse.quote(json.dumps(
        {"刷った": [f"{x['sku']} × {x['qty']}" for x in items],
         "刷れなかった": missing}, ensure_ascii=False))
    return StreamingResponse(
        io.BytesIO(pdf), media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="labels_{sid}.pdf"',
                 "X-Fill-Report": report})


# ---------- FBA指示書を便から直接取ってくる ----------
#
# 公式APIにFBA指示書は無いが、タオタロウの画面が使っているGraphQLには
# exportFBA がある。そちらから落として、そのまま備考を差し替えて返す。
# 手で落として選ぶ手間が消える。

def _fill_notes_in_workbook(wb, db: Session) -> dict:
    """開いてあるExcelの備考を、商品マスタの納品時の備考で置き換える。"""
    ws = wb.active
    head_row, cols = None, {}
    for r in range(1, min(ws.max_row, 40) + 1):
        row = {str(ws.cell(r, c).value or "").strip(): c
               for c in range(1, ws.max_column + 1)}
        if "備考" in row and any("FNSKU" in k for k in row):
            head_row, cols = r, row
            break
    if head_row is None:
        raise HTTPException(400, "「備考」の列が見つかりませんでした")

    c_note = cols["備考"]
    c_id = next((v for k, v in cols.items() if "商品ID" in k), None)
    c_info = next((v for k, v in cols.items() if "商品情報" in k), None)
    c_fnsku = next((v for k, v in cols.items() if "FNSKU" in k), None)
    c_asin = next((v for k, v in cols.items() if "ASIN" in k), None)

    matcher = _NoteMatcher(db)

    def _cell(r, c):
        return str(ws.cell(r, c).value or "").strip() if c else ""

    filled, cleared, missed = [], [], []
    for r in range(head_row + 1, ws.max_row + 1):
        tid = _cell(r, c_id)
        info = _cell(r, c_info)
        if not tid and not info:
            continue
        p = matcher.find(tid, info, _cell(r, c_fnsku), _cell(r, c_asin))
        if p is None:
            missed.append(f"{r}行目 {tid or info[:24]}")
            continue
        note = (p.delivery_note or "").strip()
        ws.cell(r, c_note).value = note or None
        (filled if note else cleared).append(p.sku)
    db.commit()          # 当たった行の商品IDを覚えておく
    return {"入れた": filled, "空にした": cleared, "当たらなかった": missed}


@router.get("/send-order/{sid:int}/instruction")
def fetch_instruction(sid: int, fill: bool = True,
                      db: Session = Depends(get_db)):
    """FBA指示書をタオタロウから落とし、備考を入れ替えて返す。"""
    import json
    import urllib.parse
    import openpyxl
    from app.services import taotaro_web

    row = db.query(OrderSettings).first()
    cookie = (getattr(row, "taotaro_web_cookie", "") or "").strip()
    if not cookie:
        raise HTTPException(
            400, "タオタロウのログイン情報が入っていません（Amazon設定で貼ってください）")

    try:
        name, raw = taotaro_web.fba_instruction_file(cookie, sid)
    except taotaro_web.WebError as e:
        raise HTTPException(400, str(e))

    report = {}
    if fill:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw))
        except Exception:
            raise HTTPException(400, "落とした指示書を開けませんでした")
        report = _fill_notes_in_workbook(wb, db)
        buf = io.BytesIO()
        wb.save(buf)
        raw = buf.getvalue()
        name = name.rsplit(".", 1)[0] + "_note.xlsx"
    # ヘッダーはASCIIしか通らない。通らない字は落とす
    name = name.encode("ascii", "ignore").decode().strip() or f"FBA_{sid}.xlsx"

    return StreamingResponse(
        io.BytesIO(raw),
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"),
        headers={"Content-Disposition": f'attachment; filename="{name}"',
                 "X-Fill-Report": urllib.parse.quote(
                     json.dumps(report, ensure_ascii=False))})


# ---------- 配送依頼をかける前の計算し直し ----------
#
# 発注した時点で必要だった数と、いま必要な数は違う。売れ行きが落ちれば
# 送りすぎになり、FBAで保管料を払って寝かせることになる。
# 倉庫にある在庫を、いまの売れ行きで航空便・船便・倉庫に振り分ける。

def _plan_rows(db: Session, products: list, ps: dict, cs) -> list:
    """振り分けに要るぶんだけ、日販とFBA在庫を出す。

    納品プランの計算をそのまま呼べると楽だが、あちらは全商品ぶんを
    取りに行く重い処理なので、ここでは必要な商品だけに絞る。
    """
    from app.core.config import settings as app_settings
    if not app_settings.SP_API_REFRESH_TOKEN:
        return []
    from app.services.amazon_api import fetch_inventory, fetch_all_sales

    inventory = fetch_inventory()
    asins = [p.asin for p in products if p.asin]
    cap = getattr(db.query(OrderSettings).first(), "order_qty_cap", 0) or 0
    s7, s15, s30, s60, s90 = fetch_all_sales(asins, cap)

    rows = []
    for p in products:
        inv = inventory.get(p.fnsku, {})
        a7 = s7.get(p.asin, 0)
        a15 = s15.get(p.asin, 0)
        a30 = s30.get(p.asin, 0)
        a60 = s60.get(p.asin, 0)
        a90 = s90.get(p.asin, 0)
        rows.append({
            "sku": p.sku or "",
            "daily": weighted_daily(a7, a15, a30, a60, a90, cs),
            "growth": growth_mult(a7, a15, a90, cs),
            "fba_available": inv.get("available", 0),
            "fba_inbound": inv.get("inbound", 0),
            "fba_processing": inv.get("processing", 0),
        })
    return rows


@router.get("/restock-split")
def restock_split(db: Session = Depends(get_db)):
    """倉庫の在庫を航空便・船便・倉庫に振り分けて返す。"""
    from app.services import restock_split as rs

    if not taotaro.is_configured():
        raise HTTPException(400, "タオタロウのトークンが未設定です")

    try:
        stock = rs.warehouse_stock(db)
    except Exception as e:
        raise HTTPException(400, f"倉庫の在庫が取れませんでした（{e}）")
    if not stock:
        return {"items": [], "note": "倉庫に、まだ便に入っていない在庫がありません"}

    settings_row = db.query(OrderSettings).first()
    ps = _build_settings(settings_row)
    cs = _build_calc_settings(settings_row)
    lt_sea = (ps["lt_shipping_request"] + ps["lt_sea_to_fba"])
    lt_air = (ps["lt_shipping_request"] + ps["lt_air_to_fba"])
    target = ((ps.get("fba_target_days") or 0)
              or (ps["free_storage_days"] - ps["lt_order_to_warehouse"]))
    target += calc_sale_extra_days(cs)

    # 日販とFBA在庫は、納品プランと同じ計算をそのまま使う（二重に持たない）
    skus = set(stock.keys())
    prods = [p for p in db.query(Product)
             .filter(Product.is_active == True).all() if p.sku in skus]
    items = _plan_rows(db, prods, ps, cs)

    # 同じSKUで楽天にも出している商品は、中国の在庫が1つの山になる。
    # 先に楽天ぶんを取り置かないと、楽天の在庫が切れる
    rk = rs.rakuten_need(db, set(stock.keys()), lt_sea)

    return {
        "items": rs.split(stock, items, lt_sea, lt_air, target, rk),
        "lt_sea": lt_sea, "lt_air": lt_air, "target_days": target,
        "rakuten_count": len(rk),
    }
