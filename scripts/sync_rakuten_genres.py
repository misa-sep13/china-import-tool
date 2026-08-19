"""楽天のジャンル階層を取り込むスクリプト（ローカルPC実行・基本は一度だけ）。

ジャンルIDを手で調べるのは現実的でないため、画面のジャンル選択に使う一覧を
DBへ入れておく。ジャンル構成はそう頻繁には変わらないので、都度ではなく
たまに実行すればよい（新しいジャンルが増えたと感じたら再実行する）。

RenderからはIP制限で楽天APIを呼べないため、取得はローカルで行い結果だけ送る。

使い方:
    python scripts/sync_rakuten_genres.py          # 3階層まで（既定）
    python scripts/sync_rakuten_genres.py --depth 2
"""
import os
import sys
import time
import argparse
import httpx

try:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
except Exception:
    pass

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

# ジャンルAPIは検索・ランキングとまたゲートウェイが違う（ichibagt）
GENRE_URL = "https://openapi.rakuten.co.jp/ichibagt/api/IchibaGenre/Search/20260701"
REQUEST_INTERVAL_SEC = 1.1


def fetch_children(genre_id) -> list[dict]:
    params = {"applicationId": APP_ID, "accessKey": ACCESS_KEY, "genreId": genre_id}
    resp = httpx.get(GENRE_URL, params=params, timeout=20)
    if resp.status_code == 403:
        print("403 CLIENT_IP_NOT_ALLOWED: このPCのIPが楽天のAllowed IPに未登録です。")
        print("楽天Developersの管理画面で現在のグローバルIPを登録してください。")
        sys.exit(1)
    resp.raise_for_status()
    return resp.json().get("children", [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth", type=int, default=3,
                        help="取り込む階層の深さ（既定3）。深くするほど時間がかかる")
    args = parser.parse_args()

    if not APP_ID or not ACCESS_KEY:
        print(f"RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY が見つかりません: {os.path.abspath(_ENV_PATH)}")
        sys.exit(1)

    collected = []
    # (genre_id, 表示用の道筋) を辿る。ルートは0
    frontier = [(0, "")]

    for depth in range(1, args.depth + 1):
        next_frontier = []
        print(f"--- 階層{depth}: {len(frontier)}件のジャンルを展開 ---")
        for i, (parent_id, parent_path) in enumerate(frontier, 1):
            try:
                children = fetch_children(parent_id)
            except Exception as e:
                print(f"  WARNING: genreId={parent_id} の取得に失敗: {e}")
                continue

            for c in children:
                g = c.get("child", c)
                gid = g.get("genreId")
                name = g.get("nameJa") or g.get("genreName") or ""
                if not gid or not name:
                    continue
                path = f"{parent_path} > {name}" if parent_path else name
                collected.append({
                    "genre_id": gid,
                    "name": name,
                    "level": depth,
                    "parent_id": parent_id or None,
                    "path": path,
                })
                next_frontier.append((gid, path))

            if i % 20 == 0:
                print(f"  {i}/{len(frontier)} 件処理済み（累計 {len(collected)} ジャンル）")
            time.sleep(REQUEST_INTERVAL_SEC)

        print(f"--- 階層{depth}完了: 累計 {len(collected)} ジャンル ---")
        frontier = next_frontier
        if not frontier:
            break

    print(f"\n合計 {len(collected)} ジャンルを取得しました。送信します...")
    with httpx.Client(timeout=180, headers=AUTH_HEADERS) as api:
        res = api.post(f"{BACKEND}/api/research/genres/bulk", json={"genres": collected})
        if res.status_code == 401:
            print(f"401 Unauthorized: AUTH_SERVICE_TOKEN を {os.path.abspath(_ENV_PATH)} に設定してください")
            sys.exit(1)
        res.raise_for_status()
        print("完了:", res.json())


if __name__ == "__main__":
    main()
