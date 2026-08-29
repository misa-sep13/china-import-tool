# -*- coding: utf-8 -*-
r"""商品ページのブックマークから「販売元」のセラーを探す

  「見込み商品」フォルダのように、セラーではなく商品ページ(/dp/ASIN)で
  ブックマークしているものは URL にセラーIDが入っていない。そこで商品ページを
  開いて、カートボックスの「販売元」のリンク(/sp?seller=…)からセラーを辿る。

  巡回本体と同じ作法で動く。温めてから、間を空けて、弾かれたら退く。
  ログインしたままなら中止する。

  使い方:
    python scout_resolve.py            … 未解決を全部
    python scout_resolve.py --limit 10 … 10件だけ試す
    python scout_resolve.py --hidden   … 画面の外で
"""
import os
import io
import sys
import time
import argparse

if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import scout_db as db
import scout_crawl as sc

# 販売元のリンクを拾う。売り切れ等でカートボックスが無いこともある
SELLER_JS = r"""
() => {
  const out = {seller_id: null, seller_name: null, by_amazon: false};
  const a = document.querySelector('#sellerProfileTriggerId')
        || document.querySelector('a[href*="/sp?"][href*="seller="]')
        || document.querySelector('#merchant-info a[href*="seller="]');
  if (a) {
    const m = (a.getAttribute('href') || '').match(/[?&]seller=([A-Z0-9]{10,20})/);
    if (m) { out.seller_id = m[1]; out.seller_name = (a.textContent || '').trim(); }
  }
  const box = document.querySelector('#merchant-info, #tabular-buybox, #buybox');
  const t = box ? (box.textContent || '') : '';
  if (!out.seller_id && /Amazon\.co\.jp\s*が販売|販売元\s*Amazon/.test(t)) out.by_amazon = true;
  return out;
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--hidden", action="store_true")
    ap.add_argument("--retry-failed", action="store_true",
                    help="前回エラーだったものもやり直す")
    ap.add_argument("--wait-min", type=float, default=3.0)
    ap.add_argument("--wait-max", type=float, default=7.0)
    ap.add_argument("--allow-signed-in", action="store_true")
    a = ap.parse_args()

    con = db.connect()
    cond = "status='pending'" if not a.retry_failed else "status IN ('pending','error')"
    sql = f"SELECT * FROM asin_queue WHERE {cond} ORDER BY added_at"
    if a.limit:
        sql += f" LIMIT {int(a.limit)}"
    rows = con.execute(sql).fetchall()
    if not rows:
        print("解決すべき商品ページはありません")
        return 0
    print(f"{len(rows)} 件の商品ページから販売元を探します "
          f"(目安 {len(rows)*7//60+1} 分)")

    if os.path.exists(sc.STOP_PATH):
        os.remove(sc.STOP_PATH)

    from playwright.sync_api import sync_playwright
    browser_args = ["--disable-blink-features=AutomationControlled"]
    if a.hidden:
        browser_args.append("--window-position=-3000,0")

    found = amazon = miss = err = 0
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                sc.PROFILE_DIR, channel="chrome", headless=False,
                args=browser_args, locale="ja-JP",
                viewport={"width": 1400, "height": 1000})
        except Exception as e:
            # 同じプロファイルのChromeは1つしか開けない
            print(f"ブラウザを起動できませんでした: {e}")
            print("すでに巡回が走っていませんか？")
            return 4
        c = sc.Crawler(ctx, a)

        ok_out, cookies = c.check_signed_out()
        if not ok_out and not a.allow_signed_in:
            print(f"!! Amazon にログインしています (cookie: {', '.join(cookies)})")
            print("!! アカウントに紐づけないため中止します")
            ctx.close()
            return 3

        sc.log("セッションを温めています…")
        if not c.warm_up():
            print("トップページが開けませんでした。時間をおいて試してください")
            ctx.close()
            return 2

        for i, r in enumerate(rows, 1):
            if os.path.exists(sc.STOP_PATH):
                sc.log("STOP ファイルを見つけたので止めます")
                break
            asin = r["asin"]
            sc.log(f"[{i}/{len(rows)}] {asin} {(r['title'] or '')[:34]}")
            status = seller_id = seller_name = None
            for attempt in range(3):
                try:
                    c.pg.goto(f"https://www.amazon.co.jp/dp/{asin}",
                              wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    sc.log(f"  ! 開けません: {e}")
                    status = "error"
                    break
                sc.nap(a.wait_min, a.wait_max)
                st = sc.page_state(c.pg)
                if st == "ok":
                    break
                if attempt < 2:
                    c.cool_down(attempt)
            else:
                status = "error"

            if status != "error":
                try:
                    got = c.pg.evaluate(SELLER_JS)
                except Exception:
                    got = {}
                if got.get("seller_id"):
                    seller_id = got["seller_id"]
                    seller_name = got.get("seller_name") or seller_id
                    status = "ok"
                elif got.get("by_amazon"):
                    status = "amazon"          # Amazon本体が販売＝リサーチ対象外
                else:
                    status = "notfound"        # 在庫切れ等でカートボックスが無い

            if status == "ok":
                # ブックマークのフォルダを引き継ぐと、あとで由来が分かる
                new = db.upsert_seller(con, seller_id, seller_name,
                                       r["folder"] or "商品ページから",
                                       f"https://www.amazon.co.jp/sp?seller={seller_id}")
                sc.log(f"  → {seller_name} ({seller_id})" + ("  ★新規" if new else "  既出"))
                found += 1
            elif status == "amazon":
                sc.log("  → Amazon本体が販売元（対象外）")
                amazon += 1
            elif status == "notfound":
                sc.log("  → 販売元が見つかりません（在庫切れ等）")
                miss += 1
            else:
                sc.log("  → エラー")
                err += 1

            con.execute("UPDATE asin_queue SET seller_id=?, seller_name=?, status=?,"
                        " resolved_at=? WHERE asin=?",
                        (seller_id, seller_name, status, db.now(), asin))
            con.commit()
            if i < len(rows):
                sc.nap(a.wait_min, a.wait_max)
        ctx.close()

    total = con.execute("SELECT COUNT(*) FROM sellers").fetchone()[0]
    con.close()
    print(f"\n終了: 販売元を特定 {found} / Amazon本体 {amazon} / "
          f"見つからず {miss} / エラー {err}")
    print(f"登録セラーは全部で {total} 件になりました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
