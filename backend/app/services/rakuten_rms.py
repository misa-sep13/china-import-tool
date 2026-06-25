"""
楽天RMS API サービス
受注データを取得してバリエーション別30日販売数を集計する
"""
import os
import base64
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import httpx


RMS_BASE = "https://api.rms.rakuten.co.jp/es"
BATCH_SIZE = 100      # getOrder の1回あたりの件数（RMSの上限）
GETORDER_CONCURRENCY = 6  # getOrder の並列数

# 楽天RMSへの在庫書き込み（push）の有効/無効。
# 本番連動を正式に開始するまでは書き込まない（デフォルト無効＝安全側）。
# china-import-tool側の値で楽天の実在庫を誤って上書きする事故を防ぐため。
# 本番連動を始めるときに環境変数 RMS_PUSH_ENABLED=true を設定して有効化する。
RMS_PUSH_ENABLED = os.environ.get("RMS_PUSH_ENABLED", "false").lower() == "true"


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


async def _collect_order_numbers(
    headers: dict,
    range_start: datetime,
    range_end: datetime,
) -> list[str]:
    """指定期間[range_start, range_end]の注文番号を searchOrder で収集して返す。
    楽天APIは1リクエスト最大63日のため60日ずつに分割する。"""
    seen_orders: set[str] = set()
    all_order_numbers: list[str] = []

    MAX_DAYS = 60
    cursor_end = range_end
    while cursor_end > range_start:
        cursor_start = max(range_start, cursor_end - timedelta(days=MAX_DAYS))
        page = 1
        while True:
            search_body = {
                "dateType": 1,
                "startDatetime": cursor_start.strftime("%Y-%m-%dT%H:%M:%S+0900"),
                "endDatetime":   cursor_end.strftime("%Y-%m-%dT%H:%M:%S+0900"),
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

        cursor_end = cursor_start

    return all_order_numbers


def ss_period_for(d: datetime) -> Optional[tuple]:
    """指定日が属する直近（過去）のSS期間を返す。
    スーパーセールは 3/6/9/12月の 4日20:00 〜 11日02:00（JST）固定。
    戻り値: (period_key:"YYYY-MM", start:datetime, end:datetime) / 無ければNone"""
    from datetime import timezone as _tz
    jst = _tz(timedelta(hours=9))
    year = d.year
    # SS開催月（降順）で、dより前に始まったSSのうち最も新しいものを探す
    candidates = []
    for y in (year, year - 1):
        for m in (12, 9, 6, 3):
            start = datetime(y, m, 4, 20, 0, 0, tzinfo=jst)
            end = datetime(y, m, 11, 2, 0, 0, tzinfo=jst)
            candidates.append((f"{y}-{m:02d}", start, end))
    candidates.sort(key=lambda c: c[1], reverse=True)
    for key, start, end in candidates:
        if start <= d:
            return (key, start, end)
    return None


async def fetch_ss_sales(
    service_secret: str,
    license_key: str,
    ss_start: datetime,
    ss_end: datetime,
) -> dict:
    """SS期間[ss_start, ss_end]のSKU別販売数を集計して返す。
    戻り値: {sku: qty, ...}"""
    headers = _auth_header(service_secret, license_key)
    order_numbers = await _collect_order_numbers(headers, ss_start, ss_end)

    sku_daily: dict[str, dict] = {}
    sem = asyncio.Semaphore(GETORDER_CONCURRENCY)
    batches = [order_numbers[i:i + BATCH_SIZE] for i in range(0, len(order_numbers), BATCH_SIZE)]
    now = datetime.now()
    await asyncio.gather(*[_process_batch(headers, b, sku_daily, now, sem) for b in batches])

    # 期間内の合計のみ集計（_process_batchは注文日で日別格納するが、収集対象が期間内注文のため全合算でよい）
    sku_qty: dict[str, int] = {}
    for sku, daily in sku_daily.items():
        sku_qty[sku] = sum(daily.values())
    return sku_qty


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
    戻り値: {"{db_sku}": quantity, ...}
    db_skuはitemsのvariant_idと一致する（RMSのvariantIdと異なる場合あり）
    """
    headers = {**_auth_header(service_secret, license_key), "Content-Type": "application/json"}
    result = {}

    # 1000件ずつ分割してリクエスト
    for i in range(0, len(items), 1000):
        chunk = items[i:i + 1000]
        # RMSへのリクエスト: manageNumber単品商品はvariantIdがSKUと異なる場合がある
        # variant_id == manage_numberの場合（s08-2など）、RMSはvariantIdを無視してmanageNumber配下を全返却する
        # そのためmanageNumberが同一でvariant_idが異なるケースを追跡するマップを作成
        # key: (manageNumber, variantId_sent) -> db_sku
        req_map: dict[tuple, str] = {}
        rms_items = []
        for item in chunk:
            mn = item["manage_number"]
            vi = item["variant_id"]
            req_map[(mn, vi)] = vi  # デフォルトはvariant_idをDBのSKUとして使う
            rms_items.append({"manageNumber": mn, "variantId": vi})

        body = json.dumps({"inventories": rms_items}, ensure_ascii=False).encode("utf-8")

        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"{RMS_BASE}/2.0/inventories/bulk-get",
                headers=headers,
                content=body,
            )
            if not res.is_success:
                raise Exception(f"bulk-get HTTP {res.status_code}: {res.text[:200]}")
            data = res.json()

        # manageNumberとvariantIdの両方でDBのSKUを逆引きできるようにする
        # variant_id == manage_numberのケース（s08-2など）はmanageNumberでマッチ
        mn_to_db_sku: dict[str, str] = {}
        for item in chunk:
            mn = item["manage_number"]
            vi = item["variant_id"]
            if vi == mn:
                mn_to_db_sku[mn] = vi

        for inv in data.get("inventories", []):
            rms_mn = inv.get("manageNumber", "")
            rms_vi = inv.get("variantId", "")
            qty = inv["quantity"]
            # まずvariantIdで直接マッチ（通常ケース: y49_pink2など）
            if (rms_mn, rms_vi) in req_map:
                result[req_map[(rms_mn, rms_vi)]] = qty
            # variantIdがリクエストと異なるがmanageNumberが一致するケース（s08-2など）
            elif rms_mn in mn_to_db_sku:
                result[mn_to_db_sku[rms_mn]] = qty
            else:
                result[rms_vi] = qty

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
    # 本番連動を開始するまでは楽天RMSへ書き込まない（RMS_PUSH_ENABLED=false）。
    # 書き込もうとした内容はログに残し、実際のPUTはスキップする。
    if not RMS_PUSH_ENABLED:
        import logging
        logging.getLogger("rakuten").warning(
            f"[RMS push 無効化中] 楽天への在庫書き込みをスキップしました（{len(items)}件）。"
            f"有効化するには環境変数 RMS_PUSH_ENABLED=true を設定してください。"
        )
        return {"ok": 0, "fail": 0, "errors": [], "skipped": len(items), "push_disabled": True}

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
) -> tuple[dict, list, set]:
    """
    直近N分の注文を取得し、注文番号別のSKU数量とキャンセル注文番号を返す。
    戻り値: (orders_by_num, order_numbers, cancelled_order_numbers)
      orders_by_num: {order_number: {sku: qty}} — キャンセル含む全注文のSKU数量
      order_numbers: searchOrderが返した全注文番号リスト
      cancelled_order_numbers: orderProgress==900のキャンセル注文番号セット
    """
    headers = _auth_header(service_secret, license_key)
    from datetime import timezone
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))
    start = now - timedelta(minutes=minutes)

    order_numbers = []
    page = 1
    while True:
        body = {
            "dateType": 1,
            "startDatetime": start.strftime("%Y-%m-%dT%H:%M:%S+0900"),
            "endDatetime":   now.strftime("%Y-%m-%dT%H:%M:%S+0900"),
            "PaginationRequestModel": {"requestRecordsAmount": 100, "requestPage": page},
        }
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"{RMS_BASE}/2.0/order/searchOrder",
                headers={**headers, "Content-Type": "application/json; charset=utf-8"},
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            )
            if not res.is_success:
                break
            data = res.json()

        page_orders = []
        for item in (data.get("orderNumberList") or []):
            num = item if isinstance(item, str) else (
                item.get("orderNumber") or item.get("order_number") or ""
            )
            if num:
                page_orders.append(str(num))

        order_numbers.extend(page_orders)

        if len(page_orders) < 100 or page >= 10:
            break
        page += 1

    if not order_numbers:
        return {}, [], set()

    orders_by_num: dict[str, dict[str, int]] = {}
    cancelled_order_numbers: set[str] = set()
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
            order_num = str(order.get("orderNumber") or "")
            is_cancelled = order.get("orderProgress", 0) == 900
            if is_cancelled:
                cancelled_order_numbers.add(order_num)
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

    return orders_by_num, order_numbers, cancelled_order_numbers


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
