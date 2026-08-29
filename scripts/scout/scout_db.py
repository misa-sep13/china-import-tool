# -*- coding: utf-8 -*-
r"""セラースカウトのデータ置き場 (SQLite)

  テーブルは4つだけ。
    sellers   … 巡回対象のセラー。Chromeのブックマークから取り込む
    products  … セラー×ASIN の最新の姿。画面の一覧はここを見る
    history   … 価格・販売数・レビューの移り変わり。1日1行だけ残す
    runs      … 「更新」1回ぶんの記録。途中で止まっても続きから再開するために使う

  販売数バッジ(「過去1か月で500点以上購入されました」)は Amazon が段階で丸めた値
  なので、数値としては下限しか分からない。sales_min に 500 を入れ、画面では
  「500+」と出す。バッジが無い商品は sales_min = 0 (＝50未満)。
"""
import os
import re
import sqlite3
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "セラースカウト.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sellers (
    seller_id     TEXT PRIMARY KEY,
    name          TEXT,
    folder        TEXT,
    url           TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    added_at      TEXT,
    last_run_at   TEXT,
    last_status   TEXT,          -- ok / blocked / error / (NULL=未巡回)
    last_note     TEXT,
    product_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    seller_id   TEXT NOT NULL,
    asin        TEXT NOT NULL,
    title       TEXT,
    image       TEXT,
    url         TEXT,
    price       INTEGER,         -- 円。取れなければ NULL
    sales_min   INTEGER,         -- 月間販売数の下限。バッジ無しは 0
    sales_text  TEXT,            -- バッジの原文。あとで仕様変更に気づけるように残す
    reviews     INTEGER,
    rating      REAL,
    page        INTEGER,         -- 何ページ目で見つけたか
    rank        INTEGER,         -- ベストセラー順の通し順位 (1始まり)
    first_seen  TEXT,
    last_seen   TEXT,
    PRIMARY KEY (seller_id, asin)
);
CREATE INDEX IF NOT EXISTS ix_products_sales   ON products(sales_min);
CREATE INDEX IF NOT EXISTS ix_products_reviews ON products(reviews);
CREATE INDEX IF NOT EXISTS ix_products_asin    ON products(asin);

CREATE TABLE IF NOT EXISTS history (
    seller_id  TEXT NOT NULL,
    asin       TEXT NOT NULL,
    day        TEXT NOT NULL,    -- YYYY-MM-DD
    price      INTEGER,
    sales_min  INTEGER,
    reviews    INTEGER,
    rating     REAL,
    PRIMARY KEY (seller_id, asin, day)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT,
    finished_at TEXT,
    status      TEXT,            -- running / done / stopped / aborted
    total       INTEGER DEFAULT 0,
    done        INTEGER DEFAULT 0,
    blocked     INTEGER DEFAULT 0,
    note        TEXT
);

-- 商品ページ(/dp/ASIN)でブックマークされたもの。URLにセラーIDが入っていないので
-- 商品ページを開いて「販売元」から辿る必要がある。その待ち行列
CREATE TABLE IF NOT EXISTS asin_queue (
    asin        TEXT PRIMARY KEY,
    title       TEXT,
    folder      TEXT,
    url         TEXT,
    seller_id   TEXT,           -- 解決できたセラーID
    seller_name TEXT,
    status      TEXT,           -- pending / ok / amazon / notfound / error
    added_at    TEXT,
    resolved_at TEXT
);

-- 競合リサーチシートへ持っていく「かご」。画面で目ぼしい商品を入れておき、
-- シート側の「セラースカウトから取り込む」でまとめて受け取る。
-- 受け取ったら taken_at を入れて、二重に取り込まないようにする
CREATE TABLE IF NOT EXISTS basket (
    asin     TEXT PRIMARY KEY,
    added_at TEXT,
    taken_at TEXT
);

