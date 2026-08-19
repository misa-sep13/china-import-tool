"""楽天リサーチツールの週次バッチ（ローカルPC実行）。

登録済みのジャンル/キーワード（research_targets）を読み、楽天ウェブサービスの
商品検索API・ランキングAPIで候補商品を取得し、Renderのバックエンドへ送信する。

楽天のAllowed IP設定はCIDR非対応で、Render/GitHub Actionsの共有IPは
デプロイのたびに変わるため通らない（既存のSEO順位チェックと同じ理由）。
このスクリプトは自宅PC等、Allowed IPに登録済みの回線から実行する前提。
別のPCへ引き継ぐ場合は、そのPCのグローバルIPをAllowed IPに追加してから
このリポジトリを配置し、タスクスケジューラに登録する。

使い方:
    backend/.env に RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY を設定した状態で
    python scripts/research_fetch_local.py
"""
import os
import sys
import time
import httpx
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
except Exception:
    pass

JST = timezone(timedelta(hours=9))

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")


def _load_env_file() -> dict:
    values = {}
    try:
        with open(_ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return values


_env_file = _load_env_file()

APP_ID = os.environ.get("RAKUTEN_APP_ID") or _env_file.get("RAKUTEN_APP_ID", "")
ACCESS_KEY = os.environ.get("RAKUTEN_ACCESS_KEY") or _env_file.get("RAKUTEN_ACCESS_KEY", "")

BACKEND = os.environ.get("BACKEND_URL") or _env_file.get("BACKEND_URL") or "https://china-import-tool.onrender.com"
_SERVICE_TOKEN = os.environ.get("AUTH_SERVICE_TOKEN") or _env_file.get("AUTH_SERVICE_TOKEN") or ""
AUTH_HEADERS = {"Authorization": f"Bearer {_SERVICE_TOKEN}"} if _SERVICE_TOKEN else {}

SEARCH_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
RANKING_URL = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"
HITS_PER_PAGE = 30
# 楽天APIはおおむね1秒1リクエストまで。それより速く叩くと弾かれることがある
REQUEST_INTERVAL_SEC = 1.1


def _auth_params() -> dict:
    return {"applicationId": APP_ID, "accessKey": ACCESS_KEY}


def _image_url(item: dict) -> str:
    urls = item.get("mediumImageUrls") or item.get("smallImageUrls") or []
    if urls:
        return urls[0].get("imageUrl", "")
    return ""


def fetch_keyword_candidates(keyword: str) -> list[dict]:
    params = {**_auth_params(), "keyword": keyword, "sort": "standard", "hits": HITS_PER_PAGE, "page": 1}
    resp = httpx.get(SEARCH_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    candidates = []
    for i, wrapped in enumerate(data.get("Items", [])):
        item = wrapped.get("Item", wrapped)
        candidates.append({
            "item_code": item.get("itemCode", ""),
            "item_name": item.get("itemName", ""),
            "item_price": item.get("itemPrice"),
            "review_count": item.get("reviewCount", 0),
            "review_average": item.get("reviewAverage", 0),
            "shop_code": item.get("shopCode", ""),
            "shop_name": item.get("shopName", ""),
            "item_url": item.get("itemUrl", ""),
            "image_url": _image_url(item),
            "rank": i + 1,
        })
    return candidates


def fetch_genre_candidates(genre_id: str) -> list[dict]:
    params = {**_auth_params(), "genreId": genre_id, "period": "realtime", "page": 1}
    resp = httpx.get(RANKING_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    candidates = []
    for wrapped in data.get("Items", []):
        item = wrapped.get("Item", wrapped)
        candidates.append({
            "item_code": item.get("itemCode", ""),
            "item_name": item.get("itemName", ""),
            "item_price": item.get("itemPrice"),
            "review_count": item.get("reviewCount", 0),
            "review_average": item.get("reviewAverage", 0),
            "shop_code": item.get("shopCode", ""),
            "shop_name": item.get("shopName", ""),
            "item_url": item.get("itemUrl", ""),
            "image_url": _image_url(item),
            "rank": item.get("rank"),
        })
    return candidates


def main():
    if not APP_ID or not ACCESS_KEY:
        print(f"RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY が見つかりません: {os.path.abspath(_ENV_PATH)}")
        sys.exit(1)

    with httpx.Client(timeout=30, headers=AUTH_HEADERS) as api:
        res = api.get(f"{BACKEND}/api/research/targets?active_only=true")
        if res.status_code == 401:
            print(f"401 Unauthorized: {BACKEND} へのアクセスにログインが必要です。")
            print(f"AUTH_SERVICE_TOKEN が {os.path.abspath(_ENV_PATH)} に設定されているか確認してください"
                  "（Renderの環境変数と同じ値。既存のSEOチェック等と共通）。")
            sys.exit(1)
        res.raise_for_status()
        targets = res.json().get("targets", [])

    print(f"リサーチ対象: {len(targets)}件")
    if not targets:
        print("research_targets に有効な対象がありません（サイト側で登録してください）")
        return

    fetched_at = datetime.now(JST).isoformat()
    ok, ng = 0, 0

    with httpx.Client(timeout=60, headers=AUTH_HEADERS) as api:
        for t in targets:
            label = t.get("label") or t.get("value")
            try:
                if t["type"] == "genre":
                    items = fetch_genre_candidates(t["value"])
                else:
                    items = fetch_keyword_candidates(t["value"])

                res = api.post(f"{BACKEND}/api/research/candidates/bulk", json={
                    "research_target_id": t["id"],
                    "fetched_at": fetched_at,
                    "items": items,
                })
                res.raise_for_status()
                print(f"  OK [{t['type']}] {label}: {len(items)}件")
                ok += 1
            except Exception as e:
                print(f"  NG [{t['type']}] {label}: {e}")
                ng += 1

            time.sleep(REQUEST_INTERVAL_SEC)

    print(f"\n完了: 成功 {ok}件 / 失敗 {ng}件")


if __name__ == "__main__":
    main()
