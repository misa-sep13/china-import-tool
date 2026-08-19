"""楽天リサーチツールのステップ1: API疎通確認用スクリプト。

本実装に入る前に、少量データで以下を確かめるためだけのもの。
  1. 商品検索API(IchibaItem/Search)が自宅IPから叩けるか
  2. 商品ランキングAPI(IchibaItem/Ranking)が叩けるか（エンドポイントの版が不明なため複数試す）
  3. リサーチに必要な項目（レビュー数・ショップコード等）が実際に取れるか

楽天ウェブサービスはアプリごとに「Allowed IP」の登録が必要で、CIDR非対応。
GitHub ActionsやRenderの共有IPは変動するため通らない（既存のSEOチェックが
これで頓挫し、ローカル実行に切り替えた経緯がある）。このスクリプトは
自宅PCから実行して、そのIPで通ることを確認する目的も兼ねる。

使い方:
    backend/.env に次の2行を書いて保存してから、python scripts/research_api_test.py
        RAKUTEN_APP_ID=xxxx
        RAKUTEN_ACCESS_KEY=yyyy
    （backend/.env はgitignore済みなのでGitHubには上がらない）
"""
import os
import sys
import json
import time
import httpx

try:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
except Exception:
    pass

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")


def _load_env_file() -> dict:
    """backend/.env を読む。環境変数を毎回設定させるのは手間なので、
    バックエンドと同じファイルからそのまま拾えるようにしておく。"""
    values = {}
    try:
        with open(_ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                # 値がクォートで囲まれていても拾えるようにする
                values[key.strip()] = val.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"WARNING: backend/.env の読み込みに失敗: {e}")
    return values


_env_file = _load_env_file()

# 環境変数を優先し、無ければ backend/.env の値を使う
APP_ID = os.environ.get("RAKUTEN_APP_ID") or _env_file.get("RAKUTEN_APP_ID", "")
ACCESS_KEY = os.environ.get("RAKUTEN_ACCESS_KEY") or _env_file.get("RAKUTEN_ACCESS_KEY", "")

# 既存の rakuten_seo.py で実際に動いている検索APIのURL（版まで含めてこの形）
SEARCH_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"

# ランキングAPIはゲートウェイのプレフィックスが検索APIと異なる。
# 検索は /ichibams/ だがランキングは /ichibaranking/ で、版も 20220601 のまま。
# ここを /ichibams/ と揃えて書くと 404 になるので注意（実際に嵌まった）。
RANKING_URL = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"

# 疎通確認なので少量でよい（指示書どおりジャンル1つ・キーワード1つ）
TEST_KEYWORD = os.environ.get("TEST_KEYWORD", "おむつ替えシート")
TEST_GENRE_ID = os.environ.get("TEST_GENRE_ID", "100939")  # 100939 = ベビー・キッズ・マタニティ


def _auth_params() -> dict:
    """検索APIは applicationId に加えて accessKey も要求する（現行版）。"""
    p = {"applicationId": APP_ID}
    if ACCESS_KEY:
        p["accessKey"] = ACCESS_KEY
    return p


def test_search() -> bool:
    """商品検索API。リサーチで使う項目が実際に取れるかまで確認する。"""
    print("=" * 60)
    print(f"[1] 商品検索API  keyword={TEST_KEYWORD!r}")
    print("=" * 60)

    params = {
        **_auth_params(),
        "keyword": TEST_KEYWORD,
        "sort": "standard",
        "hits": 5,          # 疎通確認なので5件で十分
        "page": 1,
    }
    try:
        resp = httpx.get(SEARCH_URL, params=params, timeout=20)
    except Exception as e:
        print(f"  NG: リクエスト失敗: {e}")
        return False

    if not resp.is_success:
        print(f"  NG: HTTP {resp.status_code}")
        print(f"  応答: {resp.text[:500]}")
        _hint_for_error(resp)
        return False

    data = resp.json()
    total = data.get("count", 0)
    items = data.get("Items", [])
    print(f"  OK: HTTP 200 / 全{total}件ヒット / このページ{len(items)}件")

    # リサーチに必要な項目が揃っているかを1件目で確認する
    if items:
        item = items[0].get("Item", items[0])
        need = {
            "itemCode": item.get("itemCode"),
            "itemName": (item.get("itemName") or "")[:40],
            "itemPrice": item.get("itemPrice"),
            "reviewCount": item.get("reviewCount"),
            "reviewAverage": item.get("reviewAverage"),
            "shopCode": item.get("shopCode"),
            "shopName": item.get("shopName"),
            "itemUrl": (item.get("itemUrl") or "")[:60],
        }
        print("  --- リサーチに使う項目（1件目）---")
        for k, v in need.items():
            mark = "OK " if v not in (None, "") else "NG "
            print(f"   {mark}{k}: {v}")
        missing = [k for k, v in need.items() if v in (None, "")]
        if missing:
            print(f"  WARNING: 取れなかった項目: {missing}")
    return True


