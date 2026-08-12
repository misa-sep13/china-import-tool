import httpx
import logging

logger = logging.getLogger("rakuten_seo")

SEARCH_API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
MISORA_SHOP_CODE = "misora-mart"
HITS_PER_PAGE = 30


async def check_ranking(keyword: str, shop_code: str = MISORA_SHOP_CODE,
                        max_pages: int = 8) -> dict:
    """楽天ウェブサービス IchibaItem/Search で自店舗の検索順位を調べる。
    sort=standardで楽天の検索結果と同じ並び順を取得する。"""
    from app.core.config import settings

    if not settings.RAKUTEN_APP_ID or not settings.RAKUTEN_ACCESS_KEY:
        raise Exception("RAKUTEN_APP_ID/RAKUTEN_ACCESS_KEYが未設定です")

    my_ranks = []
    total_items = 0

    async with httpx.AsyncClient(timeout=20) as client:
        for page in range(1, max_pages + 1):
            params = {
                "applicationId": settings.RAKUTEN_APP_ID,
                "accessKey": settings.RAKUTEN_ACCESS_KEY,
                "keyword": keyword,
                "sort": "standard",
                "hits": HITS_PER_PAGE,
                "page": page,
            }
            try:
                resp = await client.get(SEARCH_API_URL, params=params)
                if not resp.is_success:
                    logger.warning(f"楽天API検索エラー: {resp.status_code} keyword={keyword} page={page} body={resp.text[:300]}")
                    break
                data = resp.json()
            except Exception as e:
                logger.warning(f"楽天API検索リクエスト失敗: keyword={keyword} page={page} error={e}")
                break

            if page == 1:
                total_items = data.get("count", 0)

            items = data.get("Items", [])
            if not items:
                break

            for i, wrapped in enumerate(items):
                item = wrapped.get("Item", wrapped)
                rank = (page - 1) * HITS_PER_PAGE + i + 1
                if item.get("shopCode") == shop_code:
                    my_ranks.append({
                        "rank": rank,
                        "page": page,
                        "card_type": "item",
                    })

            if len(items) < HITS_PER_PAGE:
                break
            if page * HITS_PER_PAGE >= total_items:
                break

    return {
        "keyword": keyword,
        "shop_id": shop_code,
        "total_items": total_items,
        "searched_pages": max_pages,
        "my_ranks": my_ranks,
    }
