"""競合リサーチシートの取り込みサーバー。

シートの⚡ボタン（レビュー・キーワードの自動取得）は、このサーバーが
動いているPCにだけ出る。tool4seller にログインしたブラウザを裏で操作して
取ってくるので、ログインを預けられないサーバー（Render）には置けない。

  シート → http://127.0.0.1:8765/t4s/fetch?asins=...&kinds=reviews,keywords
        → ここが Playwright で tool4seller を操作
        → 取れた表を返す

ログインは専用のプロファイル（このフォルダの browser/）に残す。
普段使いのChromeとは別なので、そちらのログインには触らない。

  【取り込みサーバーを起動】.bat   … これを実行して常駐させる
  【tool4seller ログイン】.bat      … 初回とログインが切れたときだけ
"""
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
PROFILE = HERE / "browser"          # ログインを残す場所
VISITED = HERE / "visited_urls.txt"  # ログイン時に開いた画面のURL控え
# 取得先の画面URL。tool4sellerの画面構成はこちらで確かめようがないので、
# 決め打ちにせず、ログインのときに控えたURLをここに書いて使う。
# {asin} のところが商品ごとに差し替わる
CONF = HERE / "urls.json"
PORT = 8765

# 紹介ページ(www)ではなく、ログインして使う本体はこちら。
# www 側に /login は無く404になる
T4S = "https://data.tool4seller.com"
T4S_LOGIN = "https://data.tool4seller.com/landing?userHostRegion=com"

# ブラウザ操作は同時に走らせない。1つのプロファイルを共有しているので、
# 並行して動かすと互いのページを奪い合う
_lock = threading.Lock()


# Windowsのコンソールは既定がcp932で、絵文字を出すと落ちる。
# 出せない字は「?」に置き換えて、ログのせいで止まらないようにする
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


# ---------- tool4seller の操作 ----------

def _new_page(pw):
    """ログイン済みのプロファイルでブラウザを開く。"""
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE),
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
        locale="ja-JP",
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def _logged_in(page) -> bool:
    """ログインが生きているか。切れているとログイン画面へ飛ばされる。"""
    url = page.url or ""
    return "login" not in url.lower() and "signin" not in url.lower()


def _url_for(kind: str, asin: str) -> str:
    """取得先。urls.json に書いてあるものを使う。

    無ければ空を返し、呼び出し側で「設定がまだ」と伝える。
    当てずっぽうのURLを叩いても404になるだけなので、黙って進めない。
    """
    try:
        conf = json.loads(CONF.read_text(encoding="utf-8"))
    except Exception:
        return ""
    tpl = str(conf.get(kind) or "")
    return tpl.replace("{asin}", asin) if tpl else ""


def fetch_one(page, asin: str, kinds: set) -> dict:
    """1商品ぶん取る。取れなかった種類は入れずに返す。"""
    out = {}

    if "reviews" in kinds:
        url = _url_for("reviews", asin)
        if not url:
            return {"error": "noconf"}
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            if not _logged_in(page):
                return {"error": "login"}
            rows = _read_table(page)
            if rows:
                out["reviews"] = {"head": rows[0], "rows": rows[1:]}
        except Exception as e:
            _log("レビュー取得に失敗", asin, type(e).__name__)

    if "keywords" in kinds:
        url = _url_for("keywords", asin)
        if not url:
            return {"error": "noconf"}
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            if not _logged_in(page):
                return {"error": "login"}
            rows = _read_table(page)
            if rows:
                # シート側は「タブ区切りの生テキスト」を待っている
                out["keywords"] = {
                    "text": "\n".join("\t".join(r) for r in rows)}
        except Exception as e:
            _log("キーワード取得に失敗", asin, type(e).__name__)

    return out


def _read_table(page) -> list:
    """画面の表を、行 × 列の配列にして返す。

    tool4seller の画面構成は変わることがある。見出しと中身が拾えなければ
    空を返し、呼び出し側で「取れなかった」として扱う。
    """
    try:
        return page.evaluate("""() => {
          const tb = document.querySelector('table');
          if (!tb) return [];
          const out = [];
          for (const tr of tb.querySelectorAll('tr')) {
            const cells = [...tr.querySelectorAll('th,td')]
              .map(td => (td.innerText || '').trim());
            if (cells.some(c => c)) out.push(cells);
          }
          return out;
        }""") or []
    except Exception:
        return []


