"""Tool4Seller APIからグローバル評価・プロモーション売上を取得するサービス"""
import urllib.request
import json
import time
from typing import Dict, Optional
from datetime import datetime, timedelta

from app.core.config import settings

_token_cache = {"token": None, "shop_id": None, "expires_at": 0}
_CACHE_TTL = 3600  # JWT 1時間

# キャッシュキー: "t4s_{days}_{YYYY-MM-DD}" → 日付が変わるまで再利用
_data_cache: Dict[str, dict] = {}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _login() -> tuple[str, str]:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"], _token_cache["shop_id"]

    if not settings.TOOL4SELLER_EMAIL or not settings.TOOL4SELLER_PASSWORD:
        raise Exception("TOOL4SELLER_EMAIL / TOOL4SELLER_PASSWORD が未設定です")

    body = json.dumps({
        "userName": settings.TOOL4SELLER_EMAIL,
        "password": settings.TOOL4SELLER_PASSWORD,
    }).encode()

    req = urllib.request.Request(
        "https://das-server.tool4seller.com/user/login",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://data.tool4seller.com",
            "Referer": "https://data.tool4seller.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        data = json.loads(res.read())

    if data.get("status") != 1:
        raise Exception(f"Tool4Seller ログイン失敗: {data}")

    content = data.get("content", {})
    token = content.get("token") or content.get("tokenInfo", {}).get("token")
    if not token:
        raise Exception(f"Tool4Seller: tokenが取得できません: {content}")

    shop_id = getattr(settings, "TOOL4SELLER_SHOP_ID", None) or ""
    _token_cache["token"] = token
    _token_cache["shop_id"] = shop_id
    _token_cache["expires_at"] = time.time() + _CACHE_TTL
    return token, shop_id


def _call_t4s(path: str, body: dict) -> dict:
    token, shop_id = _login()
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"https://das-server.tool4seller.com{path}",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}",
            "Das-Current-Shop": shop_id,
            "Das-Current-Shops": shop_id,
            "Displaylanguage": "ja_jp",
            "Origin": "https://data.tool4seller.com",
            "Referer": "https://data.tool4seller.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read())


def fetch_product_data(asin_list: list, days: int = 30) -> Dict[str, dict]:
    """parentASIN→{rating, promotion, orders}のマップを返す。
    キャッシュは日付単位（日付が変わるまで再利用）。
    """
    today = _today()
    cache_key = f"t4s_{days}_{today}"

    # 古い日付のキャッシュを削除
    stale = [k for k in _data_cache if not k.endswith(today)]
    for k in stale:
        del _data_cache[k]

    if cache_key in _data_cache:
        return _data_cache[cache_key]

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    result = {}
    current_page = 1
    page_size = 100

    while True:
        resp = _call_t4s("/profitInfo/multi/list", {
            "pageSize": page_size,
            "currentPage": current_page,
            "type": "parentAsin",
            "topSort": True,
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "sortColumn": "totalQuantity",
            "sortType": "desc",
        })

        if resp.get("status") != 1:
            break

        content = resp.get("content", {})
        items = content.get("result", [])

        for item in items:
            asin = item.get("parentAsin")
            if asin:
                result[asin] = {
                    "rating":    item.get("rating"),
                    "promotion": item.get("promotion") or 0,
                    "orders":    item.get("orders") or 0,
                }

        total_page = content.get("totalPage", 1)
        if current_page >= total_page:
            break
        current_page += 1

    _data_cache[cache_key] = result
    return result


def fetch_ratings(asin_list: list) -> Dict[str, Optional[float]]:
    """後方互換: fetch_product_dataのratingのみ返す"""
    data = fetch_product_data(asin_list, days=30)
    return {asin: v["rating"] for asin, v in data.items()}
