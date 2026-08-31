"""ドラフトを楽天へ登録する。手元のPCで実行する。

楽天の商品APIは書込みに有料オプションが要り、未契約だと401（GA0001）に
なる。Compassにログインしたブラウザから内部APIへ送れば追加費用なしで
登録できるので、その方法を使う。ブラウザが要るためサーバーでは動かない。

  1. サーバーから登録待ちのドラフトを取ってくる
  2. Compassにログイン済みのブラウザで、内部APIへ3本送る
  3. 結果をサーバーへ戻す

使い方:
  python register.py                    # 登録待ちを全部
  python register.py --dry-run          # 送らずに中身だけ見る
  python register.py --limit 1          # 1件だけ試す
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_BASE = "https://china-import-tool.onrender.com/api"
CONF = os.path.join(os.path.expanduser("~"), ".rakuten_register.json")

# 連続で叩くと429になる。手順書の実測に合わせて間隔を空ける
WAIT_BETWEEN_ITEMS = 6.0      # 商品と商品のあいだ
WAIT_BETWEEN_CALLS = 1.2      # 在庫APIはQPS制限が厳しい（GA0003）
RETRY_WAIT = 20.0             # 429が出たときに待つ秒数


def load_conf():
    if os.path.exists(CONF):
        try:
            with open(CONF, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def api(base, path, token, method="GET", body=None):
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SystemExit("認証エラー: トークンを取り直してください")
        raise SystemExit(f"APIエラー {e.code}: {e.read().decode()[:300]}")


def build_variants(d):
    """バリエーションを楽天の形に組み立てる。

    楽天は variantSelectors（選択肢の定義）と variants（各枝）の
    2つで持つ。実在商品（y112）の構造に合わせている。

    軸が無ければ単品として1つだけ作る。
    """
    sku = d["sku"]
    base_price = d["price"]
    rows = d.get("variants") or []
    axis = (d.get("variant_axis") or "").strip()

    if not axis or not rows:
        # 単品。バリエーションIDは商品番号と揃えておく
        return None, {
            sku: {
                "standardPrice": base_price,
                "merchantDefinedSkuId": sku,
                "hidden": False,
            }
        }

    selectors = [{"key": "Key0", "displayName": axis, "values": []}]
    variants = {}
    for r in rows:
        label = str(r.get("label") or "").strip()
        if not label:
            continue
        # 枝のIDは y112_white の形。suffix が無ければ通し番号にする
        suffix = str(r.get("suffix") or "").strip() or f"v{len(variants) + 1}"
        selectors[0]["values"].append({"displayValue": label})
        variants[f"{sku}_{suffix}"] = {
            "selectorValues": {"Key0": label},
            "standardPrice": int(r.get("price") or base_price),
            "merchantDefinedSkuId": label,
            "hidden": False,
        }
    if not variants:
        raise ValueError("バリエーションの名前が空です")
    return selectors, variants


def build_item_body(d, shop_url):
    """商品本体（①のPUT）に送る中身を組み立てる。

    PUTは全項目置換なので、送らなかった項目は消える。新規登録なので
    問題ないが、既存商品に流用してはいけない。
    """
    selectors, variants = build_variants(d)
    body = {
        "title": d["rakuten_title"],
        "productDescription": {"pc": d.get("description_pc") or ""},
        "variants": variants,
    }
    if selectors:
        body["variantSelectors"] = selectors
    # 画像。R-Cabinetに上げたURLを渡す。楽天は location で持つ
    imgs = [u for u in (d.get("image_urls") or []) if u]
    if imgs:
        body["images"] = [{"location": u} for u in imgs]
    if d.get("catchcopy"):
        body["tagline"] = d["catchcopy"]
    if d.get("description_sp"):
        body["productDescription"]["sp"] = d["description_sp"]
    if d.get("genre_id"):
        body["genreId"] = str(d["genre_id"])
    return body


JS_SEND = r"""
async ([method, path, body]) => {
  // Compassの内部APIへ送る。fetchはブロックされることがあるのでXHRを使う。
  // 認証はログイン済みのCookieに乗るので、APIキーは要らない。
  const token = (() => {
    const m = document.querySelector('meta[name="csrf-token"]');
    if (m) return m.content;
    return window.__csrf || '';
  })();
  return await new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open(method, path, true);
    x.setRequestHeader('Content-Type', 'application/json;charset=UTF-8');
    if (token) x.setRequestHeader('X-CSRF-Token', token);
    x.onload = () => resolve({ status: x.status, body: x.responseText.slice(0, 800) });
    x.onerror = () => resolve({ status: 0, body: 'ネットワークエラー' });
    x.send(body === null ? null : JSON.stringify(body));
  });
}
"""


async def fetch_csrf(page):
    """CSRFトークンを用意する。

    metaタグに無いことがあるので、その場合は任意のGETの応答ヘッダから拾う。
    """
    got = await page.evaluate(
        """async () => {
             const m = document.querySelector('meta[name="csrf-token"]');
             if (m) return m.content;
             const r = await fetch(location.pathname, {credentials:'same-origin'});
             return r.headers.get('csrf-token') || '';
           }""")
    if got:
        await page.evaluate("t => { window.__csrf = t }", got)
    return got


async def send(page, method, path, body, label):
    """1本送る。429なら1回だけ待って再試行する。"""
    for attempt in (1, 2):
        r = await page.evaluate(JS_SEND, [method, path, body])
        if r["status"] != 429:
            break
        print(f"      429（混み合っています）。{RETRY_WAIT:.0f}秒待って再試行します")
        time.sleep(RETRY_WAIT)
    ok = 200 <= r["status"] < 300
    mark = "OK " if ok else "★NG"
    print(f"    {mark} {label}: {r['status']}")
    if not ok:
        print(f"        {r['body'][:300]}")
    return {"label": label, "method": method, "path": path,
            "status": r["status"], "body": r["body"][:500], "ok": ok}


async def register_one(page, d, shop_url, dry_run):
    """1商品を登録する。手順書どおり3本を順に送る。"""
    mn = d["sku"]
    item_body = build_item_body(d, shop_url)
    n_var = len(item_body["variants"])
    suffix = f"（{n_var}バリエーション）" if n_var > 1 else ""
    print(f"  {mn}: {d['rakuten_title'][:40]}{suffix}")

    calls = [
        ("PUT",
         f"/api/rms/v1/es/2.0/ext/items/manage-numbers/{mn}?shopUrl={shop_url}",
         item_body,
         "① 商品本体"),
        ("POST",
         "/api/rms/v1/es/2.1/inventories/bulk-upsert",
         # 全バリエーションぶん送る。入荷前なので0で作っておき、
         # 実際の在庫は既存の在庫連携が入れる
         {"inventories": [
             {"manageNumber": mn, "variantId": vid,
              # mode は必須。省略すると失敗する
              "quantity": 0, "mode": "ABSOLUTE"}
             for vid in item_body["variants"].keys()]},
         "② 在庫"),
        ("PUT",
         f"/api/rms/v1/es/2.0/categories/item-mappings/manage-numbers/{mn}",
         {"categoryIds": ["1"]},
         "③ 店舗内カテゴリ"),
    ]

    if dry_run:
        for method, path, body, label in calls:
            print(f"    [dry-run] {label}: {method} {path}")
            print(f"              {json.dumps(body, ensure_ascii=False)[:160]}")
        return {"ok": True, "log": [], "dry_run": True}

    log = []
    for i, (method, path, body, label) in enumerate(calls):
        if i:
            time.sleep(WAIT_BETWEEN_CALLS)
        r = await send(page, method, path, body, label)
        log.append(r)
        if not r["ok"]:
            # 商品本体が失敗したら在庫もカテゴリも意味がないので止める
            return {"ok": False, "log": log,
                    "error": f"{label}が{r['status']}で失敗しました"}
    return {"ok": True, "log": log}


async def run(args):
    from playwright.async_api import async_playwright
    import compass

    conf = load_conf()
    base = args.base or conf.get("base") or DEFAULT_BASE
    token = args.token or conf.get("token", "")
    shop_url = args.shop_url or conf.get("shop_url", "")
    if not token:
        raise SystemExit("トークンがありません。setup.py を実行してください")
    if not shop_url:
        raise SystemExit("店舗URL名がありません。setup.py を実行してください")

    print("登録待ちを取りに行きます…")
    j = api(base, f"/product-drafts/pending-register?limit={args.limit or 20}", token)
    ready, incomplete = j["ready"], j["incomplete"]
    print(f"  登録できる: {len(ready)}件 / 項目が足りない: {len(incomplete)}件")
    for d in incomplete:
        print(f"    - {d.get('sku') or '(SKUなし)'}: {'・'.join(d['missing'])}がありません")
    if not ready:
        print("登録するものがありません")
        return 0

    async with async_playwright() as pw:
        ctx, page = await compass.open_compass(pw)
        await fetch_csrf(page)

        done = failed = 0
        for n, d in enumerate(ready):
            if n:
                time.sleep(WAIT_BETWEEN_ITEMS)
            try:
                r = await register_one(page, d, shop_url, args.dry_run)
            except Exception as e:
                r = {"ok": False, "log": [], "error": f"{type(e).__name__}: {e}"}
                print(f"    ★NG {e}")
            if args.dry_run:
                continue
            api(base, f"/product-drafts/{d['id']}/register-result", token, "POST",
                {"ok": r["ok"], "error": r.get("error"), "log": r["log"]})
            done += r["ok"]
            failed += (not r["ok"])

        await compass.close(ctx)

    if args.dry_run:
        print()
        print("--dry-run なので何も送っていません")
        return 0

    print()
    print(f"完了: 登録{done}件 / 失敗{failed}件")
    if done:
        print("楽天の検索に出るまで20〜30分かかります。すぐ確認したいときは")
        print(f"  https://soko.rms.rakuten.co.jp/{shop_url}/<商品管理番号>/")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--shop-url", default="", help="店舗URL名")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import asyncio
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
