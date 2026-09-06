from typing import Dict, List, Optional
import urllib.parse
import urllib.request
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.core.config import settings

_token_cache = {"token": None, "expires_at": 0}

# サーバー側キャッシュ
_cache: Dict[str, dict] = {}
# 売上データ: 4時間。ウォームアップcronは毎時50分の設定だが、GitHub Actionsの
# スケジュール実行は混雑時に遅延・スキップされる（実測で最大3時間43分の空白があり、
# TTL70分では日中でもキャッシュ切れ→画面を開くと7分待ちになっていた）。
# 日販は数時間で大きく動かないため、発注判断への影響よりも待ち時間の解消を優先する。
_CACHE_TTL = 14400
_CACHE_TTL_LONG = 86400 # 画像など: 1日
# 在庫: 5分。売れたり納品されたりで刻々と変わるうえ、取得は1リクエスト数秒で済む。
# 売上（220リクエスト・約7分）と同じTTLにすると、在庫まで数時間古いままになる。
_CACHE_TTL_INVENTORY = 300

def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() < entry["expires_at"]:
        return entry["value"]
    return None

def _cache_set(key: str, value):
    _cache[key] = {"value": value, "expires_at": time.time() + _CACHE_TTL}

def _get_access_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]

    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": settings.SP_API_REFRESH_TOKEN,
        "client_id": settings.SP_API_LWA_APP_ID,
        "client_secret": settings.SP_API_LWA_CLIENT_SECRET,
    }).encode()

    req = urllib.request.Request(
        "https://api.amazon.com/auth/o2/token",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req) as res:
        result = json.loads(res.read())

    _token_cache["token"] = result["access_token"]
    _token_cache["expires_at"] = time.time() + result["expires_in"] - 60
    return _token_cache["token"]

def _call_sp_api(path: str) -> dict:
    token = _get_access_token()
    base_url = "https://sellingpartnerapi-fe.amazon.com"
    req = urllib.request.Request(
        base_url + path,
        method="GET",
        headers={
            "x-amz-access-token": token,
            "Content-Type": "application/json",
        }
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # レート制限: 指数バックオフ(2,4,8,16,32秒)で粘る
                time.sleep(2 ** (attempt + 1))
                continue
            body = e.read().decode()
            raise Exception(f"HTTP {e.code}: {body}")
    raise Exception("SP-API rate limited after retries: " + path)

def fetch_inventory() -> Dict[str, dict]:
    cached = _cache_get("inventory")
    if cached is not None:
        return cached

    mp = "A1VC38T7YXB528"
    result = {}
    next_token = None

    while True:
        params = urllib.parse.urlencode({
            "granularityType": "Marketplace",
            "granularityId": mp,
            "marketplaceIds": mp,
            # details=true を付けないと inventoryDetails（販売可能数・納品中・作業中の内訳）が
            # 返らず、totalQuantity しか取れない（納品中が常に0になる原因だった）
            "details": "true",
            **({"nextToken": next_token} if next_token else {}),
        })
        data = _call_sp_api(f"/fba/inventory/v1/summaries?{params}")

        for item in data.get("payload", {}).get("inventorySummaries", []):
            fnsku = item.get("fnSku", "")
            asin = item.get("asin", "")
            details = item.get("inventoryDetails") or {}
            # fulfillableQuantity=0（売り切れ）は正しい0として扱う（or判定だと総数に化ける）
            fulfillable = details.get("fulfillableQuantity")
            inbound = (
                (details.get("inboundWorkingQuantity") or 0)
                + (details.get("inboundShippedQuantity") or 0)
                + (details.get("inboundReceivingQuantity") or 0)
            )
            # reservedQuantityは中身で意味が違うので分けて扱う。
            #   pendingCustomerOrder : 注文が入り出荷準備中（≒売れた分）
            #   pendingTransshipment : FC間を移動中。すでにFBAにある在庫
            #   fcProcessing         : 倉庫内で作業中（セラーセントラルの「入出荷作業中」）
            # 合計を processing として扱うと、移動中の在庫まで「まだ売れない」扱いになり
            # 実際には在庫があるのに発注推奨が出てしまう。
            rq = details.get("reservedQuantity") or {}
            pending_order = rq.get("pendingCustomerOrderQuantity") or 0
            transshipment = rq.get("pendingTransshipmentQuantity") or 0
            fc_processing = rq.get("fcProcessingQuantity") or 0
            result[fnsku] = {
                "fnsku": fnsku,
                "asin": asin,
                "sku": item.get("sellerSku", ""),
                "name": item.get("productName", ""),
                "available": fulfillable if fulfillable is not None else item.get("totalQuantity", 0),
                "inbound": inbound,
                # FC間移動中は在庫としてすぐ戻るので、販売可能の側に含める
                "transshipment": transshipment,
                "processing": fc_processing,
                "pending_order": pending_order,
            }

        next_token = data.get("pagination", {}).get("nextToken")
        if not next_token:
            break

    # 在庫は短命。売上と同じ4時間だと、納品や販売が反映されず画面がずれる
    _cache["inventory"] = {"value": result, "expires_at": time.time() + _CACHE_TTL_INVENTORY}
    return result

def fetch_item_name(asin: str) -> str:
    mp = "A1VC38T7YXB528"
    try:
        params = urllib.parse.urlencode({"marketplaceIds": mp})
        data = _call_sp_api(f"/catalog/2022-04-01/items/{asin}?{params}")
        summaries = data.get("summaries", [])
        if summaries:
            return summaries[0].get("itemName", "")
    except Exception:
        pass
    return ""


def fetch_catalog_info(asin_list: List[str]) -> Dict[str, dict]:
    """商品画像（1枚目）とレビュー評価をASINごとに取得"""
    cache_key = "catalog_info"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    mp = "A1VC38T7YXB528"

    def _fetch_one(asin: str) -> tuple:
        try:
            params = urllib.parse.urlencode({
                "marketplaceIds": mp,
                "includedData": "images,summaries",
            })
            data = _call_sp_api(f"/catalog/2022-04-01/items/{asin}?{params}")
            # 画像（1枚目のMAIN画像）
            image_url = None
            for img_set in data.get("images", []):
                for img in img_set.get("images", []):
                    if img.get("variant") == "MAIN":
                        image_url = img.get("link")
                        break
                if image_url:
                    break
            # summariesからparentAsinも取得
            rating = None
            rating_count = None
            parent_asin = None
            for summary in data.get("summaries", []):
                if summary.get("marketplaceId") == mp:
                    rating = summary.get("averageCustomerReview")
                    rating_count = summary.get("numberOfCustomerReviews")
                    parent_asin = summary.get("parentAsin")
                    break
            return asin, {"image_url": image_url, "rating": rating, "rating_count": rating_count, "parent_asin": parent_asin}
        except Exception:
            return asin, {"image_url": None, "rating": None, "rating_count": None}

    result = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_fetch_one, asin): asin for asin in asin_list}
        for f in as_completed(futures):
            asin, val = f.result()
            result[asin] = val

    _cache[cache_key] = {"value": result, "expires_at": time.time() + _CACHE_TTL_LONG}
    return result

