from typing import Dict, List
from app.core.config import settings

def get_sp_api_client():
    from sp_api.api import Inventories, Sales
    from sp_api.base import Marketplaces, Credentials
    creds = Credentials(
        refresh_token=settings.SP_API_REFRESH_TOKEN,
        lwa_app_id=settings.SP_API_LWA_APP_ID,
        lwa_client_secret=settings.SP_API_LWA_CLIENT_SECRET,
        aws_access_key=settings.SP_API_AWS_ACCESS_KEY,
        aws_secret_key=settings.SP_API_AWS_SECRET_KEY,
        role_arn=settings.SP_API_ROLE_ARN,
    )
    marketplace = getattr(Marketplaces, settings.SP_API_MARKETPLACE)
    return creds, marketplace

def fetch_inventory() -> Dict[str, dict]:
    """FBA在庫データを取得。{fnsku: {available, inbound, ...}}"""
    from sp_api.api import Inventories
    from sp_api.base import Marketplaces
    creds, marketplace = get_sp_api_client()
    inv = Inventories(credentials=creds, marketplace=marketplace)

    result = {}
    next_token = None
    while True:
        kwargs = {"details": True, "granularityType": "Marketplace",
                  "granularityId": "A1VC38T7YXB528"}
        if next_token:
            kwargs["nextToken"] = next_token
        res = inv.get_inventory_summary_marketplace(**kwargs)
        for item in res.payload.get("inventorySummaries", []):
            fnsku = item.get("fnSku", "")
            asin = item.get("asin", "")
            details = item.get("inventoryDetails", {})
            result[fnsku] = {
                "fnsku": fnsku,
                "asin": asin,
                "available": item.get("fulfillableQuantity", 0),
                "inbound": (
                    details.get("inboundWorkingQuantity", 0) +
                    details.get("inboundShippedQuantity", 0) +
                    details.get("inboundReceivingQuantity", 0)
                ),
                "processing": details.get("reservedQuantity", {}).get("totalReservedQuantity", 0),
            }
        next_token = res.payload.get("nextToken")
        if not next_token:
            break
    return result

def fetch_sales(days: int, asin_list: List[str]) -> Dict[str, float]:
    """ASINごとの日販（指定日数の平均）を返す。{asin: daily_avg}"""
    from sp_api.api import SalesV1
    from sp_api.base import Marketplaces
    from datetime import datetime, timedelta, timezone
    creds, marketplace = get_sp_api_client()
    sales_api = SalesV1(credentials=creds, marketplace=marketplace)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    result = {}
    # SP-APIは一度に1ASINずつ or バッチで取得
    for asin in asin_list:
        try:
            res = sales_api.get_order_metrics(
                marketplaceIds=[marketplace.marketplace_id],
                interval=f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                granularity="Total",
                asin=asin,
            )
            units = sum(m.get("unitCount", 0) for m in res.payload)
            result[asin] = round(units / days, 4)
        except Exception:
            result[asin] = 0.0
    return result
