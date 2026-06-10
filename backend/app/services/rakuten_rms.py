"""
楽天RMS API サービス
受注データを取得してバリエーション別30日販売数を集計する
"""
import base64
import json
from datetime import datetime, timedelta, date
from typing import Optional
import httpx


RMS_BASE = "https://api.rms.rakuten.co.jp/es"


def _auth_header(service_secret: str, license_key: str) -> dict:
    token = base64.b64encode(f"{service_secret}:{license_key}".encode()).decode()
    return {"Authorization": f"ESA {token}"}


async def fetch_sales_by_sku(
    service_secret: str,
    license_key: str,
    days: int = 60,
) -> dict:
    """
    過去 days 日間の受注データを取得し、
    SKUごとの販売数を {sku: {"recent": N, "prev": N}} 形式で返す
    recent = 直近30日、prev = 31〜60日前
    """
    headers = _auth_header(service_secret, license_key)
    now = datetime.now()
    start_dt = now - timedelta(days=days)

    # 注文検索
    search_body = {
        "dateType": 1,  # 1=注文日
        "startDatetime": start_dt.strftime("%Y-%m-%dT00:00:00+0900"),
        "endDatetime": now.strftime("%Y-%m-%dT23:59:59+0900"),
        "orderProgressList": [100, 200, 300, 400, 500, 600],  # 全ステータス
        "PaginationRequestModel": {
            "requestRecordsAmount": 1000,
            "requestPage": 1,
            "SortModelList": [{"sortColumn": 2, "sortDirection": 1}],
        },
    }

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{RMS_BASE}/2.0/order/searchOrder",
            headers={**headers, "Content-Type": "application/json; charset=utf-8"},
            content=json.dumps(search_body, ensure_ascii=False).encode("utf-8"),
        )
        res.raise_for_status()
        data = res.json()

    order_numbers = []
    pagination = data.get("PaginationResponseModel", {})
    total = pagination.get("totalRecords", 0)
    for order in data.get("orderNumberList", []):
        order_numbers.append(order)

    if not order_numbers:
        return {}

    # 注文詳細を取得（最大100件ずつ）
    sku_sales: dict[str, dict] = {}
    cutoff_recent = now - timedelta(days=30)  # 直近30日の境界

    for i in range(0, len(order_numbers), 100):
        batch = order_numbers[i:i+100]
        detail_body = {"orderNumberList": batch}
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"{RMS_BASE}/2.0/order/getOrder",
                headers={**headers, "Content-Type": "application/json; charset=utf-8"},
                content=json.dumps(detail_body, ensure_ascii=False).encode("utf-8"),
            )
            res.raise_for_status()
            detail_data = res.json()

        for order in detail_data.get("orderModelList", []):
            # 注文日を取得
            order_date_str = order.get("orderDatetime", "")
            try:
                order_date = datetime.fromisoformat(order_date_str.replace("+0900", "+09:00"))
            except Exception:
                order_date = now - timedelta(days=15)

            is_recent = order_date >= cutoff_recent

            # キャンセル除外
            if order.get("orderProgress", 0) == 900:
                continue

            # 商品明細からSKUと数量を取得
            for package in order.get("PackageModelList", []):
                for item in package.get("ItemModelList", []):
                    sku = item.get("manageNumber", "")  # 楽天商品管理番号
                    if not sku:
                        # システム連携用SKU番号も試みる
                        sku = item.get("itemNumber", "")
                    if not sku:
                        continue
                    qty = item.get("units", 1) or 1

                    if sku not in sku_sales:
                        sku_sales[sku] = {"recent": 0, "prev": 0}

                    if is_recent:
                        sku_sales[sku]["recent"] += qty
                    else:
                        sku_sales[sku]["prev"] += qty

    return sku_sales


async def test_connection(service_secret: str, license_key: str) -> dict:
    """接続テスト - 注文検索APIで確認"""
    headers = _auth_header(service_secret, license_key)
    # 直近1日の注文を1件だけ検索してAPIの疎通確認
    from datetime import datetime, timedelta
    now = datetime.now()
    body = {
        "dateType": 1,
        "startDatetime": (now - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+0900"),
        "endDatetime": now.strftime("%Y-%m-%dT23:59:59+0900"),
        "orderProgressList": [100],
        "PaginationRequestModel": {
            "requestRecordsAmount": 1,
            "requestPage": 1,
            "SortModelList": [{"sortColumn": 2, "sortDirection": 1}],
        },
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
