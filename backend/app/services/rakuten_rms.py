"""
楽天RMS API サービス
受注データを取得してバリエーション別30日販売数を集計する
"""
import base64
import json
from datetime import datetime, timedelta
from typing import Optional
import httpx


RMS_BASE = "https://api.rms.rakuten.co.jp/es"
BATCH_SIZE = 10  # getOrder の1回あたりの件数


def _auth_header(service_secret: str, license_key: str) -> dict:
    token = base64.b64encode(f"{service_secret}:{license_key}".encode()).decode()
    return {"Authorization": f"ESA {token}"}


async def _process_page(
    headers: dict,
    order_numbers: list,
    sku_daily: dict,
    now: datetime,
) -> None:
    """注文番号リストの詳細を取得してsku_dailyに集計（メモリ節約のため都度処理）"""
    for i in range(0, len(order_numbers), BATCH_SIZE):
        batch = order_numbers[i:i + BATCH_SIZE]
        detail_body = {"orderNumberList": batch}
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"{RMS_BASE}/2.0/order/getOrder",
                headers={**headers, "Content-Type": "application/json; charset=utf-8"},
                content=json.dumps(detail_body, ensure_ascii=False).encode("utf-8"),
            )
            if not res.is_success:
                continue
            detail_data = res.json()

        for order in detail_data.get("orderModelList", []):
            if order.get("orderProgress", 0) == 900:  # キャンセル除外
                continue
            order_date_str = order.get("orderDatetime", "")
            try:
                order_date = datetime.fromisoformat(order_date_str.replace("+0900", "+09:00"))
            except Exception:
                order_date = now - timedelta(days=15)

            day_key = order_date.strftime("%Y-%m-%d")
            for package in order.get("PackageModelList", []):
                for item in package.get("ItemModelList", []):
                    sku = item.get("manageNumber", "") or item.get("itemNumber", "")
                    if not sku:
                        continue
                    qty = item.get("units", 1) or 1
                    if sku not in sku_daily:
                        sku_daily[sku] = {}
                    sku_daily[sku][day_key] = sku_daily[sku].get(day_key, 0) + qty


async def fetch_sales_by_sku(
    service_secret: str,
    license_key: str,
    days: int = 60,
) -> dict:
    """
    過去N日間の受注データを取得し、SKUごとの販売数を返す。
    楽天APIは63日以内の制限があるため60日ずつ分割してリクエストする。
    注文番号は全件メモリに溜めず、ページ取得のたびに即時 getOrder 処理してメモリを節約する。
    """
    headers = _auth_header(service_secret, license_key)
    now = datetime.now()
    cutoff_recent = now - timedelta(days=30)
    cutoff_prev   = now - timedelta(days=60)

    sku_daily: dict[str, dict] = {}
    seen_orders: set[str] = set()  # 重複注文番号の除去

    MAX_DAYS = 60
    fetched_days = 0
    while fetched_days < days:
        chunk = min(MAX_DAYS, days - fetched_days)
        chunk_end   = now - timedelta(days=fetched_days)
        chunk_start = now - timedelta(days=fetched_days + chunk)

        # ページネーションで全ページ取得しながら都度getOrder処理
        page = 1
        while True:
            search_body = {
                "dateType": 1,
                "startDatetime": chunk_start.strftime("%Y-%m-%dT00:00:00+0900"),
                "endDatetime":   chunk_end.strftime("%Y-%m-%dT23:59:59+0900"),
                "PaginationRequestModel": {
                    "requestRecordsAmount": 100,
                    "requestPage": page,
                },
            }
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.post(
                    f"{RMS_BASE}/2.0/order/searchOrder",
                    headers={**headers, "Content-Type": "application/json; charset=utf-8"},
                    content=json.dumps(search_body, ensure_ascii=False).encode("utf-8"),
                )
                if not res.is_success:
                    raise Exception(f"searchOrder HTTP {res.status_code}: {res.text}")
                data = res.json()

            raw_list = data.get("orderNumberList") or []
            page_numbers = []
            for item in raw_list:
                num = item if isinstance(item, str) else (
                    item.get("orderNumber") or item.get("order_number") or item.get("id") or ""
                )
                num = str(num)
                if num and num not in seen_orders:
                    seen_orders.add(num)
                    page_numbers.append(num)

            if page_numbers:
                await _process_page(headers, page_numbers, sku_daily, now)

            pagination = data.get("PaginationResponseModel") or {}
            if page >= pagination.get("totalPages", 1):
                break
            page += 1

        fetched_days += chunk

    # 集計
    sku_sales: dict[str, dict] = {}
    for sku, daily in sku_daily.items():
        recent = prev = total = 0
        for day_str, qty in daily.items():
            try:
                d = datetime.strptime(day_str, "%Y-%m-%d")
            except Exception:
                continue
            total += qty
            if d >= cutoff_recent:
                recent += qty
            elif d >= cutoff_prev:
                prev += qty
        sku_sales[sku] = {
            "recent": recent,
            "prev": prev,
            "total_90": total,
            "stockout_days": 0,
        }

    return sku_sales


async def test_connection(service_secret: str, license_key: str) -> dict:
    """接続テスト - 注文検索APIで確認"""
    headers = _auth_header(service_secret, license_key)
    now = datetime.now()
    body = {
        "dateType": 1,
        "startDatetime": (now - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+0900"),
        "endDatetime": now.strftime("%Y-%m-%dT23:59:59+0900"),
        "orderProgressList": [100],
        "PaginationRequestModel": {"requestRecordsAmount": 1, "requestPage": 1},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                f"{RMS_BASE}/2.0/order/searchOrder",
                headers={**headers, "Content-Type": "application/json; charset=utf-8"},
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            )
        if res.status_code == 200:
            return {"ok": True, "status": res.status_code}
        else:
            return {"ok": False, "status": res.status_code, "detail": res.text[:200]}
    except Exception as e:
        return {"ok": False, "status": 0, "detail": str(e)}