def _fetch_sales_one(asin: str, days: int, end_dt, order_qty_cap: int = 0) -> tuple:
    """1ASIN×1期間の日販を取得。失敗時はNoneを返す（0.0を返すと「売れていない」と
    区別できず、レート制限失敗が日販の過小評価→発注推奨から漏れる事故になるため）
    order_qty_cap>0の場合、日別データを取得して異常値（中央値×3以上）をキャップする。"""
    from datetime import timedelta
    mp = "A1VC38T7YXB528"
    start = end_dt - timedelta(days=days)
    granularity = "Day" if order_qty_cap and order_qty_cap > 0 else "Total"
    try:
        params = urllib.parse.urlencode({
            "marketplaceIds": mp,
            "interval": f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}--{end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "granularity": granularity,
            "asin": asin,
        })
        data = _call_sp_api(f"/sales/v1/orderMetrics?{params}")
        daily_units = [m.get("unitCount", 0) for m in data.get("payload", [])]
        if granularity == "Day" and len(daily_units) > 2:
            sorted_units = sorted(daily_units)
            median = sorted_units[len(sorted_units) // 2]
            cap = max(order_qty_cap, median * 3, 1)
            daily_units = [min(u, cap) for u in daily_units]
        units = sum(daily_units)
        return asin, round(units / days, 4)
    except Exception:
        return asin, None


def fetch_all_sales(asin_list: List[str], order_qty_cap: int = 0) -> tuple:
    """7/15/30/60/90日の売上を全ASIN×全期間で並列一括取得。now()を1回固定して集計期間のブレをなくす"""
    from datetime import datetime, timezone
    periods = [7, 15, 30, 60, 90]

    cache_suffix = f"_cap{order_qty_cap}" if order_qty_cap else ""

    # キャッシュチェック
    cached_results = {}
    missing_periods = set()
    for d in periods:
        cached = _cache_get(f"sales_{d}{cache_suffix}")
        if cached is not None:
            cached_results[d] = cached
        else:
            missing_periods.add(d)

    if not missing_periods:
        return (cached_results[7], cached_results[15], cached_results[30], cached_results[60], cached_results[90])

    # now()を1回だけ取得して全タスクで共有（期間のブレをなくす）
    end_dt = datetime.now(timezone.utc)

    period_results = {d: {a: None for a in asin_list} for d in missing_periods}
    tasks = [(a, d) for a in asin_list for d in missing_periods]

    # 並列数を抑えてレート制限(429)自体を減らす（10だと429多発で欠損が出ていた）
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_fetch_sales_one, a, d, end_dt, order_qty_cap): (a, d) for a, d in tasks}
        for f in as_completed(futures):
            asin, val = f.result()
            a, d = futures[f]
            period_results[d][a] = val

    # 失敗(None)分は間隔を空けて順次リトライ。それでも失敗したものだけ0にする
    import logging
    failed = [(d, a) for d in missing_periods for a, v in period_results[d].items() if v is None]
    for d, a in failed:
        time.sleep(1)
        _, v = _fetch_sales_one(a, d, end_dt, order_qty_cap)
        if v is None:
            logging.getLogger("amazon").warning(f"売上取得失敗(0扱い): asin={a} period={d}d")
            v = 0.0
        period_results[d][a] = v

    for d in missing_periods:
        _cache_set(f"sales_{d}{cache_suffix}", period_results[d])
        cached_results[d] = period_results[d]

    return (cached_results[7], cached_results[15], cached_results[30], cached_results[60], cached_results[90])


def fetch_sales_detail(asin_list: List[str], days: int = 30) -> Dict[str, dict]:
    """販売数・売上金額を取得（商品分析用）。戻り値: {asin: {units, revenue, avg_price}}"""
    from datetime import datetime, timedelta, timezone
    cache_key = f"sales_detail_{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)
    mp = "A1VC38T7YXB528"

    def _fetch_one(asin: str) -> tuple:
        try:
            params = urllib.parse.urlencode({
                "marketplaceIds": mp,
                "interval": f"{start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}--{end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "granularity": "Total",
                "asin": asin,
            })
            data = _call_sp_api(f"/sales/v1/orderMetrics?{params}")
            payload = data.get("payload", [])
            units = sum(m.get("unitCount", 0) for m in payload)
            revenue = sum(m.get("totalSales", m.get("orderedProductSales", {})).get("amount", 0) for m in payload)
            avg_price = round(revenue / units, 0) if units > 0 else 0
            return asin, {"units": units, "revenue": round(revenue, 0), "avg_price": avg_price}
        except Exception:
            return asin, {"units": 0, "revenue": 0, "avg_price": 0}

    result = {}
    # orderMetricsのレート制限は約0.5回/秒。並列を増やしても429→バックオフ待ちが
    # 増えるだけなので抑える（fetch_all_salesと同時実行時の奪い合いも減る）
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_fetch_one, asin): asin for asin in asin_list}
        for f in as_completed(futures):
            asin, val = f.result()
            result[asin] = val

    _cache_set(cache_key, result)
    return result


def fetch_new_product_info(asin_list: List[str]) -> Dict[str, dict]:
    """新商品判定用: ASINごとに初回売上日・経過日数・累計販売数を返す。
    戻り値: {asin: {first_sale_date, elapsed_days, total_units}}
    経過日数が90日以上または売上なしの場合はelapsed_days=None。
    キャッシュTTL=1時間。
    """
    from datetime import datetime, timedelta, timezone
    cache_key = "new_product_info"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    mp = "A1VC38T7YXB528"
    now = datetime.now(timezone.utc)
    # 月次で365日分取得して初回売上月を特定
    start_365 = now - timedelta(days=365)

    def _fetch_one(asin: str) -> tuple:
        try:
            params = urllib.parse.urlencode({
                "marketplaceIds": mp,
                "interval": f"{start_365.strftime('%Y-%m-%dT%H:%M:%SZ')}--{now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "granularity": "Month",
                "asin": asin,
            })
            data = _call_sp_api(f"/sales/v1/orderMetrics?{params}")
            payload = data.get("payload", [])

            # 売上がある最初の月を探す
            first_month_start = None
            for m in payload:
                if (m.get("unitCount") or 0) > 0:
                    first_month_start = m.get("interval", "").split("--")[0]
                    break

            if not first_month_start:
                return asin, {"first_sale_date": None, "elapsed_days": None, "total_units": 0}

            first_dt = datetime.fromisoformat(first_month_start.replace("Z", "+00:00"))
            elapsed_days = (now - first_dt).days

            if elapsed_days >= 90:
                return asin, {"first_sale_date": first_month_start, "elapsed_days": None, "total_units": 0}

            # 90日未満 → 初回売上日から今日までの累計販売数を取得
            params2 = urllib.parse.urlencode({
                "marketplaceIds": mp,
                "interval": f"{first_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}--{now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "granularity": "Total",
                "asin": asin,
            })
            data2 = _call_sp_api(f"/sales/v1/orderMetrics?{params2}")
            total_units = sum(m.get("unitCount", 0) for m in data2.get("payload", []))

            return asin, {
                "first_sale_date": first_month_start,
                "elapsed_days": max(elapsed_days, 1),
                "total_units": total_units,
            }
        except Exception:
            return asin, {"first_sale_date": None, "elapsed_days": None, "total_units": 0}

    result = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(_fetch_one, asin): asin for asin in asin_list}
        for f in as_completed(futures):
            asin, val = f.result()
            result[asin] = val

    # 初回売上日は日単位でしか変わらないためTTL=24時間。
    # orderMetricsのレート制限枠(0.5回/秒)を売上取得と奪い合う頻度を減らす
    _cache[cache_key] = {"value": result, "expires_at": time.time() + _CACHE_TTL_LONG}
    return result


def _positive_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        num = float(value)
        return num if num > 0 else None
    except (TypeError, ValueError):
        return None


def _extract_listing_price(pricing_item: dict) -> Optional[float]:
    offers = pricing_item.get("Product", {}).get("Offers", []) or []
    for offer in offers:
        price = (
            offer.get("BuyingPrice", {})
            .get("ListingPrice", {})
            .get("Amount")
        )
        parsed = _positive_float(price)
        if parsed is not None:
            return parsed
    return None


def _fetch_price_from_pricing_api(mp: str, item_type: str, value: str) -> Optional[float]:
    if not value:
        return None
    key = "Skus" if item_type == "Sku" else "Asins"
    params = urllib.parse.urlencode({"MarketplaceId": mp, key: value})
    data = _call_sp_api(f"/products/pricing/v0/price?ItemType={item_type}&{params}")
    for item in data.get("payload", []) or []:
        if item.get("status") == "Success":
            price = _extract_listing_price(item)
            if price is not None:
                return price
    return None


