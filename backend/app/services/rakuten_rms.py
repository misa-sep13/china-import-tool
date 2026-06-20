"""
楽天RMS API サービス
受注データを取得してバリエーション別30日販売数を集計する
"""
import base64
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import httpx


RMS_BASE = "https://api.rms.rakuten.co.jp/es"
BATCH_SIZE = 100      # getOrder の1回あたりの件数（RMSの上限）
GETORDER_CONCURRENCY = 6  # getOrder の並列数


def _auth_header(service_secret: str, license_key: str) -> dict:
    token = base64.b64encode(f"{service_secret}:{license_key}".encode()).decode()
    return {"Authorization": f"ESA {token}"}


async def _process_batch(
    headers: dict,
    batch: list,
    sku_daily: dict,
    now: datetime,
    sem: asyncio.Semaphore,
) -> None:
    """1バッチ分(最大BATCH_SIZE件)の注文詳細をgetOrderで取得しsku_dailyに集計。
    並列実行用。HTTP取得時のみawaitし、sku_dailyへの更新はawaitを挟まないため
    asyncio(単一スレッド)では共有dictを直接更新しても安全。"""
    async with sem:
        detail_body = {"orderNumberList": batch, "version": 10}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.post(
                    f"{RMS_BASE}/2.0/order/getOrder",
                    headers={**headers, "Content-Type": "application/json; charset=utf-8"},
                    content=json.dumps(detail_body, ensure_ascii=False).encode("utf-8"),
                )
                if not res.is_success:
                    return
                detail_data = res.json()
        except Exception:
            return

    for order in detail_data.get("OrderModelList", []):
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
                    qty = item.get("units", 1) or 1
                    # version7以降: SkuModelList の variantId を優先
                    sku_list = item.get("SkuModelList") or []
                    skus = [s.get("variantId", "") for s in sku_list if s.get("variantId")]
                    if not skus:
                        skus = [item.get("manageNumber", "") or item.get("itemNumber", "")]
                    for sku in skus:
                        if not sku:
                            continue
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
    from datetime import timezone
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))
    cutoff_recent = now - timedelta(days=30)
    cutoff_prev   = now - timedelta(days=60)

    sku_daily: dict[str, dict] = {}
    seen_orders: set[str] = set()  # 重複注文番号の除去
    all_order_numbers: list[str] = []

    # 1) searchOrderで全注文番号を収集（軽量・順次）
    MAX_DAYS = 60
    fetched_days = 0
    while fetched_days < days:
        chunk = min(MAX_DAYS, days - fetched_days)
        chunk_end   = now - timedelta(days=fetched_days)
        chunk_start = now - timedelta(days=fetched_days + chunk)

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

            for item in data.get("orderNumberList") or []:
                num = item if isinstance(item, str) else (
                    item.get("orderNumber") or item.get("order_number") or item.get("id") or ""
                )
                num = str(num)
                if num and num not in seen_orders:
                    seen_orders.add(num)
                    all_order_numbers.append(num)

            pagination = data.get("PaginationResponseModel") or {}
            if page >= pagination.get("totalPages", 1):
                break
            page += 1

        fetched_days += chunk

    # 2) getOrderをBATCH_SIZE件ずつ並列取得してsku_dailyへ集計
    sem = asyncio.Semaphore(GETORDER_CONCURRENCY)
    batches = [all_order_numbers[i:i + BATCH_SIZE] for i in range(0, len(all_order_numbers), BATCH_SIZE)]
    await asyncio.gather(*[_process_batch(headers, b, sku_daily, now, sem) for b in batches])

    # 3) 集計
    sku_sales: dict[str, dict] = {}
    for sku, daily in sku_daily.items():
        recent = prev = total = 0
        for day_str, qty in daily.items():
            try:
                d = datetime.strptime(day_str, "%Y-%m-%d").date()
            except Exception:
                continue
            total += qty
            # cutoffはタイムゾーン付き(JST)なので .date() 同士で比較する
            if d >= cutoff_recent.date():
                recent += qty
            elif d >= cutoff_prev.date():
                prev += qty
        sku_sales[sku] = {
            "recent": recent,
            "prev": prev,
            "total_90": total,
            "stockout_days": 0,
        }

    return sku_sales


async def fetch_inventory_from_rms(
    service_secret: str,
    license_key: str,
    items: list[dict],  # [{"manage_number": "y49", "variant_id": "y49_pink2"}, ...]
) -> dict:
    """
    RMSから在庫数を一括取得する。
    戻り値: {"{variantId}": quantity, ...}
    """
    headers = {**_auth_header(service_secret, license_key), "Content-Type": "application/json"}
    result = {}

    # 1000件ずつ分割してリクエスト
    for i in range(0, len(items), 1000):
        chunk = items[i:i + 1000]
        body = json.dumps({
            "inventories": [
                {"manageNumber": item["manage_number"], "variantId": item["variant_id"]}
                for item in chunk
            ]
        }, ensure_ascii=False).encode("utf-8")

        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"{RMS_BASE}/2.0/inventories/bulk-get",
                headers=headers,
                content=body,
            )
            if not res.is_success:
                raise Exception(f"bulk-get HTTP {res.status_code}: {res.text[:200]}")
            data = res.json()

        inventories = data.get("inventories", [])
        for inv in inventories:
            result[inv["variantId"]] = inv["quantity"]

    return result


