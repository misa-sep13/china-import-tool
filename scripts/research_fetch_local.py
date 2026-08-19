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
# ショップは1商品ずつ見たいわけではなく「レビューが多い順に主力商品を押さえたい」
# ので、レビュー数の多い順に数ページ分だけ取る
SHOP_MAX_PAGES = 4
# ジャンルは対象商品が桁違いに多いので、ランキング30件だけでは狭すぎる。
# レビュー数の多い順に深いページまで拾って幅を出す（10ページ＝約300件）。
# 標準の並び順だと深いページはレビュー0件の中古品等が混ざって使い物にならないため、
# レビュー数順で取る。伸びは前回比（review_delta）で見る
GENRE_MAX_PAGES = 10
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

    # 検索結果の並び順は「ランキング順位」ではないので rank は持たせない。
    # ジャンル別ランキング由来の順位と混ざると、意味の違う数字が
    # 同じ「〇位」として並んでしまう
    return [_item_dict(w.get("Item", w)) for w in data.get("Items", [])]


def _item_dict(item: dict, rank=None) -> dict:
    return {
        "item_code": item.get("itemCode", ""),
        "item_name": item.get("itemName", ""),
        "item_price": item.get("itemPrice"),
        "review_count": item.get("reviewCount", 0),
        "review_average": item.get("reviewAverage", 0),
        "shop_code": item.get("shopCode", ""),
        "shop_name": item.get("shopName", ""),
        "item_url": item.get("itemUrl", ""),
        "image_url": _image_url(item),
        "rank": rank,
    }


def fetch_shop_candidates(shop_code: str) -> list[dict]:
    """登録したショップの商品を、レビューが多い順に取得する。
    shopCodeは楽天の店舗URLに使われる識別子（例: ponopono）。
    店舗の表示名を渡すと "shopCode is not valid" で弾かれる。"""
    candidates = []
    for page in range(1, SHOP_MAX_PAGES + 1):
        params = {
            **_auth_params(),
            "shopCode": shop_code,
            "sort": "-reviewCount",
            "hits": HITS_PER_PAGE,
            "page": page,
        }
        resp = httpx.get(SEARCH_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("Items", [])
        if not items:
            break
        for wrapped in items:
            # ショップ内の並び順は「順位」ではないので rank は持たせない
            candidates.append(_item_dict(wrapped.get("Item", wrapped)))
        if len(items) < HITS_PER_PAGE:
            break
        time.sleep(REQUEST_INTERVAL_SEC)

    return candidates


def fetch_genre_candidates(genre_id: str) -> list[dict]:
    """ジャンルの商品を、ランキング上位＋レビューの多い順の一覧で取得する。

    ランキングAPIは上位30件しか返さずジャンルを見るには狭いので、
    検索API（genreId指定）で深いページまで拾って一覧の幅を出す。
    ランキングに入っている商品だけ順位を持たせ、一覧側は順位なしにする。
    """
    candidates = []
    seen = set()

    # 1) ジャンル別ランキング（楽天が出している実際の順位つき）
    params = {**_auth_params(), "genreId": genre_id, "period": "realtime", "page": 1}
    resp = httpx.get(RANKING_URL, params=params, timeout=20)
    resp.raise_for_status()
    for wrapped in resp.json().get("Items", []):
        item = wrapped.get("Item", wrapped)
        code = item.get("itemCode", "")
        if code in seen:
            continue
        seen.add(code)
        candidates.append({**_item_dict(item), "rank": item.get("rank")})

    # 2) ジャンル内の商品一覧（レビューの多い順に深いページまで）
    for page in range(1, GENRE_MAX_PAGES + 1):
        time.sleep(REQUEST_INTERVAL_SEC)
        params = {
            **_auth_params(),
            "genreId": genre_id,
            "sort": "-reviewCount",
            "hits": HITS_PER_PAGE,
            "page": page,
        }
        resp = httpx.get(SEARCH_URL, params=params, timeout=20)
        resp.raise_for_status()
        items = resp.json().get("Items", [])
        if not items:
            break
        for wrapped in items:
            item = wrapped.get("Item", wrapped)
            code = item.get("itemCode", "")
            if code in seen:
                continue
            seen.add(code)
            candidates.append(_item_dict(item))
        if len(items) < HITS_PER_PAGE:
            break

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
                elif t["type"] == "shop":
                    items = fetch_shop_candidates(t["value"])
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
