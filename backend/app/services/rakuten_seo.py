import httpx
from bs4 import BeautifulSoup
import logging
import asyncio
import re

logger = logging.getLogger("rakuten_seo")

SEARCH_URL = "https://search.rakuten.co.jp/search/mall/{keyword}/"
MISORA_SHOP_ID = "411150"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def check_ranking(keyword: str, shop_id: str = MISORA_SHOP_ID,
                        max_pages: int = 5) -> dict:
    results = []
    my_ranks = []
    total_items = 0

    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=HEADERS) as client:
        for page in range(1, max_pages + 1):
            url = SEARCH_URL.format(keyword=httpx.URL(keyword).raw_path.decode() if False else keyword)
            params = {}
            if page > 1:
                params["p"] = page
            try:
                resp = await client.get(
                    f"https://search.rakuten.co.jp/search/mall/{keyword}/",
                    params=params,
                )
                if not resp.is_success:
                    logger.warning(f"楽天検索エラー: {resp.status_code} page={page}")
                    break
            except Exception as e:
                logger.warning(f"楽天検索リクエスト失敗: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")

            if page == 1:
                count_el = soup.select_one("._count")
                if count_el:
                    m = re.search(r"[\d,]+", count_el.text)
                    if m:
                        total_items = int(m.group().replace(",", ""))

            cards = soup.select("[data-track-container] .searchresultitem, .dui-card.searchresultitem, div.searchresultitem")
            if not cards:
                cards = soup.select("[class*='searchresultitem']")

            if not cards:
                break

            page_size = len(cards)
            for i, card in enumerate(cards):
                rank = (page - 1) * 45 + i + 1
                card_shop_id = card.get("data-shop-id", "")
                card_type = card.get("data-card-type", "item")

                if str(card_shop_id) == str(shop_id):
                    my_ranks.append({
                        "rank": rank,
                        "page": page,
                        "card_type": card_type,
                    })

            if page_size < 45:
                break

            await asyncio.sleep(1.5)

    return {
        "keyword": keyword,
        "shop_id": shop_id,
        "total_items": total_items,
        "searched_pages": min(max_pages, max(1, len(results) + 1 if not my_ranks else max_pages)),
        "my_ranks": my_ranks,
    }
