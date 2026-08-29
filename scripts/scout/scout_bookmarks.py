# -*- coding: utf-8 -*-
r"""Chrome のブックマークから「中国輸入セラー」を取り込む

  ブックマークは JSON の1ファイル。Chrome が起動中でも読めるので、
  Chrome を閉じてもらう必要はない (読むだけ・書き込まない)。

  拾うのは出品者プロフィール(/sp?seller=XXXX)。
  タイトルの「Amazon.co.jp出品者プロフィール：〇〇」から店名も取れる。

  使い方:
    python scout_bookmarks.py            … 取り込む
    python scout_bookmarks.py --dry-run  … 何が入るか見るだけ
"""
import os
import re
import io
import sys
import json
import argparse

if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import scout_db as db

LOCAL = os.environ.get("LOCALAPPDATA", "")
ROAMING = os.environ.get("APPDATA", "")
# Chrome だけ見ていると取りこぼす。2026-08-17に実測したところ Edge に46件、
# Firefox に93件のセラーがあり、うち8件は Chrome には無かった
CHROMIUM_ROOTS = [
    ("Chrome", os.path.join(LOCAL, r"Google\Chrome\User Data")),
    ("Edge",   os.path.join(LOCAL, r"Microsoft\Edge\User Data")),
    ("Brave",  os.path.join(LOCAL, r"BraveSoftware\Brave-Browser\User Data")),
]
FIREFOX_ROOT = os.path.join(ROAMING, r"Mozilla\Firefox\Profiles")

# 出品者IDは /sp?seller=... のほか /s?me=... の形でも保存されていることがある
SELLER_RE = re.compile(r"[?&](?:seller|me)=([A-Z0-9]{10,20})")
ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")
NAME_RE = re.compile(r"出品者プロフィール\s*[：:]\s*(.+)$")


def find_profiles():
    """Bookmarks ファイルを持つプロファイルを全部返す (Chromium系)"""
    out = []
    for brand, root in CHROMIUM_ROOTS:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name, "Bookmarks")
            if os.path.isfile(p):
                out.append((f"{brand}/{name}", p))
    return out


def collect_firefox():
    """Firefox のブックマークは places.sqlite の中。

    起動中はロックされるので、いったんコピーしてから読む。
    """
    import glob
    import shutil
    import sqlite3
    import tempfile
    rows = []
    for prof in sorted(glob.glob(os.path.join(FIREFOX_ROOT, "*"))):
        src = os.path.join(prof, "places.sqlite")
        if not os.path.isfile(src):
            continue
        tmp = os.path.join(tempfile.gettempdir(), "scout_places.sqlite")
        try:
            shutil.copy(src, tmp)
            con = sqlite3.connect(tmp)
            got = con.execute(
                "SELECT p.url, b.title, ("
                "  SELECT f.title FROM moz_bookmarks f WHERE f.id=b.parent"
                ") FROM moz_places p JOIN moz_bookmarks b ON b.fk=p.id"
                " WHERE p.url LIKE '%amazon%'").fetchall()
            con.close()
        except Exception as e:
            print(f"  [Firefox/{os.path.basename(prof)}] 読めません: {e}")
            continue
        n = 0
        for url, title, folder in got:
            m = SELLER_RE.search(url or "")
            if not m:
                continue
            sid = m.group(1)
            rows.append((sid, clean_name(title, sid), f"Firefox / {folder or ''}", url))
            n += 1
        print(f"[Firefox/{os.path.basename(prof)}] セラー {n} 件")
    return rows


def clean_name(title, seller_id):
    t = (title or "").strip()
    m = NAME_RE.search(t)
    if m:
        t = m.group(1).strip()
    # 「（商願２０２４－…）　新留さん」のような手書きメモは残す。消すと本人が探せない
    return t or seller_id


def collect(path):
    """1つのBookmarksから (seller_id, name, folder, url) を集める。

    あわせて、商品ページ(/dp/ASIN)のブックマークも拾って返す。こちらはURLに
    セラーIDが無いので、後で scout_resolve.py が商品ページから辿る。
    """
    with io.open(path, encoding="utf-8") as f:
        data = json.load(f)
    found, asins = {}, {}

    def walk(node, folders):
        if node.get("type") == "folder":
            sub = folders + [node.get("name", "")]
            for c in node.get("children", []):
                walk(c, sub)
            return
        url = node.get("url", "")
        if "amazon." not in url:
            return
        folder = " / ".join([f for f in folders if f])
        m = SELLER_RE.search(url)
        if m:
            sid = m.group(1)
            # 同じセラーが複数フォルダにいたら、最初に見つけた方を残す
            found.setdefault(sid, (sid, clean_name(node.get("name"), sid), folder, url))
            return
        m = ASIN_RE.search(url)
        if m:
            asins.setdefault(m.group(1),
                             (m.group(1), (node.get("name") or "").strip(), folder, url))

    for root in data.get("roots", {}).values():
        if isinstance(root, dict):
            walk(root, [])
    return list(found.values()), list(asins.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None,
                    help="Chromeのプロファイル名 (既定は全部)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    profiles = find_profiles()
    if a.profile:
        profiles = [p for p in profiles if p[0] == a.profile]
    if not profiles:
        print("Chromeのブックマークが見つかりませんでした")
        print(f"  探した場所: {CHROME_ROOT}")
        return 1

    allrows, allasins = {}, {}
    for pname, ppath in profiles:
        rows, asins = collect(ppath)
        print(f"[{pname}] セラー {len(rows)} 件 / 商品ページ {len(asins)} 件")
        for r in rows:
            allrows.setdefault(r[0], r)
        for r in asins:
            allasins.setdefault(r[0], r)
    for r in collect_firefox():
        allrows.setdefault(r[0], r)

    print(f"合計 セラー {len(allrows)} 件 / 商品ページ {len(allasins)} 件 (重複を除く)")
    if a.dry_run:
        for sid, name, folder, url in list(allrows.values())[:30]:
            print(f"  {sid}  {name}   <{folder}>")
        if len(allrows) > 30:
            print(f"  … 他 {len(allrows)-30} 件")
        return 0

    con = db.connect()
    added = 0
    for sid, name, folder, url in allrows.values():
        if db.upsert_seller(con, sid, name, folder, url):
            added += 1
    # 商品ページのブックマークは待ち行列に積むだけ。解決は scout_resolve.py
    queued = 0
    for asin, title, folder, url in allasins.values():
        cur = con.execute(
            "INSERT OR IGNORE INTO asin_queue(asin,title,folder,url,status,added_at)"
            " VALUES(?,?,?,?,'pending',?)", (asin, title, folder, url, db.now()))
        queued += cur.rowcount
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM sellers").fetchone()[0]
    pend = con.execute("SELECT COUNT(*) FROM asin_queue WHERE status='pending'").fetchone()[0]
    con.close()
    print(f"新規セラー {added} 件を追加しました (登録セラーは全部で {total} 件)")
    if queued:
        print(f"商品ページのブックマーク {queued} 件を待ち行列に積みました")
    if pend:
        print(f"→ 販売元が未解決の商品ページが {pend} 件あります。"
              f"「商品ページからセラーを探す」で辿れます")
    return 0


if __name__ == "__main__":
    sys.exit(main())