async def push_inventory_to_rms(
    service_secret: str,
    license_key: str,
    items: list[dict],  # [{"manage_number": "y49", "variant_id": "y49_pink2", "quantity": 16}, ...]
) -> dict:
    """
    在庫数をRMSに一括反映する。
    items: manage_number, variant_id, quantity を含む辞書のリスト
    戻り値: {"ok": int, "fail": int, "errors": [...]}
    """
    headers = {**_auth_header(service_secret, license_key), "Content-Type": "application/json"}
    ok = 0
    fail = 0
    errors = []

    import asyncio

    async def _push_one(client, item):
        manage_number = item["manage_number"]
        variant_id = item["variant_id"]
        quantity = item["quantity"]
        url = f"{RMS_BASE}/2.0/inventories/manage-numbers/{manage_number}/variants/{variant_id}"
        body = json.dumps({"mode": "ABSOLUTE", "quantity": quantity}, ensure_ascii=False).encode("utf-8")
        for attempt in range(4):
            try:
                res = await client.put(url, headers=headers, content=body)
                if res.status_code == 204:
                    return ("ok", variant_id, None)
                elif res.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return ("fail", variant_id, f"HTTP {res.status_code}: {res.text[:100]}")
            except Exception as e:
                return ("fail", variant_id, str(e))
        return ("fail", variant_id, "429 too many retries")

    async with httpx.AsyncClient(timeout=30) as client:
        # 10件ずつ並列送信
        for i in range(0, len(items), 10):
            batch = items[i:i + 10]
            results = await asyncio.gather(*[_push_one(client, item) for item in batch])
            for status, sku, detail in results:
                if status == "ok":
                    ok += 1
                else:
                    fail += 1
                    errors.append({"sku": sku, "detail": detail})

    return {"ok": ok, "fail": fail, "errors": errors}


async def fetch_recent_orders(
    service_secret: str,
    license_key: str,
    minutes: int = 3,
) -> dict:
    """
    直近N分の注文を取得し、SKUごとの販売数量を返す。
    戻り値: {"y76_black": 2, "y48_pink-s": 1, ...}
    """
    headers = _auth_header(service_secret, license_key)
    from datetime import timezone
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))
    start = now - timedelta(minutes=minutes)
    body = {
        "dateType": 1,
        "startDatetime": start.strftime("%Y-%m-%dT%H:%M:%S+0900"),
        "endDatetime":   now.strftime("%Y-%m-%dT%H:%M:%S+0900"),
        "PaginationRequestModel": {"requestRecordsAmount": 100, "requestPage": 1},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{RMS_BASE}/2.0/order/searchOrder",
            headers={**headers, "Content-Type": "application/json; charset=utf-8"},
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
        if not res.is_success:
            return {}, []
        data = res.json()

    order_numbers = []
    for item in (data.get("orderNumberList") or []):
        num = item if isinstance(item, str) else (
            item.get("orderNumber") or item.get("order_number") or ""
        )
        if num:
            order_numbers.append(str(num))

    if not order_numbers:
        return {}, []

    # {order_number: {sku: qty}} 形式で返す（呼び出し側で重複排除できるよう注文番号単位）
    orders_by_num: dict[str, dict[str, int]] = {}
    for i in range(0, len(order_numbers), BATCH_SIZE):
        batch = order_numbers[i:i + BATCH_SIZE]
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"{RMS_BASE}/2.0/order/getOrder",
                headers={**headers, "Content-Type": "application/json; charset=utf-8"},
                content=json.dumps({"orderNumberList": batch, "version": 10}, ensure_ascii=False).encode("utf-8"),
            )
            if not res.is_success:
                continue
            detail = res.json()
        for order in detail.get("OrderModelList", []):
            if order.get("orderProgress", 0) == 900:
                continue
            order_num = str(order.get("orderNumber") or "")
            sku_map: dict[str, int] = {}
            for package in order.get("PackageModelList", []):
                for item in package.get("ItemModelList", []):
                    qty = item.get("units", 1) or 1
                    sku_list = item.get("SkuModelList") or []
                    skus = [s.get("variantId", "") for s in sku_list if s.get("variantId")]
                    if not skus:
                        skus = [item.get("manageNumber", "") or item.get("itemNumber", "")]
                    for sku in skus:
                        if not sku:
                            continue
                        sku_map[sku] = sku_map.get(sku, 0) + qty
            if order_num and sku_map:
                orders_by_num[order_num] = sku_map

    # searchOrderで取得した注文番号リストも返す（重複排除用）
    return orders_by_num, order_numbers


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
