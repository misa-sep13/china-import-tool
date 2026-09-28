import asyncio
import httpx
import logging

logger = logging.getLogger("rakuten_seo")

SEARCH_API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
MISORA_SHOP_CODE = "misora-mart"
HITS_PER_PAGE = 30
# 楽天ウェブサービスは1秒に1回ほどの呼び出しを想定している。
# 間を空けずに続けて投げると 429（呼びすぎ）が返り、1ページ目から
# 何も取れないまま「圏外」として記録されていた
WAIT_SEC = 1.1
RETRY_WAIT_SEC = 5.0
MAX_RETRY = 3


async def check_ranking(keyword: str, shop_code: str = MISORA_SHOP_CODE,
                        max_pages: int = 8) -> dict:
    """楽天ウェブサービス IchibaItem/Search で自店舗の検索順位を調べる。
    sort=standardで楽天の検索結果と同じ並び順を取得する。"""
    from app.core.config import settings

    if not settings.RAKUTEN_APP_ID or not settings.RAKUTEN_ACCESS_KEY:
        raise Exception("RAKUTEN_APP_ID/RAKUTEN_ACCESS_KEYが未設定です")

    my_ranks = []
    total_items = 0
    debug_error = None

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
            # 呼びすぎ（429）は少し待てば通る。ここで諦めると
            # 順位があるのに「圏外」として残ってしまう
            data = None
            for attempt in range(MAX_RETRY):
                if page > 1 or attempt > 0:
                    await asyncio.sleep(WAIT_SEC if attempt == 0 else RETRY_WAIT_SEC)
                try:
                    resp = await client.get(SEARCH_API_URL, params=params)
                except Exception as e:
                    logger.warning(f"楽天API検索リクエスト失敗: keyword={keyword} page={page} error={e}")
                    debug_error = f"request error: {e}"
                    continue
                if resp.status_code == 429:
                    logger.info(f"楽天API 429（呼びすぎ）: keyword={keyword} page={page} {attempt + 1}回目")
                    debug_error = "429: 呼びすぎです（間を空けて取り直します）"
                    continue
                if not resp.is_success:
                    logger.warning(f"楽天API検索エラー: {resp.status_code} keyword={keyword} page={page} body={resp.text[:300]}")
                    debug_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    break
                try:
                    data = resp.json()
                    debug_error = None
                except Exception as e:
                    debug_error = f"応答を読めませんでした: {e}"
                break
            if data is None:
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
        "debug_error": debug_error,
    }
