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
import io
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


def collect_html(path):
    """ブラウザから書き出したブックマークのHTMLから拾う。

    プロファイルの置き場所はブラウザや設定で変わり、探し当てられないことがある
    （実際に外注さんのPCで1件も読めなかった）。書き出したファイルなら
    確実に読めるので、逃げ道として用意しておく。

    形式は Netscape のブックマークファイル。フォルダは <H3> の入れ子で表される。
    """
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []          # いま何のフォルダの中にいるか
            self.pending = None      # 直前の <H3>（名前を読み終えたら stack へ）
            self.cur_a = None
            self.sellers, self.asins = {}, {}

        def handle_starttag(self, tag, attrs):
            d = dict(attrs)
            if tag == "h3":
                self.pending = ""
            elif tag == "dl":
                # <H3>フォルダ名</H3> の直後の <DL> がその中身
                # タグの間の改行や字下げが混ざるので落とす
                self.stack.append((self.pending or "").strip())
                self.pending = None
            elif tag == "a" and d.get("href"):
                self.cur_a = {"href": d["href"], "name": ""}

        def handle_endtag(self, tag):
            if tag == "dl" and self.stack:
                self.stack.pop()
            elif tag == "a" and self.cur_a:
                url = self.cur_a["href"]
                name = self.cur_a["name"].strip()
                self.cur_a = None
                if "amazon." not in url:
                    return
                folder = " / ".join([f for f in self.stack if f])
                m = bm.SELLER_RE.search(url)
                if m:
                    sid = m.group(1)
                    self.sellers.setdefault(
                        sid, (sid, bm.clean_name(name, sid), folder, url))
                    return
                m = bm.ASIN_RE.search(url)
                if m:
                    self.asins.setdefault(m.group(1), (m.group(1), name, folder, url))

        def handle_data(self, data):
            if self.pending is not None:
                self.pending += data
            elif self.cur_a is not None:
                self.cur_a["name"] += data

    with io.open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    p = P()
    p.feed(text)
    total = text.lower().count("<a href=")
    print(f"  書き出しファイル: ブックマーク {total}件 / "
          f"セラー {len(p.sellers)}件 / 商品ページ {len(p.asins)}件")
    return list(p.sellers.values()), list(p.asins.values())


def _count_bookmarks(path):
    """そのプロファイルのブックマーク総数と、Amazonのものの数を数える。

    セラー0件のときに「ファイルが読めていない」のか
    「読めたがAmazonのブックマークが無い」のかを見分けるために出す。
    """
    try:
        with io.open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None, None
    total = [0, 0]

    def walk(node):
        if node.get("type") == "folder":
            for c in node.get("children", []):
                walk(c)
            return
        url = node.get("url", "")
        if url:
            total[0] += 1
            if "amazon." in url:
                total[1] += 1

    for root in (data.get("roots") or {}).values():
        if isinstance(root, dict):
            walk(root)
    return total[0], total[1]


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
        n_all, n_amazon = _count_bookmarks(path)
        head = f"  {label}: ブックマーク {n_all}件" if n_all is not None else f"  {label}:"
        print(f"{head}（うちAmazon {n_amazon}件）/ セラー {len(s)}件 / 商品ページ {len(a)}件")
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
    ap.add_argument("--html", default="",
                    help="ブラウザから書き出したブックマークのHTMLから読む")
    ap.add_argument("--help-html", action="store_true",
                    help="書き出し方の案内だけ出す")
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

    print("=" * 56)
    print(" セラースカウト  ブックマーク取り込み")
    print("=" * 56)
    print()
    print("  このPCのブラウザのブックマークから")
    print("  Amazonの出品者ページを探して、一元管理ツールに登録します。")
    print("  Chrome・Edge・Brave・Firefox をまとめて見ます。")
    print("  ブラウザは開いたままで大丈夫です。")
    print()

    if args.help_html:
        print("=" * 56)
        print(" ブックマークを書き出して取り込む")
        print("=" * 56)
        print()
        print("  ブラウザのプロファイルが見つからないときの方法です。")
        print()
        print("  【Chromeの場合】")
        print("   1. 右上の「⋮」→ ブックマーク → ブックマークマネージャ")
        print("      （Ctrl + Shift + O でも開きます）")
        print("   2. 右上の「⋮」→「ブックマークをエクスポート」")
        print("   3. 分かりやすい場所に保存（デスクトップなど）")
        print()
        print("  【Edgeの場合】")
        print("   1. 右上の「…」→ お気に入り")
        print("   2. 「…」→「お気に入りのエクスポート」")
        print()
        print("  保存したHTMLファイルを、この")
        print("  【ブックマークHTMLから取り込む】.bat の上に")
        print("  ドラッグ＆ドロップしてください。")
        print()
        return 0

    if args.html:
        path = args.html.strip().strip('"')
        if not os.path.isfile(path):
            raise SystemExit(f"ファイルが見つかりません: {path}")
        print("書き出したファイルから読んでいます…")
        sellers, asins = collect_html(path)
        # ドラッグ＆ドロップで来たときは引数を足せないので、ここで聞く。
        # 書き出したファイルには個人のブックマークも入っているため、
        # フォルダを選べないと関係ないセラーまで登録されてしまう
        if not args.folder and sys.stdin and sys.stdin.isatty():
            counts = {}
            for _, _, folder, _ in sellers:
                counts[folder or "(フォルダなし)"] = counts.get(folder or "(フォルダなし)", 0) + 1
            if counts:
                print()
                print("出品者ページがあるフォルダ:")
                for f, n in sorted(counts.items(), key=lambda x: -x[1]):
                    print(f"  {n:>4}件  {f}")
                print()
                print("取り込むフォルダを入れてください（名前の一部でOK・カンマ区切りで複数可）")
                try:
                    args.folder = input("  空のまま Enter ですべて取り込みます: ").strip()
                except EOFError:
                    args.folder = ""
                print()
    else:
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
