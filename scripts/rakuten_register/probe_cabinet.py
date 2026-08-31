"""CompassにR-Cabinet（画像）の口があるか調べる。

画像の登録方法を推測で作ると、間違ったAPIを叩いて余計な事故に
なる。実際にどのエンドポイントが生きているか、GETだけで確かめる。

何も登録しない・何も変更しない。GETで叩いて応答コードを見るだけ。

使い方:
  python probe_cabinet.py
"""
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONF = os.path.join(os.path.expanduser("~"), ".rakuten_register.json")

# R-Cabinetの口として考えられるもの。楽天のCabinet APIを
# Compassが中継しているなら、この辺りに生えているはず
CANDIDATES = [
    # まず商品API。これが通れば認証は効いている（比較用）
    ("GET", "/api/rms/v1/es/2.0/ext/items/manage-numbers/y112"),
    ("GET", "/api/rms/v1/cabinet/usage/get"),
    ("GET", "/api/rms/v1/cabinet/folders/get"),
    ("GET", "/api/rms/v1/cabinet/folder/files/get?folderId=0"),
    ("GET", "/api/rms/v1/es/1.0/cabinet/usage/get"),
    ("GET", "/api/rms/v1/es/2.0/cabinet/folders"),
    # 商品APIと同じ es/2.0 の下にある可能性
    ("GET", "/api/rms/v1/es/2.0/ext/cabinet/folders"),
]

JS_GET = r"""
async ([method, path]) => {
  const m = document.querySelector('meta[name="csrf-token"]');
  const token = m ? m.content : (window.__csrf || '');
  return await new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open(method, path, true);
    if (token) x.setRequestHeader('X-CSRF-Token', token);
    x.onload = () => resolve({ status: x.status, body: x.responseText.slice(0, 400) });
    x.onerror = () => resolve({ status: 0, body: 'ネットワークエラー' });
    x.send(null);
  });
}
"""


async def run():
    from playwright.async_api import async_playwright

    conf = {}
    if os.path.exists(CONF):
        try:
            conf = json.load(open(CONF, encoding="utf-8"))
        except Exception:
            pass
    profile = conf.get("profile_dir") or os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "rakuten_register_profile")

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(profile, headless=False)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.compass-next.com/")

        if await page.locator("#user_password").count():
            print("Compassにログインしてください。終わったらEnterを押します")
            input("  … ログインできたらEnter: ")

        # CSRFトークンを先に用意する。無いまま叩くと全部401になり、
        # 口が無いのか認証が通っていないのか区別できない
        got = await page.evaluate(
            """async () => {
                 const m = document.querySelector('meta[name="csrf-token"]');
                 if (m) return m.content;
                 const r = await fetch(location.pathname, {credentials:'same-origin'});
                 return r.headers.get('csrf-token') || '';
               }""")
        await page.evaluate("t => { window.__csrf = t }", got or "")
        print()
        print(f"いまのURL: {page.url}")
        print(f"CSRFトークン: {'取れました' if got else '★取れませんでした'}")
        print()
        print("口を探しています（GETだけ。何も変更しません）")
        print()
        found, status_by_path = [], []
        for method, path in CANDIDATES:
            r = await page.evaluate(JS_GET, [method, path])
            status_by_path.append((path, r["status"]))
            mark = "○" if 200 <= r["status"] < 300 else " "
            print(f"  {mark} {r['status']:>3}  {path}")
            if 200 <= r["status"] < 300:
                if "items/manage-numbers" not in path:
                    found.append((path, r["body"]))
                print(f"        {r['body'][:200]}")

        print()
        item_ok = any("items/manage-numbers" in p and 200 <= st < 300
                      for p, st in status_by_path)
        if not item_ok:
            print("商品APIも通っていません。Compassにログインできていない可能性が")
            print("高いです。開いたブラウザでログイン状態を確認してください。")
        elif found:
            print("使えそうな口が見つかりました。この結果を貼ってください")
        else:
            print("商品APIは通るのに画像の口だけ全滅なので、Compassは")
            print("R-Cabinetを中継していないようです。")
            print("見つかりませんでした。Compassの画面で画像をアップロードするとき")
            print("どこへ送っているか、開発者ツールのNetworkタブで見ると分かります。")
            print("（F12 → Network → 画像をアップロード → 出てきたリクエストのURL）")

        await ctx.close()
    return 0


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(run()))
