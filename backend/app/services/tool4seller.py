"""Tool4Seller APIからグローバル評価（rating）を取得するサービス"""
import urllib.request
import urllib.parse
import json
import time
from typing import Dict, Optional
from datetime import datetime, timedelta

from app.core.config import settings

_token_cache = {"token": None, "shop_id": None, "expires_at": 0}

_CACHE_TTL = 3600  # JWTは1時間キャッシュ

_rating_cache: Dict[str, dict] = {}
_RATING_CACHE_TTL = 3600  # 評価は1時間キャッシュ


def _login() -> tuple[str, str]:
    """Tool4Sellerにログインし (jwt_token, shop_id) を返す"""
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

    # shop_idは環境変数から取得（未設定時は空文字→Das-Current-Shopヘッダーなし）
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
    """parentASIN→{rating, promotion}のマップを返す。
    ratingは評価（常に最新30日で取得）、promotionは期間内のVINE等プロモーション売上。
    """
    cache_key = f"t4s_product_data_{days}"
    entry = _rating_cache.get(cache_key)
    if entry and time.time() < entry["expires_at"]:
        return entry["value"]

    try:
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

        _rating_cache[cache_key] = {"value": result, "expires_at": time.time() + _RATING_CACHE_TTL}
        return result

    except Exception as e:
        raise Exception(f"Tool4Seller データ取得失敗: {e}")


def fetch_ratings(asin_list: list) -> Dict[str, Optional[float]]:
    """後方互換: fetch_product_dataのratingのみ返す"""
    data = fetch_product_data(asin_list, days=30)
    return {asin: v["rating"] for asin, v in data.items()}
