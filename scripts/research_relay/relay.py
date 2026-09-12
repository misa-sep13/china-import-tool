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
SETTINGS = HERE / "settings.json"   # 一元管理のAPIの場所とトークン
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


def _proxy_base() -> str:
    """一元管理のAPIの場所。settings.json に書いておく。"""
    try:
        d = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return str(d.get("api_base") or "").rstrip("/")
    except Exception:
        return ""


def _proxy_token() -> str:
    try:
        d = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return str(d.get("token") or "")
    except Exception:
        return ""


def _log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


# ---------- tool4seller の操作 ----------

# 普段のChromeに入っている tool4seller 拡張のID
EXT_ID = "ocjlckkmllgdmmpiobopeblldmmhjpjk"


def find_extension() -> str:
    """tool4seller 拡張の場所を探す。

    レビュー（AI評価分析）は拡張が入っていないと動かない。
    拡張そのものは持たず、普段のChromeに入っているものを借りる。
    """
    import glob
    import os
    base = os.path.expandvars("%LOCALAPPDATA%")
    pat = os.path.join(base, "Google", "Chrome", "User Data", "*",
                       "Extensions", EXT_ID, "*")
    found = [d for d in glob.glob(pat)
             if os.path.exists(os.path.join(d, "manifest.json"))]
    # 版が複数あれば新しいほうを使う
    return sorted(found)[-1] if found else ""


def _new_page(pw, headless: bool = True):
    """ログイン済みのプロファイルでブラウザを開く。

    拡張はヘッドレスでは読み込まれない。拡張が要るときは画面を出して
    動かすしかないので、画面の外へ追いやって目に入らないようにする。
    """
    args = ["--disable-blink-features=AutomationControlled"]
    ext = find_extension()
    if ext:
        args += ["--disable-extensions-except=" + ext,
                 "--load-extension=" + ext,
                 # 画面の外に置く。閉じてしまうと拡張が動かない
                 "--window-position=-2400,-2400",
                 "--window-size=1280,900"]
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE),
        headless=(headless and not ext),
        args=args,
        locale="ja-JP",
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def _logged_in(page) -> bool:
    """ログインが生きているか。切れているとログイン画面へ飛ばされる。"""
    url = page.url or ""
    return "login" not in url.lower() and "signin" not in url.lower()


def _parse_html_table(raw: bytes) -> list:
    """落ちてきた .xls を、行 × 列の配列にする。

    拡張子は .xls だが中身はHTMLの表。Excelがそれを開けるので、
    tool4seller はこの形で書き出している。
    """
    import html as _html

    text = None
    for enc in ("utf-8", "cp932", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return []

    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = [_html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>",
                                     tr, re.S | re.I)]
        if any(cells):
            rows.append(cells)
    return rows


def _download_from_amazon(page, asin: str, want: str) -> list:
    """Amazonの商品ページで、拡張の「ダウンロード」から落とす。

    手でやるときと同じ場所を押している。tool4seller の管理画面側には
    ASINでレビューを一覧する場所が無く、拡張が商品ページに差し込む
    パネルからしか取れない（レビューはAmazonのログインも要る）。
    """
    page.goto("https://www.amazon.co.jp/dp/" + asin,
              wait_until="domcontentloaded", timeout=60000)
    # 拡張がパネルを描くまで待つ。ページの読み込み完了とは別に時間がかかる
    page.wait_for_timeout(14000)

    trig = page.locator(".searchGrayDownloadBtn").first
    trig.hover(timeout=20000)
    page.wait_for_timeout(2000)

    item = page.locator("li.el-dropdown-menu__item", has_text=want).first
    with page.expect_download(timeout=120000) as dw:
        item.click()
    return _parse_html_table(dw.value.path().read_bytes())