def t4s_fetch(asins: list, kinds: set) -> dict:
    """複数ASINをまとめて取る。ブラウザは1回だけ開く。"""
    from playwright.sync_api import sync_playwright

    got = {}
    with _lock, sync_playwright() as pw:
        ctx, page = _new_page(pw)
        try:
            for asin in asins:
                _log("取得中", asin, ",".join(sorted(kinds)))
                r = fetch_one(page, asin, kinds)
                if r.get("error") == "noconf":
                    return {"ok": False,
                            "error": "取得先の画面がまだ設定されていません。"
                                     "urls.json にレビューとキーワードの"
                                     "画面URLを入れてください"}
                if r.get("error") == "login":
                    return {"ok": False,
                            "error": "ログインが切れています。"
                                     "【tool4seller ログイン】.bat を実行してください"}
                got[asin] = r
        finally:
            ctx.close()
    return {"ok": True, "items": got}


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass        # 既定のアクセスログは煩いので出さない

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # シートはGitHub Pagesから開くので、ここを開けないと繋がらない
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path == "/ping":
            # t4s:true が⚡ボタンを出す目印。
            # サジェストと画像文字は一元管理のサーバーが持っているので、
            # ここでは名乗らない（そちらへ回してもらう）
            return self._send({"ok": True, "t4s": True})

        if u.path == "/t4s/fetch":
            asins = [a.strip().upper()
                     for a in (q.get("asins", [""])[0]).split(",") if a.strip()]
            kinds = {k.strip() for k in
                     (q.get("kinds", ["reviews,keywords"])[0]).split(",") if k.strip()}
            asins = [a for a in asins if re.fullmatch(r"[A-Z0-9]{10}", a)]
            if not asins:
                return self._send({"ok": False, "error": "ASINがありません"})
            try:
                return self._send(t4s_fetch(asins, kinds))
            except Exception as e:
                _log("失敗", type(e).__name__, e)
                return self._send({"ok": False,
                                   "error": f"取り込みに失敗しました（{type(e).__name__}）"})

        self._send({"ok": False, "error": "not found"}, 404)


def main():
    if "--login" in sys.argv:
        return login()
    PROFILE.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    _log(f"取り込みサーバーを開始しました  http://127.0.0.1:{PORT}")
    _log("シートを開くと、レビューとキーワードに自動取得ボタンが出ます")
    _log("止めるときはこの窓を閉じてください")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def login():
    """ログイン用にブラウザを開く。

    ログインできたら、レビューとキーワードの画面を開いてURLを控える。
    tool4seller の画面構成はこちらで確かめようがないので、
    実際に開いたURLをそのまま設定として残す。
    """
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("tool4seller のログイン画面を開きます。")
    print()
    print("  1. ログインする")
    print("  2. レビューを見る画面と、キーワードを見る画面を開く")
    print("  3. ブラウザを閉じる（この窓ではなくブラウザのほう）")
    print()
    print("開いた画面のURLを控えて、⚡の取得先として使います。")
    print("（レビューも取るなら、同じ窓で amazon.co.jp にもログイン）")
    print("=" * 60)

    seen = []
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE), headless=False, locale="ja-JP")

        def note(page):
            try:
                u = page.url or ""
            except Exception:
                return
            if u.startswith("http") and u not in seen:
                seen.append(u)

        ctx.on("page", lambda pg: pg.on("framenavigated",
                                        lambda f: note(pg)))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("framenavigated", lambda f: note(page))
        page.goto(T4S_LOGIN)
        try:
            while ctx.pages:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    print()
    print("ログイン情報を保存しました。")
    if seen:
        VISITED.write_text("\n".join(seen), encoding="utf-8")
        print()
        print("開いた画面のURL（この中からレビューとキーワードの画面を教えてください）:")
        for u in seen[-25:]:
            print("  " + u)
        print()
        print("控えました:", VISITED)

        # 設定の雛形を置いておく。ASINの部分を {asin} に書き換えて使う
        if not CONF.exists():
            CONF.write_text(json.dumps({
                "_使い方": "下の2つに、レビュー画面とキーワード画面のURLを入れる。"
                           "ASINのところは {asin} に書き換える",
                "_控えたURL": VISITED.name + " を見てください",
                "reviews": "",
                "keywords": "",
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print()
            print("設定の雛形を作りました:", CONF)
            print("レビューとキーワードの画面URLを入れてください")
            print("（ASINのところは {asin} に書き換える）")


if __name__ == "__main__":
    main()
