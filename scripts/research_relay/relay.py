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
PORT = 8765

T4S = "https://www.tool4seller.com"

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


def fetch_one(page, asin: str, kinds: set) -> dict:
    """1商品ぶん取る。取れなかった種類は入れずに返す。"""
    out = {}

    if "reviews" in kinds:
        try:
            page.goto(f"{T4S}/review/reviewList?asin={asin}",
                      wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            if not _logged_in(page):
                return {"error": "login"}
            rows = _read_table(page)
            if rows:
                out["reviews"] = {"head": rows[0], "rows": rows[1:]}
        except Exception as e:
            _log("レビュー取得に失敗", asin, type(e).__name__)

    if "keywords" in kinds:
        try:
            page.goto(f"{T4S}/keyword/keywordResearch?asin={asin}",
                      wait_until="domcontentloaded", timeout=60000)
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
    """ログイン用にブラウザを開く。閉じるまで待つ。"""
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True)
    print("tool4seller のログイン画面を開きます。")
    print("ログインしたら、この窓ではなくブラウザを閉じてください。")
    print("（レビューも取るなら、同じ窓で amazon.co.jp にもログイン）")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE), headless=False, locale="ja-JP")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(T4S + "/login")
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
    print("ログイン情報を保存しました。")


if __name__ == "__main__":
    main()