def _keywords_from_t4s(page, asin: str) -> list:
    """キーワードは tool4seller の「ASINキーワードリサーチ」から取る。

    Amazonの商品ページのダウンロードには「レビュー」と「商品画像」しか
    無いので、こちらは管理画面側で探す。
    """
    page.goto(T4S + "/asin_lookup_keywords",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    box = page.locator("input[placeholder*='ASIN']").first
    box.fill(asin, timeout=20000)
    page.locator("button", has_text="キーワードリサーチ").first.click(timeout=20000)

    # 検索が終わるまで待つ。件数が出るまでに時間がかかる
    page.wait_for_timeout(12000)
    try:
        page.wait_for_selector("table tbody tr", timeout=60000)
    except Exception:
        pass

    return page.evaluate("""() => {
      const tb = document.querySelector('table');
      if (!tb) return [];
      const out = [];
      for (const tr of tb.querySelectorAll('tr')) {
        const cells = [...tr.querySelectorAll('th,td')]
          .map(td => (td.innerText || '').trim().replace(/\\s+/g, ' '));
        if (cells.some(c => c)) out.push(cells);
      }
      return out;
    }""") or []


def fetch_one(page, asin: str, kinds: set) -> dict:
    """1商品ぶん取る。取れなかった種類は入れずに返す。

    取れなかった理由は errors に入れる。シートがそのまま画面に出すので、
    「不明なエラー」で終わらせない。
    """
    out = {"errors": []}

    if "rv" in kinds:
        try:
            rows = _download_from_amazon(page, asin, "レビュー")
            if len(rows) > 1:
                out["reviews"] = {"head": rows[0], "rows": rows[1:]}
            else:
                out["errors"].append("レビューが1件も返ってきませんでした")
        except Exception as e:
            _log("レビュー取得に失敗", asin, type(e).__name__, str(e)[:80])
            out["errors"].append("レビュー: " + type(e).__name__)

    if "kw" in kinds:
        try:
            rows = _keywords_from_t4s(page, asin)
            if len(rows) > 1:
                # シート側は「タブ区切りの生テキスト」を待っている
                out["keywords"] = {
                    "text": "\n".join("\t".join(r) for r in rows)}
            else:
                out["errors"].append("キーワードが1件も返ってきませんでした")
        except Exception as e:
            _log("キーワード取得に失敗", asin, type(e).__name__, str(e)[:80])
            out["errors"].append("キーワード: " + type(e).__name__)

    return out


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
    return {"ok": True, "results": got}


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
            # シートは rv / kw で送ってくる
            kinds = {k.strip() for k in
                     (q.get("kinds", ["rv,kw"])[0]).split(",") if k.strip()}
            asins = [a for a in asins if re.fullmatch(r"[A-Z0-9]{10}", a)]
            if not asins:
                return self._send({"ok": False, "error": "ASINがありません"})
            try:
                return self._send(t4s_fetch(asins, kinds))
            except Exception as e:
                _log("失敗", type(e).__name__, e)
                return self._send({"ok": False,
                                   "error": f"取り込みに失敗しました（{type(e).__name__}）"})

        # ここが持っていないもの（サジェスト・画像の文字）は
        # 一元管理のサーバーへ回す。
        # シートは「取り込みサーバーがあれば、そこに全部ある」前提で
        # 呼んでくるので、無いと 404 になって取れなくなる
        if _proxy_base():
            return self._proxy(u.path, u.query)

        self._send({"ok": False, "error": "not found"}, 404)

    def _proxy(self, path: str, query: str):
        """一元管理のサーバーへそのまま渡して、返ってきたものを返す。"""
        import urllib.error
        import urllib.request

        url = _proxy_base() + "/amazon-research" + path + (("?" + query) if query else "")
        req = urllib.request.Request(url)
        # シートから渡ってきたトークンをそのまま使う。
        # 無ければ settings.json のものを使う
        token = self.headers.get("Authorization", "")
        if not token:
            t = _proxy_token()
            token = ("Bearer " + t) if t else ""
        if token:
            req.add_header("Authorization", token)
        try:
            with urllib.request.urlopen(req, timeout=180) as res:
                body = res.read()
        except urllib.error.HTTPError as e:
            body = e.read()
        except Exception as e:
            return self._send({"ok": False,
                               "error": f"一元管理へ繋がりませんでした（{type(e).__name__}）"})
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _already_running() -> bool:
    """すでに動いていないか。

    2つ動くと、同じブラウザのプロファイルを取り合って両方おかしくなる。
    自動起動と手動起動が重なると起きるので、後から立ち上がったほうが退く。
    """
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/ping", timeout=3) as res:
            return b'"ok"' in res.read() or True
    except Exception:
        return False


def main():
    if "--login" in sys.argv:
        return login()
    if _already_running():
        _log("すでに動いています。この窓は閉じてかまいません")
        _log(f"（http://127.0.0.1:{PORT} で待ち受け中）")
        time.sleep(6)
        return
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



if __name__ == "__main__":
    main()
