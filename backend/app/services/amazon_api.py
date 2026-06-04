from typing import Dict, List
import urllib.parse
import urllib.request
import json
import time
from app.core.config import settings

_token_cache = {"token": None, "expires_at": 0}

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
            with urllib.request.urlopen(req) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep((attempt + 1) * 2)
                continue
            body = e.read().decode()
            raise Exception(f"HTTP {e.code}: {body}")
    raise Exception("SP-API rate limited after retries: " + path)

def fetch_inventory() -> Dict[str, dict]:
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

def fetch_sales(days: int, asin_list: List[str]) -> Dict[str, float]:
    from datetime import datetime, timedelta, timezone
    mp = "A1VC38T7YXB528"
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    result = {}
    for asin in asin_list:
        try:
            params = urllib.parse.urlencode({
                "marketplaceIds": mp,
                "interval": f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}--{end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "granularity": "Total",
                "asin": asin,
            })
            data = _call_sp_api(f"/sales/v1/orderMetrics?{params}")
            units = sum(m.get("unitCount", 0) for m in data.get("payload", []))
            result[asin] = round(units / days, 4)
        except Exception:
            result[asin] = 0.0

    return result
