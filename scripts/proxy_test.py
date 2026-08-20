"""固定IPプロキシ（ConoHa VPS上のsquid）経由で楽天APIを叩けるか確認するスクリプト。

自宅のIPは頻繁に変わり、そのたびに楽天のAllowed IP登録が必要で運用が破綻していた
（実際に1日で3回変わった）。VPSの固定IPを経由させることで、登録するIPを1つに固定する。

確認する内容:
  1. プロキシ経由で外に出たときのIPが、VPSのIPになっているか
  2. そのIPで楽天APIが通るか（Allowed IPに登録済みか）

使い方:
    backend/.env に次の行を足してから実行する
        RAKUTEN_PROXY_URL=http://ユーザー名:パスワード@VPSのIP:3128
    python scripts/proxy_test.py
"""
import os
import sys
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


_env = _load_env_file()
APP_ID = os.environ.get("RAKUTEN_APP_ID") or _env.get("RAKUTEN_APP_ID", "")
ACCESS_KEY = os.environ.get("RAKUTEN_ACCESS_KEY") or _env.get("RAKUTEN_ACCESS_KEY", "")
PROXY_URL = os.environ.get("RAKUTEN_PROXY_URL") or _env.get("RAKUTEN_PROXY_URL", "")

SEARCH_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"


def _masked(url: str) -> str:
    """ログにパスワードを出さないための伏せ字。"""
    if "@" not in url:
        return url
    creds, _, host = url.rpartition("@")
    scheme, _, user_pass = creds.partition("://")
    user = user_pass.split(":")[0]
    return f"{scheme}://{user}:****@{host}"


def main():
    if not PROXY_URL:
        print("RAKUTEN_PROXY_URL が設定されていません。")
        print(f"  {os.path.abspath(_ENV_PATH)} に次の行を追加してください:")
        print("    RAKUTEN_PROXY_URL=http://ユーザー名:パスワード@VPSのIP:3128")
        sys.exit(1)

    print(f"プロキシ: {_masked(PROXY_URL)}")
    print()

    # --- 1) プロキシを通さない場合のIP（＝いまの自宅IP）---
    try:
        direct_ip = httpx.get("https://api.ipify.org", timeout=15).text.strip()
        print(f"[1] プロキシなしのIP（自宅）: {direct_ip}")
    except Exception as e:
        print(f"[1] プロキシなしのIP取得に失敗: {e}")
        direct_ip = None

    # --- 2) プロキシ経由で出たときのIP（＝VPSの固定IP）---
    try:
        with httpx.Client(proxy=PROXY_URL, timeout=30) as c:
            proxy_ip = c.get("https://api.ipify.org").text.strip()
        print(f"[2] プロキシ経由のIP（VPS）  : {proxy_ip}")
    except Exception as e:
        print(f"[2] NG: プロキシ経由で外に出られません: {e}")
        print("    VPSでsquidが起動しているか、ポート3128が開いているか、")
        print("    ユーザー名・パスワードが合っているかを確認してください。")
        sys.exit(1)

    if direct_ip and direct_ip == proxy_ip:
        print("    WARNING: 自宅IPと同じです。プロキシを経由できていない可能性があります。")
    print()

    # --- 3) プロキシ経由で楽天APIが通るか ---
    if not APP_ID or not ACCESS_KEY:
        print("[3] RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY が未設定のため、楽天APIの確認をとばします")
        return

    params = {
        "applicationId": APP_ID,
        "accessKey": ACCESS_KEY,
        "keyword": "おむつ替えシート",
        "hits": 3,
    }
    try:
        with httpx.Client(proxy=PROXY_URL, timeout=30) as c:
            resp = c.get(SEARCH_URL, params=params)
    except Exception as e:
        print(f"[3] NG: 楽天APIへのリクエストに失敗: {e}")
        sys.exit(1)

    if resp.status_code == 200:
        data = resp.json()
        print(f"[3] OK: 楽天API 200 / 全{data.get('count')}件ヒット")
        print()
        print("=" * 55)
        print("成功です。これ以降、登録するAllowed IPはこの1つだけで済みます:")
        print(f"  {proxy_ip}")
        print("=" * 55)
    elif resp.status_code == 403 and "CLIENT_IP_NOT_ALLOWED" in resp.text:
        print("[3] NG: 403 CLIENT_IP_NOT_ALLOWED")
        print(f"    VPSのIP {proxy_ip} を楽天Developersの Allowed IP に登録してください。")
        sys.exit(1)
    else:
        print(f"[3] NG: HTTP {resp.status_code}")
        print(f"    {resp.text[:300]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
