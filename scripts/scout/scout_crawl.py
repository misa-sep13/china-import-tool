# -*- coding: utf-8 -*-
r"""セラーのストアフロントを巡回して商品を集める

  1セラーあたりの流れ (画面でやっている操作をそのままなぞる):
    1. 出品者プロフィール  /sp?seller=<ID>
    2. すべての結果を表示  /s?me=<ID>          … このリンクの行き先が /s?me=
    3. ベストセラー順      &s=exact-aware-popularity-rank
    4. 1〜4ページを巡回    &page=1..4

  【100件を完走させるための考え方】
  Amazon にブロックされる (「ご迷惑をおかけしています」) のは、たいてい
  「素性の分からない相手が短時間に大量に叩いた」と見なされたとき。だから対策は
  小細工ではなく、次の3つだけ。

    (1) セッションを温めて使い回す
        新品のプロファイルでいきなり /s?me= を開くと1発で弾かれる(実測)。
        先にトップページを開いて cookie を作り、そのブラウザを最後まで使い回す。
        プロファイルは残るので、2回目以降の実行はさらに通りやすい。
    (2) 間隔を空ける
        ページ間 2.5〜5.5秒、セラー間 6〜14秒。ゆらぎを持たせる。
        100セラー ≒ 45〜60分。速さではなく完走を取る。
    (3) 弾かれたら退く、そして続きから再開する
        弾かれたら 60秒 → 150秒 → 300秒 と待ち時間を伸ばし、トップページで
        温め直してから同じセラーをやり直す。それでも駄目なら、そのセラーだけ
        「blocked」と記録して次へ。連続で弾かれ続けるときは走行そのものを止める
        (叩き続けるのが一番まずい)。途中で止まっても run_items に残るので
        --resume で続きから再開できる。

  使い方:
    python scout_crawl.py --limit 3            … 3セラーだけ試す
    python scout_crawl.py --all                … 登録セラー全部
    python scout_crawl.py --sellers A123,B456  … セラーIDを指定
    python scout_crawl.py --resume             … 前回の続きから
    python scout_crawl.py --all --hidden       … 画面の外で走らせる
"""
import os
import re
import io
import sys
import json
import time
import random
import argparse
import datetime

if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import scout_db as db

BASE = os.path.dirname(os.path.abspath(__file__))
STATUS_PATH = os.path.join(BASE, "run_status.json")
STOP_PATH = os.path.join(BASE, "STOP")      # このファイルを作ると走行を止める

# ブラウザのプロファイルは OneDrive の外へ。中に置くと起動のたびにキャッシュが
# 同期されて大量削除ダイアログが出る
PROFILE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", BASE), "amazon_scout_profile")

TOP = "https://www.amazon.co.jp/"
SORT_BEST = "exact-aware-popularity-rank"    # ベストセラー順

# ブロックされたページの目印
BLOCK_MARKS = ("ご迷惑をおかけしています", "Sorry! Something went wrong",
               "api-services-support@amazon.com", "エラーが発生しました")
CAPTCHA_MARKS = ("captcha", "文字を入力してください", "Enter the characters")
# 出品が1つも無いセラーの目印。2024年のブックマークには撤退済みが混ざるので、
# 「本当に空」と「取れなかった」を必ず別物として記録する
EMPTY_MARKS = ("一致する結果はありません", "に一致する商品はありませんでした")

# ページから商品を取り出す。DOM をたどるのは1回だけにして、あとは Python 側で整える
EXTRACT_JS = r"""
() => {
  const cards = document.querySelectorAll(
      'div[data-asin][data-component-type="s-search-result"]');
  const out = [];
  cards.forEach(el => {
    const asin = el.getAttribute('data-asin');
    if (!asin) return;
    const pick = (sels) => {
      for (const s of sels) { const n = el.querySelector(s); if (n) return n; }
      return null;
    };
    const img   = pick(['img.s-image', 'img[data-image-latency]']);
    const title = pick(['h2 span', 'h2 a span', '[data-cy="title-recipe"] a span',
                        'h2', '.a-size-medium.a-color-base']);
    const price = pick(['.a-price .a-offscreen', '.a-price-whole']);
    const rate  = pick(['i.a-icon-star-mini .a-icon-alt', 'i.a-icon-star .a-icon-alt',
                        '.a-icon-alt']);
    const rev   = pick(['a[aria-label$="レーティング"]', 'span[aria-label$="レーティング"]',
                        'a[aria-label*="件の評価"]', '[data-csa-c-slot-id] + a']);
    const link  = pick(['h2 a', 'a.a-link-normal.s-line-clamp-2',
                        '[data-cy="title-recipe"] a']);
    // 販売数バッジ。文言が変わっても拾えるよう「購入されました」だけを手がかりにする
    let sales = null;
    el.querySelectorAll('span').forEach(s => {
      const t = (s.textContent || '').trim();
      if (!sales && t.length < 40 && t.indexOf('購入されました') >= 0) sales = t;
    });
    out.push({
      asin,
      title: title ? title.textContent.trim() : '',
      image: img ? (img.getAttribute('src') || '') : '',
      href:  link ? (link.getAttribute('href') || '') : '',
      price: price ? price.textContent.trim() : '',
      rating: rate ? rate.textContent.trim() : '',
      reviews: rev ? (rev.getAttribute('aria-label') || rev.textContent.trim()) : '',
      sales
    });
  });
  return out;
}
"""


