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
# es/1.0/cabinet/usage/get が200でXMLを返したので、Compassは
# 楽天の旧Cabinet APIをそのまま中継している。旧APIの口の名前で探す
CAB = "/api/rms/v1/es/1.0/cabinet"
CANDIDATES = [
    # まず商品API。これが通れば認証は効いている（比較用）
    ("GET", "/api/rms/v1/es/2.0/ext/items/manage-numbers/y96"),
    # ジャンルごとの商品仕様（属性）の定義。ジャンルで項目が変わるので、
    # 固定の入力欄では作れない。定義を取れるかどうかが分かれ目
    ("GET", "/api/rms/v1/es/2.0/genres/201887"),
    ("GET", "/api/rms/v1/es/2.0/genres/201887/attributes"),
    ("GET", "/api/rms/v1/es/2.0/product-attributes/genres/201887"),
    ("GET", "/api/rms/v1/es/2.0/item-attributes/genres/201887"),
    ("GET", "/api/rms/v1/es/1.0/genre/201887/attributes"),
    # 配送方法セット（ネコポス・宅急便など）の一覧
    ("GET", "/api/rms/v1/es/2.0/shipping-method-sets"),
    ("GET", "/api/rms/v1/es/2.0/navigation/shipping-methods"),
    # 納期情報・出荷リードタイムの選択肢
    ("GET", "/api/rms/v1/es/2.0/delivery-dates"),
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
    import compass

    async with async_playwright() as pw:
        ctx, page = await compass.open_compass(pw)
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
            # 405は「その口はあるが、このメソッドでは呼べない」という意味。
            # アップロード先はPOST専用なので、405なら見つかったのと同じ
            ok = 200 <= r["status"] < 300
            mark = "○" if ok else ("△" if r["status"] == 405 else " ")
            print(f"  {mark} {r['status']:>3}  {path}")
            if (ok or r["status"] == 405) and "items/manage-numbers" not in path:
                found.append((path, r["body"]))
            if ok or r["status"] == 405:
                print(f"        {r['body'][:220]}")

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

        await compass.close(ctx)
    return 0


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(run()))
