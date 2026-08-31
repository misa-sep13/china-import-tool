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

        print()
        print("R-Cabinetの口を探しています（GETだけ。何も変更しません）")
        print()
        found = []
        for method, path in CANDIDATES:
            r = await page.evaluate(JS_GET, [method, path])
            mark = "○" if 200 <= r["status"] < 300 else " "
            print(f"  {mark} {r['status']:>3}  {path}")
            if 200 <= r["status"] < 300:
                found.append((path, r["body"]))
                print(f"        {r['body'][:200]}")

        print()
        if found:
            print("使えそうな口が見つかりました。この結果を貼ってください")
        else:
            print("見つかりませんでした。Compassの画面で画像をアップロードするとき")
            print("どこへ送っているか、開発者ツールのNetworkタブで見ると分かります。")
            print("（F12 → Network → 画像をアップロード → 出てきたリクエストのURL）")

        await ctx.close()
    return 0


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(run()))
