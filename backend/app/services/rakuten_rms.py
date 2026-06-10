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
    過去90日間の受注データを取得し、
    SKUごとの販売数を {sku: {"recent": N, "prev": N, "total_90": N, "stockout_days": N}} 形式で返す
    recent = 直近30日、prev = 31〜60日前、total_90 = 90日合計
    stockout_days = 注文0件の日数（在庫切れ日数の近似）
    """
    headers = _auth_header(service_secret, license_key)
    now = datetime.now()
    start_dt = now - timedelta(days=days)

    # 注文検索（最小限のパラメータ）
    search_body = {
        "dateType": 1,
        "startDatetime": start_dt.strftime("%Y-%m-%dT00:00:00+0900"),
        "endDatetime": now.strftime("%Y-%m-%dT00:00:00+0900"),
        "PaginationRequestModel": {
            "requestRecordsAmount": 1000,
            "requestPage": 1,
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

    # searchOrder のレスポンス構造に合わせて注文番号を取り出す
    # ["order1", "order2"] の場合と [{"orderNumber": "order1"}] の場合の両方に対応
    raw_list = data.get("orderNumberList") or []
    order_numbers = []
    for item in raw_list:
        if isinstance(item, str):
            order_numbers.append(item)
        elif isinstance(item, dict):
            num = item.get("orderNumber") or item.get("order_number") or item.get("id")
            if num:
                order_numbers.append(str(num))

    if not order_numbers:
        return {}

    # 注文詳細を取得（最大100件ずつ）
    # {sku: {date_str: qty}} で日別販売数を集計
    sku_daily: dict[str, dict] = {}
    cutoff_recent = now - timedelta(days=30)   # 直近30日の境界
    cutoff_prev   = now - timedelta(days=60)   # 31〜60日の境界

    for i in range(0, len(order_numbers), 10):
        batch = order_numbers[i:i+10]
        detail_body = {"orderNumberList": batch}
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"{RMS_BASE}/2.0/order/getOrder",
                headers={**headers, "Content-Type": "application/json; charset=utf-8"},
                content=json.dumps(detail_body, ensure_ascii=False).encode("utf-8"),
            )
            if not res.is_success:
                # エラー内容をraiseせず次のバッチへ（部分取得を継続）
                continue
            detail_data = res.json()

        for order in detail_data.get("orderModelList", []):
            order_date_str = order.get("orderDatetime", "")
            try:
                order_date = datetime.fromisoformat(order_date_str.replace("+0900", "+09:00"))
            except Exception:
                order_date = now - timedelta(days=15)

            # キャンセル除外
            if order.get("orderProgress", 0) == 900:
                continue

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

    # 集計: recent(30日), prev(31〜60日), total_90, stockout_days
    sku_sales: dict[str, dict] = {}
    for sku, daily in sku_daily.items():
        recent = prev = total_90 = 0
        for day_str, qty in daily.items():
            try:
                d = datetime.strptime(day_str, "%Y-%m-%d")
            except Exception:
                continue
            total_90 += qty
            if d >= cutoff_recent:
                recent += qty
            elif d >= cutoff_prev:
                prev += qty

        # 在庫切れ日数は在庫管理機能実装後に正確に計算（現在は0）
        stockout_days = 0

        sku_sales[sku] = {
            "recent":       recent,
            "prev":         prev,
            "total_90":     total_90,
            "stockout_days": stockout_days,
        }

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