def log(msg):
    print(f"{datetime.datetime.now():%H:%M:%S} {msg}", flush=True)


def nap(lo, hi):
    time.sleep(random.uniform(lo, hi))


def write_status(**kw):
    kw["updated_at"] = db.now()
    try:
        with io.open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(kw, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def page_state(pg):
    """いまのページが 正常 / ブロック / CAPTCHA のどれかを見分ける"""
    try:
        title = (pg.title() or "")
        body = pg.locator("body").inner_text(timeout=5000)[:3000]
    except Exception:
        return "error"
    blob = title + " " + body
    if any(m in blob for m in CAPTCHA_MARKS):
        return "captcha"
    if any(m in blob for m in BLOCK_MARKS):
        return "blocked"
    return "ok"


class Crawler:
    def __init__(self, ctx, args):
        self.ctx = ctx
        self.pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        self.a = args
        self.warm = False

    # ---- ログインしていないことを確かめる -----------------------------------
    def check_signed_out(self):
        """Amazon にログインした状態で巡回していないかを見る。

        これが一番大事な安全策。ログインしていなければ、Amazon から見えるのは
        「どこかの誰かの普通の閲覧」でしかなく、アカウントに結びつかない。
        逆にログインしたまま大量に巡回すると、そのアカウントに紐づいて
        制限がかかりうる。買い物用アカウントは巻き添えにしない。
        """
        names = {c["name"] for c in self.ctx.cookies()}
        signed = {"at-acbjp", "sess-at-acbjp", "x-acbjp"} & names
        return (not signed), sorted(signed)

    # ---- セッションを温める -------------------------------------------------
    def warm_up(self):
        """トップページで cookie を作る。ここが通らないと以降は全部弾かれる"""
        self.pg.goto(TOP, wait_until="domcontentloaded", timeout=60000)
        nap(2.0, 4.0)
        try:                                  # 人が見ているように少しスクロール
            self.pg.mouse.wheel(0, random.randint(600, 1600))
        except Exception:
            pass
        nap(1.0, 2.0)
        st = page_state(self.pg)
        self.warm = (st == "ok")
        if not self.warm:
            log(f"  ! トップページが {st} でした")
        return self.warm

    def cool_down(self, attempt):
        """弾かれたときに退く。回を追うごとに長く待つ"""
        waits = [60, 150, 300, 600]
        w = waits[min(attempt, len(waits) - 1)]
        log(f"  ブロックされました。{w}秒待って温め直します (試行 {attempt+1})")
        write_status(state="cooldown", wait_sec=w)
        for _ in range(w):
            if os.path.exists(STOP_PATH):
                return
            time.sleep(1)
        self.warm_up()

    # ---- 1ページ取る --------------------------------------------------------
    def fetch_page(self, seller_id, page_no):
        """1ページ読む。

        「描画待ち」と「ペース調整」は別物なので分けている。
        描画待ちは結果カードが出るまでの待ちで、出たらすぐ進んでよい（決め打ちで
        4秒待つのは、ただ遅いだけで安全性には何も寄与しない）。
        Amazonから見た速さを決めているのは、次の要求までの間隔＝ペース調整の方。
        """
        url = (f"https://www.amazon.co.jp/s?me={seller_id}"
               f"&s={SORT_BEST}&page={page_no}")
        if page_no > 1:
            url += f"&ref=sr_pg_{page_no}"
        self.pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            # 「結果が出た」と「結果が無い」の両方を待つ。結果カードだけを待つと、
            # 4ページ未満のセラーの最後の空ページで毎回タイムアウトぶん丸損する
            # (2026-08-17に実測: 1セラーあたり+16秒)
            self.pg.wait_for_function(
                """() => !!document.querySelector(
                       'div[data-asin][data-component-type="s-search-result"]')
                    || /一致する結果はありません|一致する商品はありませんでした/
                       .test(document.body.innerText)""",
                timeout=self.a.render_timeout * 1000)
        except Exception:
            time.sleep(1.0)          # ブロック等。本文を読むのに少しだけ待つ
        st = page_state(self.pg)
        if st != "ok":
            return st, []
        try:
            raw = self.pg.evaluate(EXTRACT_JS)
        except Exception as e:
            log(f"  ! 取り出しに失敗: {e}")
            return "error", []
        return "ok", raw

    def crawl_seller(self, seller_id, name):
        """1セラーを巡回して商品の配列を返す。(status, items, stop_reason, pages)

        stop_reason は「なぜページをめくるのをやめたか」。
        page_cap（上限に当たった＝まだ先がある）を必ず記録して呼び出し側に
        返すのが肝心。ここを黙って切ると、セラーが伸びたときに取りこぼしが
        誰にも気づかれないまま増えていく。
        """
        # 1. 出品者プロフィールを経由する。画面でやっている手順と同じにしておくと
        #    いきなり検索結果を叩くより素直に通る
        if self.a.visit_profile:
            try:
                self.pg.goto(f"https://www.amazon.co.jp/sp?seller={seller_id}",
                             wait_until="domcontentloaded", timeout=60000)
                nap(1.5, 3.0)
                st = page_state(self.pg)
                if st != "ok":
                    return st, [], None, 0
            except Exception as e:
                log(f"  ! プロフィール表示で失敗: {e}")

        items, seen, rank = [], set(), 0
        # ベストセラー順なので、販売数バッジは後ろのページほど減っていく。
        # 2026-08-17の実測(28社1,511商品): 1ページ目21.6% → 2ページ目4.7%
        # → 3ページ目1.4% → 4ページ目0.0%。しかも「0が出たあとに復活した」セラーは
        # 28社中0社だった。だからバッジが尽きたページで打ち切ってよい。
        # 固定ページ数より賢く、深い店は深く、浅い店は浅く取れる。
        reason, last_page = "page_cap", 0
        for page_no in range(1, self.a.pages + 1):
            st, raw = self.fetch_page(seller_id, page_no)
            if st != "ok":
                return st, items, None, last_page
            last_page = page_no
            if not raw:
                if page_no == 1:
                    # 1ページ目で0件。空の店なのか、取れなかったのかを見分ける
                    try:
                        body = self.pg.locator("body").inner_text(timeout=5000)
                    except Exception:
                        body = ""
                    if any(m in body for m in EMPTY_MARKS):
                        return "empty", [], "no_more", 1
                    return "error", [], None, 1
                reason = "no_more"                      # これ以上ページが無い
                break
            new_on_page = badge_on_page = 0
            for r in raw:
                asin = r["asin"]
                if asin in seen:
                    continue                            # 同じ商品が再掲されることがある
                seen.add(asin)
                rank += 1
                new_on_page += 1
                sales_min = db.parse_sales(r.get("sales"))
                if sales_min is None:                   # バッジの書き方が変わった
                    log(f"  ! 販売数バッジを読めません: {r.get('sales')!r}")
                    # 読めなかったものは「バッジあり」側で数える。0扱いにすると
                    # 文言変更のときに静かに1ページで打ち切ってしまう
                    sales_min, badge_on_page = 0, badge_on_page + 1
                elif sales_min > 0:
                    badge_on_page += 1
                href = r.get("href") or ""
                if href.startswith("/"):
                    href = "https://www.amazon.co.jp" + href
                items.append({
                    "asin": asin,
                    "title": r["title"],
                    "image": r["image"],
                    "url": href or f"https://www.amazon.co.jp/dp/{asin}",
                    "price": db.parse_price(r["price"]),
                    "sales_min": sales_min,
                    "sales_text": r.get("sales") or "",
                    "reviews": db.parse_reviews(r["reviews"]),
                    "rating": db.parse_rating(r["rating"]),
                    "page": page_no,
                    "rank": rank,
                })
            log(f"    {page_no}ページ目: {new_on_page}件 "
                f"(販売数バッジ {badge_on_page}件)")
            if new_on_page == 0:
                reason = "no_more"
                break
            if self.a.early_stop and badge_on_page == 0:
                log(f"    → バッジが無くなったので{page_no}ページで打ち切ります")
                reason = "badge_gone"
                break
            if page_no < self.a.pages:
                nap(self.a.page_wait_min, self.a.page_wait_max)   # ペース調整はここだけ
        else:
            # for を最後まで回り切った＝上限に当たった。バッジがまだ出ていたなら
            # このセラーはもっと深くまで売れている。取りこぼしとして記録する
            if not (self.a.early_stop and badge_on_page == 0):
                log(f"    ! {self.a.pages}ページの上限に当たりました（まだ先があります）")
                reason = "page_cap"
            else:
                reason = "badge_gone"
        return "ok", items, reason, last_page


def pick_sellers(con, a):
    if a.sellers:
        ids = [s.strip() for s in a.sellers.split(",") if s.strip()]
        q = ",".join("?" * len(ids))
        rows = con.execute(
            f"SELECT seller_id,name FROM sellers WHERE seller_id IN ({q})", ids).fetchall()
        return [(r["seller_id"], r["name"]) for r in rows]

    sql = "SELECT seller_id,name FROM sellers WHERE enabled=1"
    if a.stale_days:                      # 最近取ったセラーは飛ばす
        sql += (" AND (last_run_at IS NULL OR last_run_at <"
                f" datetime('now','localtime','-{int(a.stale_days)} day'))")
    # 一度も取っていないセラー → 取得が古いセラー の順に片づける
    sql += " ORDER BY (last_run_at IS NOT NULL), last_run_at"
    if a.limit:
        sql += f" LIMIT {int(a.limit)}"
    return [(r["seller_id"], r["name"]) for r in con.execute(sql).fetchall()]


def open_run(con, a, targets):
    """走行を1つ作る。--resume なら前回の未完了ぶんを引き継ぐ"""
    if a.resume:
        row = con.execute("SELECT * FROM runs WHERE status IN ('running','stopped')"
                          " ORDER BY run_id DESC LIMIT 1").fetchone()
        if row:
            rid = row["run_id"]
            rest = con.execute("SELECT seller_id FROM run_items WHERE run_id=?"
                               " AND status='pending'", (rid,)).fetchall()
            if rest:
                ids = [r["seller_id"] for r in rest]
                q = ",".join("?" * len(ids))
                names = {r["seller_id"]: r["name"] for r in con.execute(
                    f"SELECT seller_id,name FROM sellers WHERE seller_id IN ({q})",
                    ids).fetchall()}
                con.execute("UPDATE runs SET status='running' WHERE run_id=?", (rid,))
                con.commit()
                log(f"前回の続きから再開します (残り {len(ids)} 件)")
                return rid, [(i, names.get(i, i)) for i in ids]
        log("再開できる走行がありませんでした。新しく始めます")

    cur = con.execute("INSERT INTO runs(started_at,status,total) VALUES(?,?,?)",
                      (db.now(), "running", len(targets)))
    rid = cur.lastrowid
    for sid, _ in targets:
        con.execute("INSERT OR REPLACE INTO run_items(run_id,seller_id,status)"
                    " VALUES(?,?,'pending')", (rid, sid))
    con.commit()
    return rid, targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="登録セラーを全部")
    ap.add_argument("--limit", type=int, default=0, help="先頭から何件まで")
    ap.add_argument("--sellers", default="", help="セラーIDをカンマ区切りで指定")
    ap.add_argument("--resume", action="store_true", help="前回の続きから")
    # 既定を4→12に引き上げた。止まる条件は「バッジが尽きたら」であって
    # ページ数ではない。ページ数は暴走を止めるための安全上限にすぎず、
    # ここに当たった場合は取りこぼしとして記録して画面に出す。
    # (--no-early-stop のときだけ、従来どおり固定ページ数として働く)
    ap.add_argument("--pages", type=int, default=12,
                    help="1セラーあたりのページ数の上限（安全のための頭打ち）")
    ap.add_argument("--stale-days", type=int, default=0,
                    help="この日数以内に取得済みのセラーは飛ばす")
    # ページ間・セラー間の「間隔」だけが Amazon から見た速さを決める。
    # 描画待ち(--render-timeout)は上限であって、出たらすぐ進むので実測1〜2秒。
    ap.add_argument("--page-wait-min", type=float, default=2.5)
    ap.add_argument("--page-wait-max", type=float, default=5.5)
    ap.add_argument("--seller-wait-min", type=float, default=6.0)
    ap.add_argument("--seller-wait-max", type=float, default=14.0)
    ap.add_argument("--render-timeout", type=float, default=8.0,
                    help="ページが出るまで待つ上限（秒）。通常1〜2秒で出る")
    ap.add_argument("--fast", action="store_true",
                    help="安全寄りの最速設定にする（間隔を詰める）")
    ap.add_argument("--no-early-stop", dest="early_stop", action="store_false",
                    default=True,
                    help="販売数バッジが無くなっても最後のページまで読む")
    ap.add_argument("--max-block-retry", type=int, default=3,
                    help="1セラーが弾かれたときに何回やり直すか")
    ap.add_argument("--abort-after", type=int, default=5,
                    help="連続でこの数だけ弾かれたら走行を止める")
    ap.add_argument("--hidden", action="store_true", help="画面の外で走らせる")
    ap.add_argument("--allow-signed-in", action="store_true",
                    help="Amazonにログインしたままでも巡回する(おすすめしません)")
    ap.add_argument("--no-visit-profile", dest="visit_profile", action="store_false",
                    default=True, help="出品者プロフィールを経由しない(要求数を減らす)")
    a = ap.parse_args()

    if not (a.all or a.limit or a.sellers or a.resume):
        ap.error("--all / --limit / --sellers / --resume のどれかを指定してください")

    if a.fast:
        # 出品者プロフィールの経由をやめる＝要求が1セラーあたり5回→4回に減る。
        # 速くなるうえに叩く回数も減るので、安全性はむしろ上がる
        a.visit_profile = False
        a.page_wait_min, a.page_wait_max = 2.0, 4.0
        a.seller_wait_min, a.seller_wait_max = 3.0, 7.0

    if os.path.exists(STOP_PATH):
        os.remove(STOP_PATH)

    con = db.connect()
    targets = pick_sellers(con, a)
    if not targets and not a.resume:
        log("対象のセラーがありません")
        return 0
    run_id, targets = open_run(con, a, targets)
    total = len(targets)
    log(f"走行 #{run_id}: {total} 件を巡回します "
        f"(1セラー {a.pages}ページ / 目安 {total*(a.pages*4+10)//60} 分)")

    from playwright.sync_api import sync_playwright

    args_browser = ["--disable-blink-features=AutomationControlled"]
    if a.hidden:
        args_browser.append("--window-position=-3000,0")

    done = blocked = errors = capped = 0
    streak = 0                      # 連続でブロックされた回数
    t0 = time.time()

    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                PROFILE_DIR, channel="chrome", headless=False,
                args=args_browser, locale="ja-JP",
                viewport={"width": 1400, "height": 1000},
            )
        except Exception as e:
            # 同じプロファイルのChromeは1つしか開けない。巡回と販売元探しを
            # 同時に走らせるとここで落ちる。何が起きたか分かるように書いておく
            log(f"ブラウザを起動できませんでした: {e}")
            log("すでに巡回か「商品ページからセラーを探す」が走っていませんか？")
            con.execute("UPDATE runs SET status='aborted', finished_at=?, note=?"
                        " WHERE run_id=?", (db.now(), "ブラウザ起動に失敗", run_id))
            con.commit()
            write_status(state="error", note="ブラウザを起動できませんでした")
            return 4
        c = Crawler(ctx, a)

        # ログインしたまま巡回しない。買い物用アカウントを巻き添えにしないため
        ok_out, found = c.check_signed_out()
        if not ok_out and not a.allow_signed_in:
            log("!! このブラウザは Amazon にログインしています "
                f"(cookie: {', '.join(found)})")
            log("!! アカウントに紐づけないため、巡回を中止します。")
            log("!! 開いた窓で右上からサインアウトするか、次を実行してください:")
            log(f"!!   rmdir /s /q \"{PROFILE_DIR}\"")
            con.execute("UPDATE runs SET status='aborted', finished_at=?, note=?"
                        " WHERE run_id=?", (db.now(), "ログイン状態のため中止", run_id))
            con.commit()
            write_status(state="signed_in", note="ログイン状態のため中止しました")
            ctx.close()
            return 3

        log("セッションを温めています…")
        if not c.warm_up():
            log("トップページが開けませんでした。時間をおいて試してください")
            con.execute("UPDATE runs SET status='aborted', finished_at=?, note=?"
                        " WHERE run_id=?", (db.now(), "温めに失敗", run_id))
            con.commit()
            ctx.close()
            return 2

        for idx, (sid, name) in enumerate(targets, 1):
            if os.path.exists(STOP_PATH):
                log("STOP ファイルを見つけたので止めます")
                con.execute("UPDATE runs SET status='stopped', finished_at=?"
                            " WHERE run_id=?", (db.now(), run_id))
                con.commit()
                break

            log(f"[{idx}/{total}] {name or sid} ({sid})")
            write_status(run_id=run_id, state="running", total=total, index=idx,
                         done=done, blocked=blocked, capped=capped,
                         seller=name or sid, seller_id=sid,
                         elapsed_sec=int(time.time() - t0))

            status, items, reason, npages = "", [], None, 0
            t_seller = time.time()
            for attempt in range(a.max_block_retry + 1):
                status, items, reason, npages = c.crawl_seller(sid, name)
                if status in ("ok", "empty"):
                    break
                if status == "captcha":
                    # 画像認証は人が解くしかない。勝手に突破しない
                    log("  CAPTCHA が出ました。ブラウザの窓で認証してください。"
                        "5分待ってから続けます")
                    write_status(run_id=run_id, state="captcha", seller=name or sid)
                    for _ in range(300):
                        if os.path.exists(STOP_PATH):
                            break
                        time.sleep(1)
                        if page_state(c.pg) == "ok":
                            break
                    continue
                if attempt < a.max_block_retry:
                    c.cool_down(attempt)
                    if os.path.exists(STOP_PATH):
                        break

            if status == "empty":
                # 撤退したセラー。過去に集めた商品は消さずに残す(いつまで見えていたかが分かる)
                db.mark_seller(con, sid, "empty", "出品なし", "no_more", 1)
                con.execute("UPDATE run_items SET status='empty', note='出品なし',"
                            " done_at=? WHERE run_id=? AND seller_id=?",
                            (db.now(), run_id, sid))
                log("  → 出品がありませんでした（撤退した可能性）")
                done += 1
                streak = 0
            elif status == "ok":
                db.save_products(con, sid, items)
                db.mark_seller(con, sid, "ok", f"{len(items)}件", reason, npages)
                if reason == "page_cap":
                    capped += 1
                con.execute("UPDATE run_items SET status='ok', note=?, done_at=?"
                            " WHERE run_id=? AND seller_id=?",
                            (f"{len(items)}件", db.now(), run_id, sid))
                hit = sum(1 for i in items if (i["sales_min"] or 0) > 0)
                log(f"  → {len(items)}件 (販売数バッジ付き {hit}件) "
                    f"[{time.time()-t_seller:.1f}秒]")
                done += 1
                streak = 0
            else:
                db.mark_seller(con, sid, status, "巡回できませんでした", None, npages)
                con.execute("UPDATE run_items SET status=?, done_at=?"
                            " WHERE run_id=? AND seller_id=?",
                            (status, db.now(), run_id, sid))
                log(f"  → {status} のため飛ばしました")
                if status == "blocked":
                    blocked += 1
                    streak += 1
                else:
                    errors += 1
            con.execute("UPDATE runs SET done=?, blocked=? WHERE run_id=?",
                        (done, blocked, run_id))
            con.commit()

            if streak >= a.abort_after:
                # ここで叩き続けるのが一番まずい。素直に降りて、続きは次回に回す
                log(f"{streak} 件続けて弾かれたので走行を止めます。"
                    f"時間をおいて --resume で続きから再開してください")
                con.execute("UPDATE runs SET status='stopped', finished_at=?, note=?"
                            " WHERE run_id=?",
                            (db.now(), f"連続ブロック{streak}件で中断", run_id))
                con.commit()
                break

            if idx < total:
                nap(a.seller_wait_min, a.seller_wait_max)

        row = con.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row and row["status"] == "running":
            con.execute("UPDATE runs SET status='done', finished_at=? WHERE run_id=?",
                        (db.now(), run_id))
            con.commit()
        ctx.close()

    mins = (time.time() - t0) / 60
    left = con.execute("SELECT COUNT(*) FROM run_items WHERE run_id=? AND status='pending'",
                       (run_id,)).fetchone()[0]
    log(f"終了: 成功 {done} / ブロック {blocked} / エラー {errors} / 残り {left} "
        f"({mins:.1f}分)")
    if capped:
        log(f"! {capped}社が{a.pages}ページの上限に当たりました。"
            f"「上限に当たったセラーを深追い」で拾えます")
    write_status(run_id=run_id, state="finished", total=total, done=done,
                 blocked=blocked, errors=errors, remaining=left, capped=capped,
                 elapsed_sec=int(time.time() - t0))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
