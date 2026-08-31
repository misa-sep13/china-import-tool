"""雛形にする商品を読んで、一元管理へ覚えさせる。

商品仕様（シリーズ名・素材・多頭用など）はジャンルごとに項目が変わる。
楽天にその定義を返すAPIは無かった（実測で404）ので、実在の商品が
持っている項目を借りる。同じジャンルなら同じ項目になる。

雛形を読めるのはCompassにログインしたブラウザだけなので、ここで読んで
サーバーへ送る。以後は画面がその項目を出せるようになる。

使い方:
  python read_template.py y96            # 1件
  python read_template.py y96 y112 y47   # まとめて
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import compass


def api(base, path, token, method="GET", body=None):
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SystemExit("認証エラー: トークンを取り直してください")
        raise SystemExit(f"APIエラー {e.code}: {e.read().decode()[:300]}")


JS_GET = r"""
async (path) => {
  const m = document.querySelector('meta[name="csrf-token"]');
  const token = m ? m.content : (window.__csrf || '');
  return await new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open('GET', path, true);
    if (token) x.setRequestHeader('X-CSRF-Token', token);
    x.onload = () => resolve({ status: x.status, body: x.responseText });
    x.onerror = () => resolve({ status: 0, body: 'ネットワークエラー' });
    x.send(null);
  });
}
"""


def summarize(item):
    """画面で使う情報だけ抜き出す。"""
    variants = item.get("variants") or {}
    first = next(iter(variants.values()), {})

    # 商品仕様の項目名。枝によって持っているものが違うことがあるので、
    # 全部の枝から集めて順番を保つ
    names, seen = [], set()
    for v in variants.values():
        for a in (v.get("attributes") or []):
            n = a.get("name")
            if n and n not in seen:
                seen.add(n)
                names.append(n)

    return {
        "genre_id": str(item.get("genreId") or ""),
        "attribute_names": names,
        "shipping": first.get("shipping") or {},
        "delivery": {
            "normalDeliveryDateId": first.get("normalDeliveryDateId"),
            "backOrderDeliveryDateId": first.get("backOrderDeliveryDateId"),
        },
        "variant_axes": [s.get("displayName")
                         for s in (item.get("variantSelectors") or [])],
    }


async def run(args):
    from playwright.async_api import async_playwright

    conf = compass.load_conf()
    base = conf.get("base") or "https://china-import-tool.onrender.com/api"
    token = conf.get("token", "")
    shop = conf.get("shop_url", "")
    if not token or not shop:
        raise SystemExit("設定がありません。setup.py を実行してください")

    async with async_playwright() as pw:
        ctx, page = await compass.open_compass(pw)
        await compass.csrf_token(page)

        for mn in args.skus:
            print()
            print(f"■ {mn}")
            r = await page.evaluate(
                JS_GET,
                f"/api/rms/v1/es/2.0/ext/items/manage-numbers/{mn}?shopUrl={shop}")
            if r["status"] != 200:
                print(f"  読めませんでした（{r['status']}）: {r['body'][:200]}")
                continue

            item = json.loads(r["body"])
            info = summarize(item)
            print(f"  ジャンルID  : {info['genre_id']}")
            print(f"  バリエーション軸: {'、'.join(info['variant_axes']) or '(単品)'}")
            print(f"  配送方法    : {json.dumps(info['shipping'], ensure_ascii=False)}")
            print(f"  納期        : {json.dumps(info['delivery'], ensure_ascii=False)}")
            print(f"  商品仕様の項目（{len(info['attribute_names'])}個）:")
            for n in info["attribute_names"]:
                print(f"      {n}")

            if args.dry_run:
                continue
            api(base, "/product-drafts/meta/template-info", token, "POST", {
                "manage_number": mn,
                "genre_id": info["genre_id"],
                "attribute_names": info["attribute_names"],
                "shipping": info["shipping"],
                "raw": {"delivery": info["delivery"],
                        "variant_axes": info["variant_axes"]},
            })
            print("  → サーバーへ覚えさせました")

        await compass.close(ctx)

    if args.dry_run:
        print()
        print("--dry-run なので送っていません")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("skus", nargs="+", help="雛形にする商品の管理番号")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    import asyncio
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
