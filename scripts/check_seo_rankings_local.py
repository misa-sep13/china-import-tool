"""SEO順位をローカルPCから楽天検索スクレイピングでチェックし、Renderへ送信するスクリプト。

GitHub ActionsやRenderのデータセンターIPからは楽天にブロックされるため、
このスクリプトはご自宅PCで実行する（Windowsタスクスケジューラでの自動実行を想定）。
実行にはインターネット接続が必要。PCが起動していない日はスキップされる。
"""
import httpx
from bs4 import BeautifulSoup
import re
import sys
import time
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

# 進捗をその場で出す。既定のバッファリングだと、タスクスケジューラやログへ
# リダイレクトしたときに出力が溜まり、動いているのか止まったのか分からなくなる
try:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
except Exception:
    pass

BACKEND = os.environ.get("BACKEND_URL", "https://china-import-tool.onrender.com")
SHOP_ID = "411150"
SEARCH_URL = "https://search.rakuten.co.jp/search/mall/{keyword}/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
# 2ページ（90位）まで見れば実用上十分。5ページ見ていた頃は208件で約50分かかり、
# PCを落とすと一括送信まで到達せず1件も保存されなかった
MAX_PAGES = 2
# 自店が見つかったらそれ以降のページは見ない（上位の商品ほど速く終わる）
STOP_WHEN_FOUND = True
# 送信の区切り。全件終わるまで貯めると、途中で落ちたとき全部無駄になる
SEND_EVERY = 20
# 楽天の応答が1ページ5〜10秒かかる（解析は0.2秒）。待ち時間が支配的なので
# 並列にすると素直に短くなる。実測: 1→49分 / 3→19分 / 5→13分。
# 5でもブロックはされなかったが、毎晩208件を投げるので安全側の3にしている
WORKERS = int(os.environ.get("SEO_WORKERS", "3"))
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
            m = re.search(r"([\d,]{2,})\s*件", resp.text)
            if m:
                total_items = int(m.group(1).replace(",", ""))

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

        # 自店が見つかったら、残りのページを見る必要はない
        if STOP_WHEN_FOUND and my_ranks:
            break
        if page_size < 45:
            break
        time.sleep(0.8)

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
    results = []      # まだ送っていない分
    sent = 0
    errors = 0

    def flush():
        """溜まった分を送る。全件終わるまで待つと、途中で落ちたとき全部消える"""
        nonlocal results, sent
        if not results:
            return
        try:
            with httpx.Client(timeout=120) as api:
                res = api.post(
                    f"{BACKEND}/api/seo/rankings/bulk",
                    json={"checked_at": checked_at, "results": results},
                )
                res.raise_for_status()
                n = res.json().get("imported", 0)
            sent += n
            print(f"  --- 送信: {n}件（累計 {sent}件）")
            results = []
        except Exception as e:
            # 送信に失敗しても手元には残す。次の区切りでまとめて再送を試みる
            print(f"  WARNING: 送信失敗（次回にまとめて再送）: {e}")

    lock = threading.Lock()
    done = 0

    def work(kw):
        """1キーワード分を取得する。スレッドから呼ばれるので、
        httpxのクライアントはスレッドごとに作る"""
        nonlocal done, errors
        rows = []
        label = ""
        try:
            with httpx.Client() as c:
                data = scrape_ranking(c, kw["keyword"])
        except Exception as e:
            with lock:
                errors += 1
            rows.append({
                "seo_keyword_id": kw["id"], "keyword": kw["keyword"],
                "product_sku": kw.get("product_sku"),
                "rank": None, "page": None, "total_items": None, "card_type": None,
            })
            label = f"ERROR: {e}"
        else:
            if data["my_ranks"]:
                for r in data["my_ranks"]:
                    rows.append({
                        "seo_keyword_id": kw["id"], "keyword": kw["keyword"],
                        "product_sku": kw.get("product_sku"),
                        "rank": r["rank"], "page": r["page"],
                        "total_items": data["total_items"], "card_type": r["card_type"],
                    })
                label = f"{min(r['rank'] for r in data['my_ranks'])}位"
            else:
                rows.append({
                    "seo_keyword_id": kw["id"], "keyword": kw["keyword"],
                    "product_sku": kw.get("product_sku"),
                    "rank": None, "page": None,
                    "total_items": data["total_items"], "card_type": None,
                })
                label = "圏外"

        with lock:
            results.extend(rows)
            done += 1
            print(f"[{done}/{len(keywords)}] {kw['keyword']} "
                  f"(SKU: {kw.get('product_sku', '-')}) -> {label}")
            # 区切りごとに送る。PCが落ちてもここまでは画面に反映される
            if done % SEND_EVERY == 0:
                flush()

    # 楽天の応答待ちが支配的なので並列にする。取得の合間の待機は
    # scrape_ranking 内の sleep が担う
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, keywords))

    flush()   # 端数を送る
    print(f"\n完了: 送信 {sent}件 / キーワード {len(keywords)}件, エラー: {errors}件")
    if results:
        print(f"WARNING: 送信できなかった分が {len(results)}件あります")


if __name__ == "__main__":
    main()