def test_ranking() -> bool:
    """商品ランキングAPI。急上昇の検出に使う順位データが取れるか確認する。"""
    print()
    print("=" * 60)
    print(f"[2] 商品ランキングAPI  genreId={TEST_GENRE_ID}")
    print("=" * 60)

    # genreId は age/sex と併用できない（API仕様）。ジャンル別ランキングだけ見る
    params = {**_auth_params(), "genreId": TEST_GENRE_ID}
    try:
        resp = httpx.get(RANKING_URL, params=params, timeout=20)
    except Exception as e:
        print(f"  NG: リクエスト失敗: {e}")
        return False

    if not resp.is_success:
        print(f"  NG: HTTP {resp.status_code}")
        print(f"  応答: {resp.text[:500]}")
        _hint_for_error(resp)
        return False

    data = resp.json()
    items = data.get("Items", [])
    print(f"  OK: HTTP 200 / {len(items)}件")
    for wrapped in items[:3]:
        item = wrapped.get("Item", wrapped)
        print(f"   {item.get('rank')}位 {(item.get('itemName') or '')[:40]}")
        print(f"        reviewCount={item.get('reviewCount')} "
              f"shopCode={item.get('shopCode')} price={item.get('itemPrice')}")
    return True


def _hint_for_error(resp: httpx.Response) -> None:
    """よくある失敗の原因を、応答の中身から推測して出す。"""
    body = resp.text.lower()
    if resp.status_code == 400 and "wrong parameter" in body:
        print("  ヒント: applicationId か accessKey が誤っている可能性があります")
    elif resp.status_code in (403, 429):
        print("  ヒント: このIPが楽天の Allowed IP に未登録の可能性があります。")
        print("         楽天Developersの管理画面で、いまの自宅IPを登録してください。")


def main():
    if not APP_ID:
        print("RAKUTEN_APP_ID が見つかりません。次のファイルをメモ帳で開いて")
        print("（無ければ新規作成して）2行書いて保存してください:")
        print(f"  {os.path.abspath(_ENV_PATH)}")
        print("    RAKUTEN_APP_ID=（楽天Developersのアプリケーション ID）")
        print("    RAKUTEN_ACCESS_KEY=（同じ画面のアクセスキー）")
        sys.exit(1)
    if not ACCESS_KEY:
        print("WARNING: RAKUTEN_ACCESS_KEY が未設定です。現行APIでは必須の可能性が高いです。")

    # いまの自宅IP。楽天の Allowed IP に登録する値なので控えておく
    try:
        my_ip = httpx.get("https://api.ipify.org", timeout=10).text.strip()
        print(f"このPCのグローバルIP: {my_ip}")
        print("（楽天Developersの Allowed IP にこの値が登録されている必要があります）")
        print()
    except Exception:
        pass

    ok_search = test_search()
    time.sleep(1)
    ok_ranking = test_ranking()

    print()
    print("=" * 60)
    print(f"結果  商品検索API: {'OK' if ok_search else 'NG'} / "
          f"ランキングAPI: {'OK' if ok_ranking else 'NG'}")
    print("=" * 60)
    if ok_search and ok_ranking:
        print("ステップ1クリア。差分検出・セラー数チェックの実装に進めます。")
    else:
        print("失敗した方の応答内容を見て、原因（キー誤り/IP未登録/版違い）を切り分けます。")


if __name__ == "__main__":
    main()
