"""ブラウザのブックマークからセラーを拾って、一元管理サーバーへ登録する。

配布版の scout_bookmarks.py をそのまま使い、送り先だけサーバーにしたもの。
ローカルDBを作らずに始められるので、初回はこれを実行する。

Chrome・Edge・Brave・Firefox の全プロファイルから
`https://www.amazon.co.jp/sp?seller=XXXX` の形のブックマークを拾う。

使い方:
  python push_sellers.py --token <ログイン後のトークン>
  python push_sellers.py --token <...> --dry-run     # 送らずに中身だけ見る
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import scout_bookmarks as bm   # noqa: E402  配布版のブックマーク収集をそのまま使う

DEFAULT_BASE = "https://china-import-tool.onrender.com/api"


def collect_all():
    """Chrome系の全プロファイル＋Firefoxからセラーを集める。

    ブラウザごとに登録しているセラーが違うことがあるので、全部を見る
    （実測で、Chromeだけ見ていたら8社落ちていた）。
    """
    sellers, asins = {}, {}

    # find_profiles は (ラベル, パス) のタプルを返す
    for label, path in bm.find_profiles():
        try:
            s, a = bm.collect(path)
        except Exception as e:
            print(f"  読めませんでした: {label} ({type(e).__name__})")
            continue
        if s:
            print(f"  {label}: セラー {len(s)}件")
        for sid, name, folder, url in s:
            sellers.setdefault(sid, (sid, name, folder, url))
        for asin, name, folder, url in a:
            asins.setdefault(asin, (asin, name, folder, url))

    try:
        for sid, name, folder, url in bm.collect_firefox():
            sellers.setdefault(sid, (sid, name, folder, url))
    except Exception as e:
        print(f"  Firefoxは読めませんでした（{type(e).__name__}）")

    return list(sellers.values()), list(asins.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("SCOUT_API", DEFAULT_BASE))
    ap.add_argument("--token", default=os.environ.get("APP_TOKEN", ""))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("ブックマークを探しています…")
    sellers, asins = collect_all()
    print(f"  セラーページ: {len(sellers)}件")
    print(f"  商品ページ  : {len(asins)}件"
          f"{'（URLにセラーIDが無いので今回は送りません）' if asins else ''}")

    if not sellers:
        print()
        print("見つかりませんでした。Amazonの出品者プロフィール")
        print("  https://www.amazon.co.jp/sp?seller=XXXX")
        print("をブラウザのブックマークに入れてから、もう一度実行してください。")
        return 1

    # フォルダごとの内訳（どこから拾ったか分かるように）
    by_folder = {}
    for _, _, folder, _ in sellers:
        by_folder[folder or "(フォルダなし)"] = by_folder.get(folder or "(フォルダなし)", 0) + 1
    print()
    print("フォルダ別:")
    for f, n in sorted(by_folder.items(), key=lambda x: -x[1])[:12]:
        print(f"  {n:>4}件  {f}")

    payload = [{"seller_id": sid, "name": name, "folder": folder, "url": url}
               for sid, name, folder, url in sellers]

    if args.dry_run:
        print()
        print("--dry-run なので送信しません。先頭5件:")
        for p in payload[:5]:
            print("  ", json.dumps(p, ensure_ascii=False)[:110])
        return 0

    print()
    print(f"サーバーへ送ります（{len(payload)}件）…")
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    req = urllib.request.Request(
        f"{args.base.rstrip('/')}/scout/sellers/bulk",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as res:
            r = json.load(res)
        print(f"完了: 新規{r.get('created', 0)}件 / 更新{r.get('updated', 0)}件")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code == 401:
            print("認証エラー: --token にログイン後のトークンを渡してください")
        else:
            print(f"エラー {e.code}: {body}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
