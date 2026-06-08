from typing import Dict, List
import urllib.parse
import urllib.request
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.core.config import settings

_token_cache = {"token": None, "expires_at": 0}

# サーバー側キャッシュ
_cache: Dict[str, dict] = {}
_CACHE_TTL = 3600       # 売上データ: 1時間
_CACHE_TTL_LONG = 86400 # 画像・在庫など: 1日

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
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep((attempt + 1) * 2)
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
            **({"nextToken": next_token} if next_token else {}),
        })
        data = _call_sp_api(f"/fba/inventory/v1/summaries?{params}")

        for item in data.get("payload", {}).get("inventorySummaries", []):
            fnsku = item.get("fnSku", "")
            asin = item.get("asin", "")
            result[fnsku] = {
                "fnsku": fnsku,
                "asin": asin,
                "sku": item.get("sellerSku", ""),
                "name": item.get("productName", ""),
                "available": item.get("fulfillableQuantity") or item.get("totalQuantity", 0),
                "inbound": item.get("inboundWorkingQuantity", 0) + item.get("inboundShippedQuantity", 0) + item.get("inboundReceivingQuantity", 0),
                "processing": item.get("reservedQuantity", 0),
            }

        next_token = data.get("pagination", {}).get("nextToken")
        if not next_token:
            break

    _cache_set("inventory", result)
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

def _fetch_sales_one(asin: str, days: int, end_dt) -> tuple:
    from datetime import timedelta
    mp = "A1VC38T7YXB528"
    start = end_dt - timedelta(days=days)
    try:
        params = urllib.parse.urlencode({
            "marketplaceIds": mp,
            "interval": f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}--{end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "granularity": "Total",
            "asin": asin,
        })
        data = _call_sp_api(f"/sales/v1/orderMetrics?{params}")
        units = sum(m.get("unitCount", 0) for m in data.get("payload", []))
        return asin, round(units / days, 4)
    except Exception:
        return asin, 0.0


def fetch_all_sales(asin_list: List[str]) -> tuple:
    """7/15/30/60/90日の売上を全ASIN×全期間で並列一括取得。now()を1回固定して集計期間のブレをなくす"""
    from datetime import datetime, timezone
    periods = [7, 15, 30, 60, 90]

    # キャッシュチェック
    cached_results = {}
    missing_periods = set()
    for d in periods:
        cached = _cache_get(f"sales_{d}")
        if cached is not None:
            cached_results[d] = cached
        else:
            missing_periods.add(d)

    if not missing_periods:
        return (cached_results[7], cached_results[15], cached_results[30], cached_results[60], cached_results[90])

    # now()を1回だけ取得して全タスクで共有（期間のブレをなくす）
    end_dt = datetime.now(timezone.utc)

    period_results = {d: {a: 0.0 for a in asin_list} for d in missing_periods}
    tasks = [(a, d) for a in asin_list for d in missing_periods]

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_sales_one, a, d, end_dt): (a, d) for a, d in tasks}
        for f in as_completed(futures):
            asin, val = f.result()
            a, d = futures[f]
            period_results[d][a] = val

    for d in missing_periods:
        _cache_set(f"sales_{d}", period_results[d])
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
            revenue = sum(m.get("orderedProductSales", {}).get("amount", 0) for m in payload)
            avg_price = round(revenue / units, 0) if units > 0 else 0
            return asin, {"units": units, "revenue": round(revenue, 0), "avg_price": avg_price}
        except Exception:
            return asin, {"units": 0, "revenue": 0, "avg_price": 0}

    result = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_one, asin): asin for asin in asin_list}
        for f in as_completed(futures):
            asin, val = f.result()
            result[asin] = val

    _cache_set(cache_key, result)
    return result


def _fetch_price_and_fee_one(sku: str) -> tuple:
    """1SKUの出品価格とFBA手数料を取得。戻り値: (sku, selling_price, fba_fee)"""
    mp = "A1VC38T7YXB528"
    selling_price = None
    fba_fee = None

    # 出品価格取得
    try:
        params = urllib.parse.urlencode({"MarketplaceId": mp, "Skus": sku})
        data = _call_sp_api(f"/products/pricing/v0/price?ItemType=Sku&{params}")
        items = data.get("payload", [])
        if items and items[0].get("status") == "Success":
            offers = items[0].get("Product", {}).get("Offers", [])
            if offers:
                selling_price = offers[0].get("BuyingPrice", {}).get("ListingPrice", {}).get("Amount")
    except Exception:
        pass

    # FBA手数料取得（出品価格が取れた場合のみ）
    if selling_price:
        try:
            body = json.dumps({
                "FeesEstimateRequest": {
                    "MarketplaceId": mp,
                    "IsAmazonFulfilled": True,
                    "PriceToEstimateFees": {
                        "ListingPrice": {"CurrencyCode": "JPY", "Amount": selling_price},
                        "Shipping": {"CurrencyCode": "JPY", "Amount": 0},
                    },
                    "Identifier": sku,
                }
            }).encode()
            token = _get_access_token()
            req = urllib.request.Request(
                f"https://sellingpartnerapi-fe.amazon.com/products/fees/v0/listings/{urllib.parse.quote(sku, safe='')}/feesEstimate",
                data=body,
                method="POST",
                headers={
                    "x-amz-access-token": token,
                    "Content-Type": "application/json",
                }
            )
            with urllib.request.urlopen(req, timeout=15) as res:
                fee_data = json.loads(res.read())
            total_fee = (fee_data.get("payload", {})
                         .get("FeesEstimateResult", {})
                         .get("FeesEstimate", {})
                         .get("TotalFeesEstimate", {})
                         .get("Amount"))
            if total_fee is not None:
                fba_fee = float(total_fee)
        except Exception:
            pass

    return sku, selling_price, fba_fee


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


def update_listing_price(sku: str, price: float) -> bool:
    """SP-API Listings Items APIで出品価格を更新。成功でTrue"""
    mp = "A1VC38T7YXB528"
    token = _get_access_token()
    body = json.dumps({
        "productType": "PRODUCT",
        "patches": [
            {
                "op": "replace",
                "path": "/attributes/list_price",
                "value": [{"currency_code": "JPY", "value": round(price)}],
            }
        ],
    }).encode()
    req = urllib.request.Request(
        f"https://sellingpartnerapi-fe.amazon.com/listings/2022-04-01/items/{urllib.parse.quote(sku, safe='')}",
        data=body,
        method="PATCH",
        headers={
            "x-amz-access-token": token,
            "Content-Type": "application/json",
            "marketplaceIds": mp,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            result = json.loads(res.read())
        return result.get("status") == "ACCEPTED"
    except Exception:
        return False


def fetch_prices_and_fees(sku_list: List[str]) -> Dict[str, dict]:
    """全SKUの出品価格・FBA手数料を並列取得。戻り値: {sku: {selling_price, fba_fee}}"""
    result = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_fetch_price_and_fee_one, sku): sku for sku in sku_list}
        for f in as_completed(futures):
            sku, selling_price, fba_fee = f.result()
            result[sku] = {"selling_price": selling_price, "fba_fee": fba_fee}
    return result
