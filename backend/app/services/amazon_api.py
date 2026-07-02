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
_CACHE_TTL = 4200       # 売上データ: 70分（毎時のウォームアップcronに余裕を持たせる）
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
            **({"nextToken": next_token} if next_token else {}),
        })
        data = _call_sp_api(f"/fba/inventory/v1/summaries?{params}")

        for item in data.get("payload", {}).get("inventorySummaries", []):
            fnsku = item.get("fnSku", "")
            asin = item.get("asin", "")
            # fulfillableQuantity=0（売り切れ）は正しい0として扱う。
            # `or` だと0が偽扱いされtotalQuantity(返品処理中等を含む)に化けて
            # 売り切れ商品に幽霊在庫が出るため、None判定にする。
            fulfillable = item.get("fulfillableQuantity")
            result[fnsku] = {
                "fnsku": fnsku,
                "asin": asin,
                "sku": item.get("sellerSku", ""),
                "name": item.get("productName", ""),
                "available": fulfillable if fulfillable is not None else item.get("totalQuantity", 0),
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
    """1ASIN×1期間の日販を取得。失敗時はNoneを返す（0.0を返すと「売れていない」と
    区別できず、レート制限失敗が日販の過小評価→発注推奨から漏れる事故になるため）"""
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
        return asin, None


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

    period_results = {d: {a: None for a in asin_list} for d in missing_periods}
    tasks = [(a, d) for a in asin_list for d in missing_periods]

    # 並列数を抑えてレート制限(429)自体を減らす（10だと429多発で欠損が出ていた）
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_fetch_sales_one, a, d, end_dt): (a, d) for a, d in tasks}
        for f in as_completed(futures):
            asin, val = f.result()
            a, d = futures[f]
            period_results[d][a] = val

    # 失敗(None)分は間隔を空けて順次リトライ。それでも失敗したものだけ0にする
    import logging
    failed = [(d, a) for d in missing_periods for a, v in period_results[d].items() if v is None]
    for d, a in failed:
        time.sleep(1)
        _, v = _fetch_sales_one(a, d, end_dt)
        if v is None:
            logging.getLogger("amazon").warning(f"売上取得失敗(0扱い): asin={a} period={d}d")
            v = 0.0
        period_results[d][a] = v

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
            revenue = sum(m.get("totalSales", m.get("orderedProductSales", {})).get("amount", 0) for m in payload)
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
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_fetch_one, asin): asin for asin in asin_list}
        for f in as_completed(futures):
            asin, val = f.result()
            result[asin] = val

    _cache_set(cache_key, result)
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
    """Feeds APIで出品価格を更新。戻り値: (success: bool, error_msg: str)"""
    mp = "A1VC38T7YXB528"
    token = _get_access_token()

    xml_body = f'''<?xml version="1.0" encoding="utf-8"?>
<AmazonEnvelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="amznenvelope.xsd">
  <Header><DocumentVersion>1.01</DocumentVersion><MerchantIdentifier>A29K12KTHSASJ0</MerchantIdentifier></Header>
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
