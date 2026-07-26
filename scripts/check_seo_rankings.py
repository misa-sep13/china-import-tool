"""SEO順位を楽天検索からチェックしてRenderに送信するスクリプト（GH Actions用）"""
import httpx
from bs4 import BeautifulSoup
import re
import time
import os
from datetime import datetime, timezone, timedelta

BACKEND = os.environ.get("BACKEND_URL", "https://china-import-tool.onrender.com")
SHOP_ID = "411150"
SEARCH_URL = "https://search.rakuten.co.jp/search/mall/{keyword}/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
MAX_PAGES = 5
JST = timezone(timedelta(hours=9))


def scrape_ranking(client: httpx.Client, keyword: str) -> dict:
    my_ranks = []
    total_items = 0

    for page in range(1, MAX_PAGES + 1):
        params = {}
        if page > 1:
            params["p"] = page
        try:
            resp = client.get(
                SEARCH_URL.format(keyword=keyword),
                params=params,
                headers=HEADERS,
                timeout=20,
                follow_redirects=True,
            )
            if not resp.is_success:
                print(f"  WARNING: HTTP {resp.status_code} for '{keyword}' page={page}")
                break
        except Exception as e:
            print(f"  WARNING: Request failed for '{keyword}' page={page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        if page == 1:
            count_el = soup.select_one("._count")
            if count_el:
                m = re.search(r"[\d,]+", count_el.text)
                if m:
                    total_items = int(m.group().replace(",", ""))

        cards = soup.select(
            "[data-track-container] .searchresultitem, "
            ".dui-card.searchresultitem, "
            "div.searchresultitem"
        )
        if not cards:
            cards = soup.select("[class*='searchresultitem']")
        if not cards:
            break

        page_size = len(cards)
        for i, card in enumerate(cards):
            rank = (page - 1) * 45 + i + 1
            card_shop_id = card.get("data-shop-id", "")
            card_type = card.get("data-card-type", "item")
            if str(card_shop_id) == SHOP_ID:
                my_ranks.append({"rank": rank, "page": page, "card_type": card_type})

        if page_size < 45:
            break
        time.sleep(1.5)

    return {"keyword": keyword, "total_items": total_items, "my_ranks": my_ranks}


def main():
    with httpx.Client(timeout=30) as api:
        res = api.get(f"{BACKEND}/api/seo/keywords?active_only=true")
        res.raise_for_status()
        keywords = res.json().get("keywords", [])

    print(f"チェック対象: {len(keywords)}件")
    if not keywords:
        return

    now = datetime.now(JST)
    checked_at = now.isoformat()
    results = []
    errors = 0

    with httpx.Client() as scraper:
        for i, kw in enumerate(keywords):
            print(f"[{i+1}/{len(keywords)}] {kw['keyword']} (SKU: {kw.get('product_sku', '-')})")
            try:
                data = scrape_ranking(scraper, kw["keyword"])
            except Exception as e:
                print(f"  ERROR: {e}")
                errors += 1
                results.append({
                    "seo_keyword_id": kw["id"],
                    "keyword": kw["keyword"],
                    "product_sku": kw.get("product_sku"),
                    "rank": None,
                    "page": None,
                    "total_items": None,
                    "card_type": None,
                })
                continue

            if data["my_ranks"]:
                for r in data["my_ranks"]:
                    results.append({
                        "seo_keyword_id": kw["id"],
                        "keyword": kw["keyword"],
                        "product_sku": kw.get("product_sku"),
                        "rank": r["rank"],
                        "page": r["page"],
                        "total_items": data["total_items"],
                        "card_type": r["card_type"],
                    })
                    best = min(r["rank"] for r in data["my_ranks"])
                    print(f"  -> {best}位")
            else:
                results.append({
                    "seo_keyword_id": kw["id"],
                    "keyword": kw["keyword"],
                    "product_sku": kw.get("product_sku"),
                    "rank": None,
                    "page": None,
                    "total_items": data["total_items"],
                    "card_type": None,
                })
                print("  -> 圏外")

            time.sleep(2)

    print(f"\nスクレイピング完了: {len(results)}件, エラー: {errors}件")

    BATCH = 100
    with httpx.Client(timeout=300) as api:
        for i in range(0, len(results), BATCH):
            batch = results[i:i + BATCH]
            res = api.post(
                f"{BACKEND}/api/seo/rankings/bulk",
                json={"checked_at": checked_at, "results": batch},
            )
            res.raise_for_status()
            r = res.json()
            print(f"  送信済み: {r.get('imported', 0)}件")

    print("完了")


if __name__ == "__main__":
    main()