-- ちょっとした覚え書き。いまは「登録ボタンが押された」の伝言に使っている。
-- セラースカウト(8791)と競合リサーチシート(file://)は別の生い立ちなので、
-- 画面から画面へ直接は渡せない。ここを経由して伝える
CREATE TABLE IF NOT EXISTS app_kv (
    k  TEXT PRIMARY KEY,
    v  TEXT,
    at TEXT
);

CREATE TABLE IF NOT EXISTS run_items (
    run_id    INTEGER NOT NULL,
    seller_id TEXT NOT NULL,
    status    TEXT,              -- pending / ok / blocked / error
    note      TEXT,
    done_at   TEXT,
    PRIMARY KEY (run_id, seller_id)
);
"""


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.date.today().isoformat()


def connect(path=DB_PATH):
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    migrate(con)
    return con


def migrate(con):
    """あとから足した列を、既存のDBにも入れる。

    CREATE TABLE IF NOT EXISTS は既にある表を作り直さないので、列の追加は
    ここでやらないと反映されない。
    """
    have = {r["name"] for r in con.execute("PRAGMA table_info(sellers)")}
    if "stop_reason" not in have:
        # なぜページをめくるのをやめたのか。
        #   badge_gone … 販売数バッジが尽きた(＝正常に読み切った)
        #   page_cap   … こちらの上限に当たった(＝まだ先がある。取りこぼし)
        #   no_more    … セラーの商品が尽きた
        con.execute("ALTER TABLE sellers ADD COLUMN stop_reason TEXT")
        con.execute("ALTER TABLE sellers ADD COLUMN last_pages INTEGER")
        con.commit()


# ---- バッジの読み取り ------------------------------------------------------
# 「過去1か月で500点以上購入されました」→ 500
# 「過去1か月で1万点以上購入されました」→ 10000
# 数字の書き方が変わっても静かに 0 にしないよう、拾えなかったら None を返して
# 呼び出し側で気づけるようにする。
_SALES_RE = re.compile(r"([\d,]+)\s*(万)?\s*点以上")


def parse_sales(text):
    """バッジの原文から下限個数を取り出す。バッジ自体が無ければ 0。"""
    if not text:
        return 0
    m = _SALES_RE.search(text.replace(",", ""))
    if not m:
        return None                      # 書き方が変わった＝要確認
    n = int(m.group(1))
    if m.group(2):                       # 「1万点以上」
        n *= 10000
    return n


def parse_price(text):
    if not text:
        return None
    m = re.search(r"([\d,]+)", text.replace("￥", "").replace("¥", ""))
    return int(m.group(1).replace(",", "")) if m else None


def parse_reviews(text):
    """aria-label の「146 レーティング」「146件の評価」などから件数を取り出す"""
    if not text:
        return None
    m = re.search(r"([\d,]+)", text)
    return int(m.group(1).replace(",", "")) if m else None


def parse_rating(text):
    """「5つ星のうち3.9」→ 3.9

    素直に最初の数字を採ると、頭の「5つ星」の 5 を掴んでしまい全商品が 5.0 に
    なる(2026-08-17に実測)。必ず「5つ星のうち」の後ろを見る。
    """
    if not text:
        return None
    m = re.search(r"5つ星のうち\s*([\d.]+)", text)
    if not m:
        m = re.search(r"([\d.]+)\s*(?:out of|/)\s*5", text)
    if not m:                               # 書き方が変わったら最後の数字を採る
        nums = re.findall(r"\d+(?:\.\d+)?", text)
        if not nums:
            return None
        m = re.match(r"(\d+(?:\.\d+)?)", nums[-1])
    try:
        v = float(m.group(1))
    except (ValueError, AttributeError):
        return None
    return v if 0 <= v <= 5 else None


# ---- 書き込み --------------------------------------------------------------
def upsert_seller(con, seller_id, name=None, folder=None, url=None):
    row = con.execute("SELECT seller_id FROM sellers WHERE seller_id=?",
                      (seller_id,)).fetchone()
    if row:
        # 名前は手で直しているかもしれないので、空のときだけ上書きする
        con.execute(
            "UPDATE sellers SET name=COALESCE(NULLIF(?,''), name),"
            " folder=COALESCE(NULLIF(?,''), folder), url=COALESCE(NULLIF(?,''), url)"
            " WHERE seller_id=?", (name or "", folder or "", url or "", seller_id))
        return False
    con.execute(
        "INSERT INTO sellers(seller_id,name,folder,url,enabled,added_at)"
        " VALUES(?,?,?,?,1,?)", (seller_id, name or "", folder or "", url or "", now()))
    return True


def save_products(con, seller_id, items):
    """1セラーぶんの取得結果を書き込む。差分ではなく毎回まるごと入れ替える。

    ただし DELETE はしない。売り切れ・削除された商品も「いつまで見えていたか」を
    last_seen で残したいため。画面側で最終確認日を出す。
    """
    day = today()
    ts = now()
    for it in items:
        con.execute("""
            INSERT INTO products(seller_id,asin,title,image,url,price,sales_min,
                                 sales_text,reviews,rating,page,rank,first_seen,last_seen)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(seller_id,asin) DO UPDATE SET
                title=excluded.title, image=excluded.image, url=excluded.url,
                price=excluded.price, sales_min=excluded.sales_min,
                sales_text=excluded.sales_text, reviews=excluded.reviews,
                rating=excluded.rating, page=excluded.page, rank=excluded.rank,
                last_seen=excluded.last_seen
        """, (seller_id, it["asin"], it["title"], it["image"], it["url"],
              it["price"], it["sales_min"], it["sales_text"], it["reviews"],
              it["rating"], it["page"], it["rank"], ts, ts))
        con.execute("""
            INSERT INTO history(seller_id,asin,day,price,sales_min,reviews,rating)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(seller_id,asin,day) DO UPDATE SET
                price=excluded.price, sales_min=excluded.sales_min,
                reviews=excluded.reviews, rating=excluded.rating
        """, (seller_id, it["asin"], day, it["price"], it["sales_min"],
              it["reviews"], it["rating"]))
    n = con.execute("SELECT COUNT(*) FROM products WHERE seller_id=?",
                    (seller_id,)).fetchone()[0]
    con.execute("UPDATE sellers SET product_count=? WHERE seller_id=?", (n, seller_id))


def mark_seller(con, seller_id, status, note="", stop_reason=None, pages=None):
    con.execute("UPDATE sellers SET last_run_at=?, last_status=?, last_note=?,"
                " stop_reason=?, last_pages=? WHERE seller_id=?",
                (now(), status, note, stop_reason, pages, seller_id))
