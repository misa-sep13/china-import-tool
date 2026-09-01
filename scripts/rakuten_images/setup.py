"""トークンと店舗URL名を一度だけ保存する。以後は入力不要。

Compassのパスワードはここでは扱わない。ブラウザに一度ログインすれば
Cookieが残るので、保存する必要がない。
"""
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONF = os.path.join(os.path.expanduser("~"), ".rakuten_register.json")
DEFAULT_BASE = "https://china-import-tool.onrender.com/api"


def main():
    cur = {}
    if os.path.exists(CONF):
        try:
            cur = json.load(open(CONF, encoding="utf-8"))
        except Exception:
            pass

    print("=" * 54)
    print(" 楽天の画像アップロード  初回設定")
    print("=" * 54)
    print()
    print("一元管理にログインした状態で F12 → Console に貼り、")
    print("出てきた文字列を貼り付けてください。")
    print()
    print("  localStorage.getItem('auth_token')")
    print()
    token = getpass.getpass("トークン（貼り付けても表示されません）: ").strip().strip('"\'')
    token = token or cur.get("token", "")
    if not token:
        raise SystemExit("トークンが空です")

    print()
    print("店舗URL名を入れてください（楽天のURLの店舗部分）。")
    print("  例: https://www.rakuten.co.jp/misono/ なら misono")
    shop = input(f"店舗URL名 [{cur.get('shop_url') or ''}]: ").strip() or cur.get("shop_url", "")
    if not shop:
        raise SystemExit("店舗URL名が空です")

    base = cur.get("base") or DEFAULT_BASE
    print()
    print("確認しています…")
    req = urllib.request.Request(
        f"{base.rstrip('/')}/product-drafts?limit=1",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            json.load(r)
        print("  OK。サーバーに繋がりました")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SystemExit("このトークンでは通りませんでした。取り直してください")
        raise SystemExit(f"サーバーに繋がりませんでした（{e.code}）")

    # ブラウザのプロファイルはOneDrive外に置く。OneDrive配下だと
    # キャッシュ数千件が同期されて大量削除の確認が出る
    profile = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "rakuten_register_profile")

    json.dump({"token": token, "shop_url": shop, "base": base,
               "profile_dir": profile},
              open(CONF, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    try:
        os.chmod(CONF, 0o600)
    except Exception:
        pass

    print()
    print(f"保存しました: {CONF}")
    print(f"ブラウザの置き場: {profile}")
    print("以後は upload_images.py を実行するだけです。")


if __name__ == "__main__":
    main()
