"""ブラウザのブックマークからセラーを拾って、一元管理サーバーへ登録する。

配布版の scout_bookmarks.py をそのまま使い、送り先だけサーバーにしたもの。
ローカルDBを作らずに始められるので、初回はこれを実行する。

Chrome・Edge・Brave・Firefox の全プロファイルから
`https://www.amazon.co.jp/sp?seller=XXXX` の形のブックマークを拾う。

使い方:
  python push_sellers.py                            # 初回設定済みなら引数不要
  python push_sellers.py --dry-run                   # 送らずに中身だけ見る
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
    profiles = list(bm.find_profiles())
    if not profiles:
        print("  ブラウザのブックマークが見つかりませんでした")
    for label, path in profiles:
        try:
            s, a = bm.collect(path)
        except Exception as e:
            print(f"  読めませんでした: {label} ({type(e).__name__})")
            continue
        # 0件でも出す。出さないと「読めていない」のか
        # 「読めたがセラーが無い」のか分からない（実際に切り分けに困った）
        print(f"  {label}: セラー {len(s)}件 / 商品ページ {len(a)}件")
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
    ap.add_argument("--base", default=os.environ.get("SCOUT_API", ""))
    ap.add_argument("--token", default=os.environ.get("APP_TOKEN", ""))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--folder", default="",
                    help="このフォルダの中だけ取り込む（部分一致・カンマ区切りで複数可）")
    ap.add_argument("--list-folders", action="store_true",
                    help="ブックマークのフォルダ一覧だけ出す")
    args = ap.parse_args()

    # setup.py で保存した設定を使う。sync_server.py と同じ置き場所・同じ優先順。
    # これが無いと、初回設定を済ませてもここだけトークンを手で貼ることになる。
    conf = {}
    conf_path = os.path.join(os.path.expanduser("~"), ".scout_config.json")
    if os.path.exists(conf_path):
        try:
            with open(conf_path, encoding="utf-8") as f:
                conf = json.load(f)
        except Exception:
            pass
    base = (args.base or conf.get("base") or DEFAULT_BASE).rstrip("/")
    args.token = args.token or conf.get("token", "")

    # 送らない --dry-run はトークン無しでも動かせる（中身の確認用）
    if not args.token and not args.dry_run:
        raise SystemExit(
            "トークンがありません。先に【初回設定】を実行してください"
            "（コマンドなら python setup.py）")

    print("ブックマークを探しています…")
    sellers, asins = collect_all()

    if args.list_folders:
        counts = {}
        for _, _, folder, _ in sellers:
            counts[folder or "(フォルダなし)"] = counts.get(folder or "(フォルダなし)", 0) + 1
        print()
        print("セラーのブックマークがあるフォルダ:")
        for f, n in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {n:>4}件  {f}")
        return 0

    # フォルダで絞る。フォルダ名は「ブックマーク バー / Ama / Amazonセラー」の
    # ような形なので、指定はその一部でよい（全部書かせるのは現実的でない）
    if not sellers:
        print()
        print("このPCのブックマークに、出品者ページが1件もありませんでした。")
        print()
        print("拾えるのは、Amazonの「出品者プロフィール」のページです。")
        print("  https://www.amazon.co.jp/sp?seller=XXXXXXXXXX")
        print("  https://www.amazon.co.jp/s?me=XXXXXXXXXX")
        print()
        print("商品ページ（/dp/...）はセラーIDが分からないので拾えません。")
        print("商品ページの「販売元」のリンクを開いてから、そのページを")
        print("ブックマークしてください。")
        print()
        print("上に出ているプロファイルが、ふだんお使いのブラウザと")
        print("合っているかもご確認ください。")
        return 1

    wanted = [w.strip().lower() for w in (args.folder or "").split(",") if w.strip()]
    if wanted:
        before_rows = list(sellers)
        before = len(sellers)
        sellers = [x for x in sellers
                   if any(w in (x[2] or "").lower() for w in wanted)]
        print(f"  フォルダ「{args.folder}」で絞り込み: {before}件 → {len(sellers)}件")
        if not sellers:
            print()
            print("そのフォルダには出品者ページのブックマークがありませんでした。")
            print("フォルダ名は一部でかまいません（例: Amazonセラー）。")
            print()
            print("出品者ページがあるフォルダは次のとおりです:")
            counts = {}
            for _, _, folder, _ in before_rows:
                counts[folder or "(フォルダなし)"] = counts.get(folder or "(フォルダなし)", 0) + 1
            for f, n in sorted(counts.items(), key=lambda x: -x[1]):
                print(f"  {n:>4}件  {f}")
            return 1

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
        f"{base}/scout/sellers/bulk",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as res:
            r = json.load(res)
        print(f"完了: 新規{r.get('created', 0)}件 / 更新{r.get('updated', 0)}件")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code == 401:
            print("認証エラー: トークンが古いか間違っています。【初回設定】をやり直してください")
        else:
            print(f"エラー {e.code}: {body}")
        return 1
    except urllib.error.URLError as e:
        # ネットが切れている・サーバーが起きていない場合。
        # そのままだとPythonのトレースバックが出て、原因が分からなくなる
        print(f"サーバーに繋がりませんでした（{e.reason}）")
        print("ネット接続を確認して、もう一度実行してください")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
