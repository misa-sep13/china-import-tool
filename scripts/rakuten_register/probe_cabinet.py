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
    # Compassの画面に「画像の登録・編集」があるので、Compass独自の
    # 口を持っている可能性が高い。rms中継とは別の場所を探す
    ("GET", "/api/images"),
    ("GET", "/api/cabinet/folders"),
    ("GET", "/api/cabinet/files"),
    ("GET", "/api/rms/v1/cabinet/folders"),
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

        # ログイン画面かどうかの自動判定は当てにしない。
        # 判定が外れると「ログイン済み」と思い込んで全部401になり、
        # 口が無いのか認証が無いのか分からなくなる（実際にそうなった）。
        # 必ず一度止まって、人に画面を見てもらう
        await page.wait_for_timeout(2500)
        print()
        print("ブラウザを開きました。Compassの管理画面が見えていますか？")
        print("  ログイン画面なら、ログインしてください")
        print("  すでに管理画面ならそのままで大丈夫です")
        input("  … 準備できたらEnter: ")
        await page.wait_for_timeout(1500)

        # CSRFトークンを先に用意する。無いまま叩くと全部401になり、
        # 口が無いのか認証が通っていないのか区別できない
        # ログイン後のページで取り直す。ログイン画面のトークンでは通らない
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
            print()
            print("Compassの画面には「画像の登録・編集」があるので、独自の口を")
            print("持っているはずです。次の手順で調べられます:")
            print("  1. いま開いているブラウザで「画像の登録・編集」を開く")
            print("  2. F12 → Network タブ")
            print("  3. 画像を1枚アップロードする")
            print("  4. 一覧に出たリクエストのURLを教えてください")

        # 結果をファイルにも残す。画面が流れても後から見られるように
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "probe_result.txt")
        lines = [f"URL: {page.url}",
                 f"CSRF: {'取れた' if got else '取れなかった'}", ""]
        lines += [f"{st:>3}  {path}" for path, st in status_by_path]
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print()
        print(f"結果を保存しました: {out}")
        print()
        print("ブラウザは開いたままにしています。ログインできているか")
        print("画面で確かめてください。確認したらEnterで閉じます。")
        input("  … Enterで終了: ")

        await ctx.close()
    return 0


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(run()))