def _extract_total_fee(fee_data: dict) -> Optional[float]:
    total_fee = (
        fee_data.get("payload", {})
        .get("FeesEstimateResult", {})
        .get("FeesEstimate", {})
        .get("TotalFeesEstimate", {})
        .get("Amount")
    )
    return _positive_float(total_fee)


def _fetch_fba_fee(mp: str, identifier: str, selling_price: float, identifier_type: str) -> Optional[float]:
    if not identifier:
        return None
    if identifier_type == "asin":
        path = f"/products/fees/v0/items/{urllib.parse.quote(identifier, safe='')}/feesEstimate"
    else:
        path = f"/products/fees/v0/listings/{urllib.parse.quote(identifier, safe='')}/feesEstimate"

    body = json.dumps({
        "FeesEstimateRequest": {
            "MarketplaceId": mp,
            "IsAmazonFulfilled": True,
            "PriceToEstimateFees": {
                "ListingPrice": {"CurrencyCode": "JPY", "Amount": selling_price},
                "Shipping": {"CurrencyCode": "JPY", "Amount": 0},
            },
            "Identifier": identifier,
        }
    }).encode()
    token = _get_access_token()
    req = urllib.request.Request(
        f"https://sellingpartnerapi-fe.amazon.com{path}",
        data=body,
        method="POST",
        headers={
            "x-amz-access-token": token,
            "Content-Type": "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        return _extract_total_fee(json.loads(res.read()))


def _fetch_price_and_fee_one(sku: str, asin: str = "", fallback_price: Optional[float] = None) -> tuple:
    """1SKUの出品価格とFBA手数料を取得。戻り値: (sku, selling_price, fba_fee, price_source, fee_source)"""
    mp = "A1VC38T7YXB528"
    selling_price = None
    fba_fee = None
    price_source = None
    fee_source = None

    # 出品価格取得。SKU価格が取れない場合はASIN価格、最後にDB保存済み価格を使う。
    try:
        selling_price = _fetch_price_from_pricing_api(mp, "Sku", sku)
        if selling_price is not None:
            price_source = "sku"
    except Exception:
        pass

    if selling_price is None and asin:
        try:
            selling_price = _fetch_price_from_pricing_api(mp, "Asin", asin)
            if selling_price is not None:
                price_source = "asin"
        except Exception:
            pass

    if selling_price is None:
        selling_price = _positive_float(fallback_price)
        if selling_price is not None:
            price_source = "db"

    # FBA手数料取得（出品価格が取れた場合のみ）
    if selling_price is not None:
        try:
            fba_fee = _fetch_fba_fee(mp, sku, selling_price, "sku")
            if fba_fee is not None:
                fee_source = "sku"
        except Exception:
            pass

    if selling_price is not None and fba_fee is None and asin:
        try:
            fba_fee = _fetch_fba_fee(mp, asin, selling_price, "asin")
            if fba_fee is not None:
                fee_source = "asin"
        except Exception:
            pass

    return sku, selling_price, fba_fee, price_source, fee_source


# ---------- FBA納品（Fulfillment Inbound API） ----------

# 納品(shipment)のステータス。v0の getShipments は ShipmentStatusList を
# 複数まとめて渡すと1件しか返さないため、1つずつ問い合わせて結合する。
_SHIPMENT_STATUSES = [
    "WORKING", "READY_TO_SHIP", "SHIPPED", "IN_TRANSIT", "DELIVERED",
    "CHECKED_IN", "RECEIVING", "CLOSED",
]


def fetch_inbound_shipments(days: int = 180) -> Dict[str, dict]:
    """FBAへ実際に発送した数量をSKU単位で返す。発注済みの消し込みに使う。

    戻り値: {sku: {"shipped": 出荷数, "received": 受領数, "shipments": [...]}}

    納品プラン(2024-03-20 inboundPlans)は作り直しても古いものがACTIVEのまま残り、
    実際の発送数と一致しない（同じ70個のプランが3日連続で作られていた）。
    こちらは実際に発送された数なので、消し込みの根拠として確実。

    キャンセル・削除された納品は_SHIPMENT_STATUSESに含めていないので数えない。
    """
    cache_key = f"inbound_shipments_{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    from datetime import datetime, timedelta, timezone
    mp = "A1VC38T7YXB528"
    now = datetime.now(timezone.utc)
    base = {
        "MarketplaceId": mp,
        "QueryType": "DATE_RANGE",
        "LastUpdatedAfter": (now - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "LastUpdatedBefore": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
    }

    def _list_by_status(status: str) -> Dict[str, dict]:
        found: Dict[str, dict] = {}
        q = urllib.parse.urlencode(base) + f"&ShipmentStatusList={status}"
        try:
            data = _call_sp_api(f"/fba/inbound/v0/shipments?{q}")
        except Exception:
            return found
        while True:
            payload = data.get("payload") or {}
            for s in (payload.get("ShipmentData") or []):
                sid = s.get("ShipmentId")
                if sid:
                    found[sid] = s
            token = payload.get("NextToken")
            if not token:
                break
            try:
                data = _call_sp_api(
                    f"/fba/inbound/v0/shipments?"
                    + urllib.parse.urlencode({"MarketplaceId": mp, "QueryType": "NEXT_TOKEN", "NextToken": token})
                )
            except Exception:
                break
        return found

    shipments: Dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for found in ex.map(_list_by_status, _SHIPMENT_STATUSES):
            shipments.update(found)

    def _items(sid: str) -> List[tuple]:
        try:
            data = _call_sp_api(
                f"/fba/inbound/v0/shipments/{sid}/items?"
                + urllib.parse.urlencode({"MarketplaceId": mp})
            )
        except Exception:
            return []
        rows = []
        for it in ((data.get("payload") or {}).get("ItemData") or []):
            sku = it.get("SellerSKU") or ""
            if sku:
                rows.append((sku, it.get("QuantityShipped") or 0, it.get("QuantityReceived") or 0, sid))
        return rows

    result: Dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for rows in ex.map(_items, list(shipments)):
            for sku, shipped, received, sid in rows:
                rec = result.setdefault(sku, {"shipped": 0, "received": 0, "shipments": []})
                rec["shipped"] += shipped
                rec["received"] += received
                s = shipments.get(sid) or {}
                name = s.get("ShipmentName") or ""
                rec["shipments"].append({
                    "shipment_id": sid,
                    "name": name,
                    "status": s.get("ShipmentStatus") or "",
                    "shipped": shipped,
                    "received": received,
                    "shipped_at": _shipment_date(name),
                })

    _cache_set(cache_key, result)
    return result


def _shipment_date(shipment_name: str) -> str:
    """納品名から作成日を取り出す。'FBA STA (2026/07/02 05:35)-XJE2' -> '2026-07-02'

    v0のShipmentDataには日付フィールドが無く、名前に埋まっているものしか手がかりが
    ない。取れない場合は空文字を返し、呼び出し側で日付不明として扱う。
    """
    import re
    m = re.search(r"(\d{4})/(\d{2})/(\d{2})", shipment_name or "")
    if not m:
        return ""
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _post_sp_api(path: str, body: dict) -> dict:
    """SP-APIへのPOST。_call_sp_apiはGET専用なので書き込み用に用意する。"""
    token = _get_access_token()
    req = urllib.request.Request(
        "https://sellingpartnerapi-fe.amazon.com" + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"x-amz-access-token": token, "Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            raise Exception(f"HTTP {e.code}: {e.read().decode()[:500]}")
    raise Exception("SP-API rate limited after retries: " + path)


def fetch_default_source_address() -> Optional[dict]:
    """納品プランの発送元住所を、直近のプランから引き継ぐ。

    住所をコードや設定に持たせるとセラーセントラル側で変更したときにずれるため、
    実際に使われた住所をそのまま再利用する。
    """
    try:
        data = _call_sp_api(
            "/inbound/fba/2024-03-20/inboundPlans?"
            + urllib.parse.urlencode({"pageSize": 1})
        )
    except Exception:
        return None
    plans = data.get("inboundPlans") or []
    if not plans:
        return None
    return plans[0].get("sourceAddress") or None


def create_inbound_plan(items: List[dict], source_address: dict, name: str = "") -> dict:
    """FBA納品プランを作成する。

    items: [{"sku": SKU, "qty": 個数}, ...]（個数はピース単位）
    戻り値: {"inbound_plan_id": ..., "operation_id": ...}

    梱包や配送業者の指定はしない。箱詰めはタオタロウが行うため、
    こちらで確定できるのはSKUと数量までになる。
    """
    mp = "A1VC38T7YXB528"
    payload_items = [
        {
            "msku": it["sku"],
            "quantity": int(it["qty"]),
            # 商品ラベルの貼付・準備はこちら（出品者）で行う
            "labelOwner": "SELLER",
            "prepOwner": "SELLER",
        }
        for it in items
        if it.get("sku") and int(it.get("qty") or 0) > 0
    ]
    if not payload_items:
        raise ValueError("納品数が1以上の商品がありません")

    body = {
        "destinationMarketplaces": [mp],
        "sourceAddress": source_address,
        "items": payload_items,
    }
    if name:
        body["name"] = name

    data = _post_sp_api("/inbound/fba/2024-03-20/inboundPlans", body)
    return {
        "inbound_plan_id": data.get("inboundPlanId") or "",
        "operation_id": data.get("operationId") or "",
    }


def get_inbound_operation_status(operation_id: str) -> dict:
    """createInboundPlanは非同期。operationIdで完了したかを確認する。"""
    return _call_sp_api(f"/inbound/fba/2024-03-20/operations/{operation_id}")


def fetch_inbound_plans() -> List[dict]:
    """FBA納品プランをSKU単位で返す（作成済みだが未発送のものを含む）。

    実際に発送された数は fetch_inbound_shipments() を使うこと。こちらは
    作り直した残骸もACTIVEのまま残るため、単純合計は実態と一致しない。

    戻り値: [{plan_id, created_at, status, sku, qty}, ...]（作成日の新しい順）
    """
    cached = _cache_get("inbound_plans")
    if cached is not None:
        return cached

    plans: List[dict] = []
    token = None
    while True:
        params = {"pageSize": 30}
        if token:
            params["paginationToken"] = token
        data = _call_sp_api(f"/inbound/fba/2024-03-20/inboundPlans?{urllib.parse.urlencode(params)}")
        plans.extend(data.get("inboundPlans") or [])
        token = (data.get("pagination") or {}).get("nextToken")
        if not token:
            break

    def _fetch_items(plan: dict) -> List[dict]:
        pid = plan.get("inboundPlanId")
        if not pid:
            return []

        # listInboundPlans の status は作り直しやキャンセル後も ACTIVE のままなので、
        # 個別GETで shipments の実ステータスを見る。出荷が1件も無いプラン
        # （＝画面上の「キャンセル済み」や配置未確定）は納品として数えない。
        shipment_status = ""
        try:
            detail = _call_sp_api(f"/inbound/fba/2024-03-20/inboundPlans/{pid}")
            shipments = detail.get("shipments") or []
            if not shipments:
                return []
            shipment_status = shipments[0].get("status") or ""
            if shipment_status in ("CANCELLED", "DELETED", "VOID"):
                return []
        except Exception:
            # 取得できない場合は判断材料が無いので、数えない側に倒す
            return []

        rows = []
        item_token = None
        while True:
            params = {"pageSize": 100}
            if item_token:
                params["paginationToken"] = item_token
            try:
                data = _call_sp_api(
                    f"/inbound/fba/2024-03-20/inboundPlans/{pid}/items?{urllib.parse.urlencode(params)}"
                )
            except Exception:
                return rows
            for it in (data.get("items") or []):
                msku = it.get("msku") or ""
                qty = it.get("quantity") or 0
                if msku and qty:
                    rows.append({
                        "plan_id": pid,
                        "created_at": plan.get("createdAt") or "",
                        "status": plan.get("status") or "",
                        "shipment_status": shipment_status,
                        "sku": msku,
                        "qty": qty,
                    })
            item_token = (data.get("pagination") or {}).get("nextToken")
            if not item_token:
                break
        return rows

    result: List[dict] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for rows in ex.map(_fetch_items, plans):
            result.extend(rows)

    result.sort(key=lambda r: r["created_at"], reverse=True)
    _cache[("inbound_plans")] = {"value": result, "expires_at": time.time() + _CACHE_TTL_LONG}
    return result


def fetch_sales_period(days: int, offset_days: int, asin_list: List[str]) -> Dict[str, float]:
    """offset_days前〜(offset_days+days)前の期間の日販を取得"""
    from datetime import datetime, timedelta, timezone
    mp = "A1VC38T7YXB528"

    def _fetch_one(asin: str) -> tuple:
        end = datetime.now(timezone.utc) - timedelta(days=offset_days)
        start = end - timedelta(days=days)
        try:
            params = urllib.parse.urlencode({
                "marketplaceIds": mp,
                "interval": f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}--{end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "granularity": "Total",
                "asin": asin,
            })
            data = _call_sp_api(f"/sales/v1/orderMetrics?{params}")
            units = sum(m.get("unitCount", 0) for m in data.get("payload", []))
            return asin, round(units / days, 4)
        except Exception:
            return asin, 0.0

    result = {asin: 0.0 for asin in asin_list}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_one, asin): asin for asin in asin_list}
        for f in as_completed(futures):
            asin, val = f.result()
            result[asin] = val
    return result


def update_listing_price(sku: str, price: float) -> tuple:
    """Feeds APIで出品価格を更新。戻り値: (success: bool, error_msg: str)

    MerchantIdentifier は以前アカウントIDを直書きしていた。アカウントを
    切り替えたときに直し忘れて価格更新が失敗するので、環境変数から取る。
    """
    mp = "A1VC38T7YXB528"
    token = _get_access_token()

    xml_body = f'''<?xml version="1.0" encoding="utf-8"?>
<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="amznenvelope.xsd">
  <Header><DocumentVersion>1.01</DocumentVersion><MerchantIdentifier>{_seller_id()}</MerchantIdentifier></Header>
  <MessageType>Price</MessageType>
  <Message><MessageID>1</MessageID>
    <Price><SKU>{sku}</SKU><StandardPrice currency="JPY">{round(price)}</StandardPrice></Price>
  </Message>
</AmazonEnvelope>'''.encode("utf-8")

    headers = {"x-amz-access-token": token, "Content-Type": "application/json"}

    try:
        # Step1: フィードドキュメント作成
        req1 = urllib.request.Request(
            "https://sellingpartnerapi-fe.amazon.com/feeds/2021-06-30/documents",
            data=json.dumps({"contentType": "text/xml; charset=UTF-8"}).encode(),
            method="POST", headers=headers,
        )
        with urllib.request.urlopen(req1, timeout=15) as res:
            doc = json.loads(res.read())
        doc_id = doc["feedDocumentId"]
        upload_url = doc["url"]

        # Step2: XMLをS3にアップロード
        upload_req = urllib.request.Request(
            upload_url, data=xml_body, method="PUT",
            headers={"Content-Type": "text/xml; charset=UTF-8"},
        )
        with urllib.request.urlopen(upload_req, timeout=15):
            pass

        # Step3: フィード送信
        req3 = urllib.request.Request(
            "https://sellingpartnerapi-fe.amazon.com/feeds/2021-06-30/feeds",
            data=json.dumps({
                "feedType": "POST_PRODUCT_PRICING_DATA",
                "marketplaceIds": [mp],
                "inputFeedDocumentId": doc_id,
            }).encode(),
            method="POST", headers=headers,
        )
        with urllib.request.urlopen(req3, timeout=15) as res:
            result = json.loads(res.read())

        if result.get("feedId"):
            return True, ""
        return False, str(result)

    except urllib.error.HTTPError as e:
        err = e.read().decode()
        return False, f"HTTP {e.code}: {err}"
    except Exception as ex:
        return False, str(ex)


def fetch_prices_and_fees(
    sku_list: List[str],
    asin_map: Optional[Dict[str, str]] = None,
    fallback_prices: Optional[Dict[str, float]] = None,
) -> Dict[str, dict]:
    """全SKUの出品価格・FBA手数料を並列取得。戻り値: {sku: {selling_price, fba_fee}}"""
    result = {}
    asin_map = asin_map or {}
    fallback_prices = fallback_prices or {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {
            ex.submit(
                _fetch_price_and_fee_one,
                sku,
                asin_map.get(sku, ""),
                fallback_prices.get(sku),
            ): sku
            for sku in sku_list
        }
        for f in as_completed(futures):
            sku, selling_price, fba_fee, price_source, fee_source = f.result()
            result[sku] = {
                "selling_price": selling_price,
                "fba_fee": fba_fee,
                "price_source": price_source,
                "fee_source": fee_source,
            }
    return result


# ---------- Amazon Ads API ----------

_ads_token_cache = {"token": None, "expires_at": 0}


def _get_ads_access_token() -> str:
    if _ads_token_cache["token"] and time.time() < _ads_token_cache["expires_at"]:
        return _ads_token_cache["token"]

    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": settings.ADS_API_REFRESH_TOKEN,
        "client_id": settings.ADS_API_CLIENT_ID,
        "client_secret": settings.ADS_API_CLIENT_SECRET,
    }).encode()

    req = urllib.request.Request(
        "https://api.amazon.com/auth/o2/token",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        result = json.loads(res.read())

    _ads_token_cache["token"] = result["access_token"]
    _ads_token_cache["expires_at"] = time.time() + result["expires_in"] - 60
    return _ads_token_cache["token"]


def _get_ads_profile_id() -> str:
    """日本マーケットプレイス（countryCode=JP）のprofileIdを取得"""
    cached = _cache_get("ads_profile_id")
    if cached:
        return cached

    token = _get_ads_access_token()
    req = urllib.request.Request(
        "https://advertising-api-fe.amazon.com/v2/profiles",
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Amazon-Advertising-API-ClientId": settings.ADS_API_CLIENT_ID,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        profiles = json.loads(res.read())

    profile_id = None
    for p in profiles:
        if p.get("countryCode") == "JP":
            profile_id = str(p["profileId"])
            break
    if not profile_id and profiles:
        profile_id = str(profiles[0]["profileId"])

    if profile_id:
        _cache[("ads_profile_id")] = {"value": profile_id, "expires_at": time.time() + _CACHE_TTL_LONG}
    return profile_id


def fetch_ads_data(asin_list: List[str], days: int) -> Dict[str, dict]:
    """ASIN単位の広告データを取得（Ads API v3）。戻り値: {asin: {ad_spend, impressions, clicks, ad_orders, ad_revenue}}"""
    if not settings.ADS_API_REFRESH_TOKEN:
        return {}

    cached = _cache_get(f"ads_data_{days}")
    if cached is not None:
        return cached

    from datetime import datetime, timedelta
    import gzip
    end_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        token = _get_ads_access_token()
        profile_id = _get_ads_profile_id()
        if not profile_id:
            return {}

        headers = {
            "Authorization": f"Bearer {token}",
            "Amazon-Advertising-API-ClientId": settings.ADS_API_CLIENT_ID,
            "Amazon-Advertising-API-Scope": profile_id,
            "Content-Type": "application/json",
        }

        body = json.dumps({
            "name": f"sp_asin_{days}d",
            "startDate": start_date,
            "endDate": end_date,
            "configuration": {
                "adProduct": "SPONSORED_PRODUCTS",
                "groupBy": ["advertiser"],
                "columns": ["impressions", "clicks", "cost", "purchases30d", "sales30d", "advertisedAsin"],
                "reportTypeId": "spAdvertisedProduct",
                "timeUnit": "SUMMARY",
                "format": "GZIP_JSON",
            },
        }).encode()

        req = urllib.request.Request(
            "https://advertising-api-fe.amazon.com/reporting/reports",
            data=body, method="POST", headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as res:
            report_resp = json.loads(res.read())

        report_id = report_resp.get("reportId")
        if not report_id:
            return {}

        # レポート完成まで最大90秒ポーリング
        report_url = None
        for _ in range(30):
            time.sleep(3)
            status_req = urllib.request.Request(
                f"https://advertising-api-fe.amazon.com/reporting/reports/{report_id}",
                method="GET", headers=headers,
            )
            with urllib.request.urlopen(status_req, timeout=15) as res:
                status_data = json.loads(res.read())
            if status_data.get("status") == "COMPLETED":
                report_url = status_data.get("url")
                break
            elif status_data.get("status") == "FAILURE":
                return {}

        if not report_url:
            return {}

        dl_req = urllib.request.Request(report_url, method="GET")
        with urllib.request.urlopen(dl_req, timeout=30) as res:
            raw = res.read()
        try:
            rows = json.loads(gzip.decompress(raw))
        except Exception:
            rows = json.loads(raw)

        # ASIN単位に集計
        result: Dict[str, dict] = {}
        for row in rows:
            asin = row.get("advertisedAsin")
            if not asin:
                continue
            if asin not in result:
                result[asin] = {"ad_spend": 0, "impressions": 0, "clicks": 0, "ad_orders": 0, "ad_revenue": 0}
            result[asin]["ad_spend"]    += float(row.get("cost") or 0)
            result[asin]["impressions"] += int(row.get("impressions") or 0)
            result[asin]["clicks"]      += int(row.get("clicks") or 0)
            result[asin]["ad_orders"]   += int(row.get("purchases30d") or 0)
            result[asin]["ad_revenue"]  += float(row.get("sales30d") or 0)

        _cache_set(f"ads_data_{days}", result)
        return result

    except Exception:
        return {}


# ---------- Ads API v3: エンティティ取得 + レポート ----------

import logging as _logging

_ads_logger = _logging.getLogger("ads_api")

ADS_BASE = "https://advertising-api-fe.amazon.com"

_ADS_RETRY_MAX = 4
_ADS_RETRY_BASE_WAIT = 2


class AdsApiError(Exception):
    pass


def _ads_api_headers(content_type: str = "application/json", accept: str = "application/json") -> dict:
    token = _get_ads_access_token()
    profile_id = _get_ads_profile_id()
    return {
        "Authorization": f"Bearer {token}",
        "Amazon-Advertising-API-ClientId": settings.ADS_API_CLIENT_ID,
        "Amazon-Advertising-API-Scope": profile_id,
        "Content-Type": content_type,
        "Accept": accept,
    }


def _ads_request_with_retry(req, *, timeout=30) -> dict:
    """429/5xxのリトライ + exponential backoff付きHTTPリクエスト"""
    last_err = None
    for attempt in range(_ADS_RETRY_MAX):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 or e.code >= 500:
                wait = _ADS_RETRY_BASE_WAIT * (2 ** attempt)
                _ads_logger.warning("Ads API %s %s -> HTTP %d, retry in %ds", req.get_method(), req.full_url, e.code, wait)
                time.sleep(wait)
                continue
            body = e.read().decode()[:500]
            raise AdsApiError(f"Ads API HTTP {e.code}: {body}") from e
        except Exception as e:
            last_err = e
            if attempt < _ADS_RETRY_MAX - 1:
                wait = _ADS_RETRY_BASE_WAIT * (2 ** attempt)
                _ads_logger.warning("Ads API request error: %s, retry in %ds", e, wait)
                time.sleep(wait)
                continue
            raise
    raise AdsApiError(f"Ads API rate limited after {_ADS_RETRY_MAX} retries: {last_err}")


def _ads_download_with_retry(url, *, timeout=30) -> bytes:
    """レポートダウンロード用（バイナリ返却、429/5xxリトライ付き）"""
    last_err = None
    for attempt in range(_ADS_RETRY_MAX):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 or e.code >= 500:
                wait = _ADS_RETRY_BASE_WAIT * (2 ** attempt)
                _ads_logger.warning("Report download HTTP %d, retry in %ds", e.code, wait)
                time.sleep(wait)
                continue
            raise AdsApiError(f"Report download HTTP {e.code}") from e
        except Exception as e:
            last_err = e
            if attempt < _ADS_RETRY_MAX - 1:
                wait = _ADS_RETRY_BASE_WAIT * (2 ** attempt)
                time.sleep(wait)
                continue
            raise
    raise AdsApiError(f"Report download failed after {_ADS_RETRY_MAX} retries: {last_err}")


def _ads_post_list(
    endpoint: str,
    media_type: str,
    body_key: str,
    filters: dict | None = None,
    max_results: int = 10000,
) -> list:
    """SP API v3 の POST /list 形式で全件取得（ページネーション対応）
    Content-TypeとAcceptの両方にvendor media typeを使用"""
    headers = _ads_api_headers(content_type=media_type, accept=media_type)
    all_items = []
    next_token = None

    while True:
        body: dict = {"maxResults": min(max_results - len(all_items), 1000)}
        if filters:
            body["stateFilter"] = filters.get("stateFilter", {})
        if next_token:
            body["nextToken"] = next_token

        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{ADS_BASE}{endpoint}", data=data, method="POST", headers=headers,
        )
        result = _ads_request_with_retry(req)

        items = result.get(body_key, [])
        all_items.extend(items)

        next_token = result.get("nextToken")
        if not next_token or len(all_items) >= max_results:
            break

    return all_items


def fetch_sp_campaigns() -> list:
    return _ads_post_list(
        "/sp/campaigns/list",
        "application/vnd.spCampaign.v3+json",
        "campaigns",
    )


def fetch_sp_ad_groups() -> list:
    return _ads_post_list(
        "/sp/adGroups/list",
        "application/vnd.spAdGroup.v3+json",
        "adGroups",
    )


def fetch_sp_keywords() -> list:
    return _ads_post_list(
        "/sp/keywords/list",
        "application/vnd.spKeyword.v3+json",
        "keywords",
    )


def fetch_sp_targets() -> list:
    return _ads_post_list(
        "/sp/targets/list",
        "application/vnd.spTargetingClause.v3+json",
        "targetingClauses",
    )


def _fetch_ads_report(
    report_type_id: str,
    group_by: list,
    columns: list,
    days: int = 30,
    start_date: str = None,
    end_date: str = None,
) -> list:
    """Ads Reporting API v3 でレポート取得。失敗時はAdsApiErrorを送出。"""
    import gzip
    from datetime import datetime, timedelta

    if not start_date or not end_date:
        end_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    headers = _ads_api_headers()
    body = json.dumps({
        "name": f"{report_type_id}_{start_date}_{end_date}",
        "startDate": start_date,
        "endDate": end_date,
        "configuration": {
            "adProduct": "SPONSORED_PRODUCTS",
            "groupBy": group_by,
            "columns": columns,
            "reportTypeId": report_type_id,
            "timeUnit": "SUMMARY",
            "format": "GZIP_JSON",
        },
    }).encode()

    req = urllib.request.Request(
        f"{ADS_BASE}/reporting/reports",
        data=body, method="POST", headers=headers,
    )
    report_resp = _ads_request_with_retry(req)

    report_id = report_resp.get("reportId")
    if not report_id:
        raise AdsApiError(f"Report {report_type_id}: reportId missing in response")

    for _ in range(40):
        time.sleep(3)
        status_req = urllib.request.Request(
            f"{ADS_BASE}/reporting/reports/{report_id}",
            method="GET", headers=headers,
        )
        status_data = _ads_request_with_retry(status_req, timeout=15)
        status = status_data.get("status")
        if status == "COMPLETED":
            report_url = status_data.get("url")
            if not report_url:
                raise AdsApiError(f"Report {report_type_id}: COMPLETED but no download URL")
            raw = _ads_download_with_retry(report_url)
            try:
                return json.loads(gzip.decompress(raw))
            except Exception:
                return json.loads(raw)
        elif status in ("FAILURE", "FAILED"):
            raise AdsApiError(f"Report {report_type_id}: status={status}")

    raise AdsApiError(f"Report {report_type_id}: polling timeout (120s)")


def fetch_campaign_report(
    days: int = 30,
    start_date: str = None,
    end_date: str = None,
    attribution_days: int = 30,
) -> list:
    purchases_col = f"purchases{attribution_days}d"
    sales_col = f"sales{attribution_days}d"
    return _fetch_ads_report(
        "spCampaigns", ["campaign"],
        ["campaignId", "campaignName", "impressions", "clicks", "cost",
         purchases_col, sales_col],
        days, start_date, end_date,
    )


def fetch_targeting_report(
    days: int = 30,
    start_date: str = None,
    end_date: str = None,
    attribution_days: int = 30,
) -> list:
    purchases_col = f"purchases{attribution_days}d"
    sales_col = f"sales{attribution_days}d"
    return _fetch_ads_report(
        "spTargeting", ["targeting"],
        ["campaignId", "adGroupId", "targeting", "keyword", "keywordType",
         "impressions", "clicks", "cost", purchases_col, sales_col],
        days, start_date, end_date,
    )


def fetch_search_term_report(
    days: int = 30,
    start_date: str = None,
    end_date: str = None,
    attribution_days: int = 30,
) -> list:
    purchases_col = f"purchases{attribution_days}d"
    sales_col = f"sales{attribution_days}d"
    return _fetch_ads_report(
        "spSearchTerm", ["searchTerm"],
        ["campaignId", "adGroupId", "searchTerm", "matchType", "keyword",
         "impressions", "clicks", "cost", purchases_col, sales_col],
        days, start_date, end_date,
    )


def parse_campaign_name(name: str) -> tuple:
    for prefix in ("A_", "P_", "G_", "E_"):
        if name.startswith(prefix):
            rest = name[len(prefix):]
            asin = rest.split("_")[0].split(" ")[0] if rest else None
            if asin and len(asin) >= 10:
                return (prefix, asin)
            return (prefix, None)
    return ("other", None)


# ---------- 競合リサーチシート用（1ASINぶんをまとめて取る） ----------
#
# リサーチシートは配布版のころ、手元の中継サーバー(127.0.0.1:8765)を経由して
# SP-APIを叩いていた。中継を入れた人しか使えず、実際には誰も動かしていなかった
# ため、寸法・重量・手数料が空のままになっていた。
# SP-APIは正規のAPIでサーバーから叩けるので、ここに寄せる。

_RESEARCH_MP = "A1VC38T7YXB528"

# 仕様欄に出す属性。多すぎると読めないので、判断に使うものだけ拾う
_SPEC_KEYS = [
    ("brand", "ブランド"), ("material", "素材"), ("color", "カラー"),
    ("size", "サイズ"), ("style", "スタイル"), ("model_number", "型番"),
    ("item_type_name", "種類"), ("number_of_items", "入数"),
]


def _cm(value, unit) -> Optional[float]:
    """SP-APIの寸法をcmに直す。単位はinches/centimeters等で返ってくる。"""
    v = _positive_float(value)
    if v is None:
        return None
    u = (unit or "").lower()
    if u.startswith("inch"):
        return round(v * 2.54, 1)
    if u.startswith("milli"):
        return round(v / 10, 1)
    if u.startswith("meter"):
        return round(v * 100, 1)
    return round(v, 1)


def _kg(value, unit) -> Optional[float]:
    v = _positive_float(value)
    if v is None:
        return None
    u = (unit or "").lower()
    if u.startswith("pound") or u == "lb":
        return round(v * 0.4536, 3)
    if u.startswith("ounce") or u == "oz":
        return round(v * 0.02835, 3)
    if u.startswith("gram") and not u.startswith("kilo"):
        return round(v / 1000, 3)
    return round(v, 3)


def _image_data_url(url: str) -> Optional[str]:
    """画像を取ってきてdata URLにする。

    URLをそのまま返すと、シート側が縮小のためcanvasに描いた時点で
    別サイトの画像として扱われ、取り出せなくなることがある。
    こちらで取ってしまえばその問題が起きない。
    """
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as res:
            raw = res.read()
            mime = res.headers.get("Content-Type", "image/jpeg").split(";")[0]
        import base64
        return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
    except Exception:
        return None


def fetch_research_asin(asin: str, price: Optional[float] = None) -> dict:
    """リサーチシートの1行ぶん。商品名・寸法・重量・手数料・画像・仕様。

    どれか取れなくても他は返す（1項目のために全部が空になるのを避ける）。
    取れなかったものは notes に理由を入れて画面に出す。
    """
    asin = (asin or "").strip().upper()
    if not asin:
        return {"ok": False, "error": "ASINがありません"}

    fields: Dict[str, object] = {}
    notes: List[str] = []
    image_url = None
    spec_lines: List[str] = []
    rank = None

    try:
        params = urllib.parse.urlencode({
            "marketplaceIds": _RESEARCH_MP,
            "includedData": "attributes,dimensions,images,summaries,salesRanks",
        })
        data = _call_sp_api(f"/catalog/2022-04-01/items/{asin}?{params}")
    except Exception as e:
        return {"ok": False, "error": f"商品情報を取得できませんでした（{type(e).__name__}）"}

    for s in data.get("summaries", []):
        if s.get("marketplaceId") != _RESEARCH_MP:
            continue
        if s.get("itemName"):
            fields["competitor"] = s["itemName"]
        break

    for img_set in data.get("images", []):
        for img in img_set.get("images", []):
            if img.get("variant") == "MAIN":
                image_url = img.get("link")
                break
        if image_url:
            break

    # 寸法。package（梱包後）を優先する。送料も手数料も箱の大きさで決まるため
    for dim in data.get("dimensions", []):
        if dim.get("marketplaceId") != _RESEARCH_MP:
            continue
        box = dim.get("package") or dim.get("item") or {}
        sides = []
        for key in ("length", "width", "height"):
            v = _cm((box.get(key) or {}).get("value"), (box.get(key) or {}).get("unit"))
            if v:
                sides.append(v)
        if len(sides) == 3:
            sides.sort(reverse=True)          # 長辺・中辺・短辺の順
            fields["lenA"], fields["lenB"], fields["lenC"] = sides
        w = _kg((box.get("weight") or {}).get("value"), (box.get("weight") or {}).get("unit"))
        if w:
            fields["weight"] = w
        break
    if "lenA" not in fields:
        notes.append("寸法はAmazonに登録がありませんでした")
    if "weight" not in fields:
        notes.append("重量はAmazonに登録がありませんでした")

    for ranks in data.get("salesRanks", []):
        for r in (ranks.get("displayGroupRanks") or []) + (ranks.get("classificationRanks") or []):
            if r.get("rank"):
                rank = r["rank"]
                break
        if rank:
            break

    attrs = data.get("attributes") or {}
    for key, label in _SPEC_KEYS:
        vals = attrs.get(key)
        if not isinstance(vals, list) or not vals:
            continue
        v = vals[0]
        text = v.get("value") if isinstance(v, dict) else v
        if text not in (None, ""):
            spec_lines.append(f"{label}: {text}")
    for bullet in (attrs.get("bullet_point") or [])[:5]:
        text = bullet.get("value") if isinstance(bullet, dict) else bullet
        if text:
            spec_lines.append(f"・{text}")

    # 手数料は売価が決まっていないと出せない（金額に対して計算されるため）
    if price:
        try:
            fee = _fetch_fba_fee(_RESEARCH_MP, asin, float(price), "asin")
            if fee is not None:
                fields["fee"] = round(fee)
                fields["fulfill"] = "FBA"
        except Exception:
            notes.append("手数料を取得できませんでした")
    else:
        notes.append("売価を入れると手数料も取り込みます")

    return {
        "ok": True,
        "fields": fields,
        "image": _image_data_url(image_url),
        "spec": "\n".join(spec_lines) or None,
        "rank": rank,
        "notes": notes,
    }


# ---------- 出品カテゴリ（商品タイプ） ----------
#
# Amazonは商品タイプごとに必須項目が違い、数百種類ある。決め打ちはできないので
# Amazonから定義を取ってきて画面に出す。競合ASINが分かっていれば、その商品タイプを
# そのまま使うのが確実（同じ棚に並べたいのだから、競合と同じ型でよい）。


def _seller_id() -> str:
    sid = getattr(settings, "SP_API_SELLER_ID", None)
    if not sid:
        raise RuntimeError("SP_API_SELLER_ID が未設定です。Renderの環境変数に設定してください")
    return sid


def fetch_product_type(asin: str) -> dict:
    """競合ASINの商品タイプを調べる。"""
    asin = (asin or "").strip().upper()
    if not asin:
        return {"ok": False, "error": "ASINがありません"}
    try:
        params = urllib.parse.urlencode({
            "marketplaceIds": _RESEARCH_MP,
            "includedData": "productTypes,summaries",
        })
        data = _call_sp_api(f"/catalog/2022-04-01/items/{asin}?{params}")
    except urllib.error.HTTPError as e:
        # 何が起きたか分からないと直せない。応答の中身も返す
        body = ""
        try:
            body = e.read().decode()[:400]
        except Exception:
            pass
        hint = ""
        if e.code == 403:
            hint = "アプリのロールに Product Listing が入っているか確認してください"
        elif e.code == 404:
            hint = "そのASINが日本のカタログに無いようです"
        return {"ok": False, "error": f"HTTP {e.code}: {body}", "ヒント": hint}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}

    ptype = None
    for p in data.get("productTypes", []):
        if p.get("marketplaceId") == _RESEARCH_MP and p.get("productType"):
            ptype = p["productType"]
            break
    name = None
    for s in data.get("summaries", []):
        if s.get("marketplaceId") == _RESEARCH_MP:
            name = s.get("itemName")
            break
    if not ptype:
        return {"ok": False, "error": "この商品には商品タイプが登録されていません"}
    return {"ok": True, "product_type": ptype, "asin": asin, "item_name": name}


# 出品原稿から自動で埋まる項目。画面で聞き直さないよう、ここで持っておく
_FILLED_BY_TOOL = {
    "item_name", "brand", "bullet_point", "product_description",
    "externally_assigned_product_identifier", "merchant_suggested_asin",
    "list_price", "purchasable_offer", "fulfillment_availability",
    "condition_type", "main_product_image_locator", "other_product_image_locator",
    "item_package_dimensions", "item_package_weight", "supplier_declared_dg_hz_regulation",
}


def fetch_product_type_schema(product_type: str) -> dict:
    """その商品タイプの必須項目を、画面に出せる形にして返す。

    Amazonが返す定義はJSON Schemaそのもので、そのままでは読めない。
    必須のものだけを拾い、日本語の表示名と入力の種類を添える。
    """
    pt = (product_type or "").strip().upper()
    if not pt:
        return {"ok": False, "error": "商品タイプがありません"}
    try:
        params = urllib.parse.urlencode({
            "marketplaceIds": _RESEARCH_MP,
            "sellerId": _seller_id(),
            "productType": pt,
            "requirements": "LISTING",
            "locale": "ja_JP",
        })
        meta = _call_sp_api(f"/definitions/2020-09-01/productTypes/{pt}?{params}")
    except Exception as e:
        return {"ok": False, "error": f"商品タイプの定義を取得できませんでした（{type(e).__name__}）"}

    url = (meta.get("schema") or {}).get("link", {}).get("resource")
    if not url:
        return {"ok": False, "error": "定義の場所が返ってきませんでした"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as res:
            schema = json.loads(res.read())
    except Exception as e:
        return {"ok": False, "error": f"定義を読めませんでした（{type(e).__name__}）"}

    props = schema.get("properties") or {}
    # 最上位の required はごく少ない。実際に必須になるものは、
    # 条件付き（allOf/anyOf/oneOf の中の required）に散らばっている。
    # セラーセントラルの入力欄と揃えるため、そこまで拾う。
    required = list(schema.get("required") or [])

    def dig(node):
        if isinstance(node, dict):
            for k in ("required",):
                v = node.get(k)
                if isinstance(v, list):
                    for x in v:
                        if isinstance(x, str) and x not in required:
                            required.append(x)
            for k in ("allOf", "anyOf", "oneOf", "then", "else", "if"):
                v = node.get(k)
                if isinstance(v, list):
                    for x in v:
                        dig(x)
                elif isinstance(v, dict):
                    dig(v)
        elif isinstance(node, list):
            for x in node:
                dig(x)

    dig(schema)
    # 定義に無い名前は出しても入れられないので落とす
    required = [k for k in required if k in props]
    fields = []
    for key in required:
        if key in _FILLED_BY_TOOL:
            continue
        p = props.get(key) or {}
        items = (p.get("items") or {})
        inner = (items.get("properties") or {}).get("value") or {}
        # 選択肢は value.enum に直接あることも、value.anyOf の中の
        # 「enum を持つほう」に入っていることもある（自由入力も許す項目）。
        # 後者を見ていなかったため、素材や対象のお客様が
        # 「プルダウンから選択」と書いてあるのに欄がただの入力になっていた。
        def pick_enum(node):
            if not isinstance(node, dict):
                return None, []
            if node.get("enum"):
                return node["enum"], node.get("enumNames") or []
            for br in (node.get("anyOf") or node.get("oneOf") or []):
                if isinstance(br, dict) and br.get("enum"):
                    return br["enum"], br.get("enumNames") or []
            return None, []

        enum, names = pick_enum(inner)
        if not enum:
            enum, names = pick_enum(items)
        if not enum:
            enum, names = pick_enum(p)
        choices = []
        for i, v in enumerate((enum or [])[:200]):
            label = names[i] if i < len(names) else None
            choices.append({"value": v, "label": label or str(v)})
        fields.append({
            "name": key,
            "label": p.get("title") or key,
            "description": p.get("description") or "",
            "type": "select" if enum else "text",
            "choices": choices,
        })
    # 呼び出し側が fields で読んでいるので、同じものを両方の名前で返す
    return {"ok": True, "product_type": pt,
            "display_name": meta.get("displayName") or pt,
            "fields": fields,
            "required_fields": fields,
            "auto_filled": sorted(set(k for k in required if k in _FILLED_BY_TOOL)),
            "all_count": len(props)}


# ---------- 出品（Listings Items API） ----------

def build_listing_attributes(draft: dict, product_type: str,
                             extra: dict = None) -> dict:
    """出品に送る attributes を組み立てる。

    Amazonは項目ごとに [{"value": ..., "marketplace_id": ...}] の形を取る。
    素の値を渡すと400になるので、ここで包む。

    ドラフトから埋まるもの（商品名・説明・ブランド・JAN・価格・画像）と、
    商品タイプごとの必須項目（原産国など extra）を混ぜる。
    """
    mp = _RESEARCH_MP

    def one(value, **kw):
        return [{"value": value, "marketplace_id": mp, **kw}]

    a = {}
    a["item_name"] = one(draft.get("rakuten_title") or "")
    if draft.get("brand_name"):
        a["brand"] = one(draft["brand_name"])
    if draft.get("description_pc"):
        # Amazonの商品説明にHTMLタグは使えない。楽天用の表を落とす
        a["product_description"] = one(_strip_html(draft["description_pc"]))

    # 要点（箇条書き）。5個まで
    bullets = draft.get("amazon_bullets") or []
    if bullets:
        a["bullet_point"] = [{"value": b, "marketplace_id": mp}
                             for b in bullets[:5] if str(b).strip()]

    # JANコード。新規出品にはこれが要る
    if draft.get("amazon_jan"):
        a["externally_assigned_product_identifier"] = one(
            draft["amazon_jan"], type="ean")

    # 価格と在庫。在庫は0で作り、実在庫は既存の在庫連携が入れる
    price = draft.get("price")
    if price:
        a["purchasable_offer"] = [{
            "marketplace_id": mp, "currency": "JPY",
            "our_price": [{"schedule": [{"value_with_tax": int(price)}]}],
        }]
    a["fulfillment_availability"] = [{
        "fulfillment_channel_code": "DEFAULT", "quantity": 0,
    }]
    a["condition_type"] = one("new_new")

    # 画像。R-Cabinetに上げたものは楽天用なので使わない。
    # Amazonは公開URLを渡す必要があり、別に用意する
    imgs = [u for u in (draft.get("amazon_image_urls") or []) if u]
    if imgs:
        a["main_product_image_locator"] = [
            {"marketplace_id": mp, "media_location": imgs[0]}]
        if len(imgs) > 1:
            a["other_product_image_locator"] = [
                {"marketplace_id": mp, "media_location": u} for u in imgs[1:9]]

    # 商品タイプごとの必須項目。画面で入れてもらったもの
    for k, v in (extra or {}).items():
        if v is None or str(v).strip() == "":
            continue
        a[k] = one(v)

    return a


def _strip_html(text: str) -> str:
    """HTMLを落として素の文にする。Amazonの説明文にタグは使えない。"""
    import re as _re
    t = _re.sub(r"<br\s*/?>", "\n", text or "", flags=_re.I)
    t = _re.sub(r"</(tr|table|p|div)>", "\n", t, flags=_re.I)
    t = _re.sub(r"<[^>]+>", "", t)
    t = _re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()[:2000]


def submit_listing(sku: str, product_type: str, attributes: dict,
                   issue_locale: str = "ja_JP", validate_only: bool = False) -> dict:
    """1商品をAmazonへ出品する。

    PUTなので、同じSKUへもう一度送ると差し替えになる。新規も更新も
    同じ呼び方でよい。

    validate_only=True なら実際には出品せず、Amazonに中身だけ見てもらう。
    何が足りないかを先に知るために使う（カテゴリごとの必須項目は
    数が多く、先に網羅できないため）。

    戻り値には Amazon が返した問題点（issues）をそのまま入れる。
    何が足りないかは、それを見ないと分からない。
    """
    token = _get_access_token()
    q = {
        "marketplaceIds": _RESEARCH_MP,
        "issueLocale": issue_locale,
    }
    if validate_only:
        q["mode"] = "VALIDATION_PREVIEW"
    params = urllib.parse.urlencode(q)
    url = (f"https://sellingpartnerapi-fe.amazon.com/listings/2021-08-01/items/"
           f"{_seller_id()}/{urllib.parse.quote(sku)}?{params}")
    body = json.dumps({
        "productType": product_type,
        "requirements": "LISTING",
        "attributes": attributes,
    }, ensure_ascii=False).encode()

    req = urllib.request.Request(url, data=body, method="PUT", headers={
        "x-amz-access-token": token,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            r = json.loads(res.read())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:800]
        except Exception:
            pass
        return {"ok": False, "status": e.code, "error": detail}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}

    # ACCEPTED でも issues に警告が入ることがある。そのまま返す
    issues = r.get("issues") or []
    fatal = [i for i in issues if i.get("severity") == "ERROR"]
    return {"ok": r.get("status") == "ACCEPTED" and not fatal,
            "status": r.get("status"), "sku": r.get("sku"),
            "issues": issues}


def fetch_attr_definition(product_type: str, name: str) -> dict:
    """商品タイプの定義から、1項目ぶんをそのまま返す。

    選択肢が enum なのか examples なのか、どこに入っているかは
    項目によって違う。画面に出ないときはここで中身を見る。
    """
    pt = (product_type or "").strip().upper()
    try:
        params = urllib.parse.urlencode({
            "marketplaceIds": _RESEARCH_MP, "sellerId": _seller_id(),
            "productTypeVersion": "LATEST", "locale": "ja_JP",
        })
        meta = _call_sp_api(
            f"/definitions/2020-09-01/productTypes/{pt}?{params}")
        url = (meta.get("schema") or {}).get("link", {}).get("resource")
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as res:
            schema = json.loads(res.read())
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    prop = (schema.get("properties") or {}).get(name)
    if prop is None:
        return {"ok": False, "error": "その項目は定義にありません"}
    return {"ok": True, "name": name, "definition": prop}
