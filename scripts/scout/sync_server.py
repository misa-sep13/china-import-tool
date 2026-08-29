"""セラースカウトのローカルDBと、一元管理サーバーを同期する。

巡回そのもの（scout_crawl.py）は配布版のまま手元のPCで走らせる。
Amazonはデータセンターのipからだと即ブロックするので、サーバー上では動かない。
このスクリプトは前後の受け渡しだけを担う。

  1. pull  : サーバーのセラー一覧をローカルDBへ取り込む（巡回対象を合わせる）
  2. 巡回  : scout_crawl.py を実行（このスクリプトからも呼べる）
  3. push  : ローカルDBの結果をサーバーへ送る

複数人で分担できる。割り当ては決めず、同じASINは新しい巡回で上書きする
（誰が回しても結果は同じなので、重複しても新しい情報になるだけ）。

使い方:
  python sync_server.py --token <ログイン後のトークン>              # pull→巡回→push
  python sync_server.py --token <...> --pull-only                  # セラーを取り込むだけ
  python sync_server.py --token <...> --push-only                  # 送るだけ
  python sync_server.py --token <...> --limit 30                   # 先頭30社だけ巡回
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
# 配布版の scout_db.py と同じファイルを見る（同じフォルダに置く前提）
DB_PATH = os.path.join(HERE, "セラースカウト.db")
DEFAULT_BASE = "https://china-import-tool.onrender.com/api"


def api(path, token, method="GET", body=None, timeout=180):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        if e.code == 401:
            raise SystemExit("認証エラー: --token にログイン後のトークンを渡してください")
        raise SystemExit(f"APIエラー {e.code}: {detail}")


def open_db():
    if not os.path.exists(DB_PATH):
        raise SystemExit(f"ローカルDBがありません: {DB_PATH}\n"
                         "先に配布版のセラースカウトを一度起動してください")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def pull_sellers(base, token):
    """サーバーのセラー一覧をローカルDBへ入れる。巡回対象を全員で揃えるため。"""
    j = api(f"{base}/scout/sellers", token)
    sellers = j.get("sellers", [])
    con = open_db()
    cur = con.cursor()
    n = 0
    for s in sellers:
        cur.execute("""
            INSERT INTO sellers (seller_id, name, folder, url, enabled, added_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(seller_id) DO UPDATE SET
                name = excluded.name,
                folder = excluded.folder,
                url = excluded.url,
                enabled = excluded.enabled
        """, (s["seller_id"], s.get("name"), s.get("folder"), s.get("url"),
              1 if s.get("enabled", True) else 0))
        n += 1
    con.commit()
    con.close()
    print(f"サーバーから取り込み: {n}社")
    return n


def push_results(base, token, run_by, only_new=True):
    """ローカルDBの巡回結果をサーバーへ送る。セラー単位でまとめて送る。"""
    con = open_db()
    cur = con.cursor()

    # 巡回済みのセラーだけ送る
    where = "WHERE last_run_at IS NOT NULL"
    cur.execute(f"SELECT seller_id, name, folder, url, last_status, last_note "
                f"FROM sellers {where}")
    sellers = cur.fetchall()
    if not sellers:
        print("送るものがありません（まだ巡回していません）")
        con.close()
        return 0

    sent_sellers = sent_products = 0
    for s in sellers:
        cur.execute("""
            SELECT asin, title, image, url, price, sales_min, sales_text,
                   reviews, rating, page, rank
            FROM products WHERE seller_id = ?
        """, (s["seller_id"],))
        products = [dict(r) for r in cur.fetchall()]
        if not products and s["last_status"] == "ok":
            continue
        body = {
            "seller_id": s["seller_id"],
            "status": s["last_status"] or "ok",
            "note": s["last_note"],
            "run_by": run_by,
            "products": products,
        }
        try:
            r = api(f"{base}/scout/crawl-result", token, "POST", body)
            sent_sellers += 1
            sent_products += r.get("saved", 0)
            print(f"  送信 {s['seller_id']} ({s['name'] or '-'}): {r.get('saved', 0)}件")
        except SystemExit:
            raise
        except Exception as e:
            print(f"  ★失敗 {s['seller_id']}: {e}")

    con.close()
    print(f"送信完了: {sent_sellers}社 / {sent_products}商品")
    return sent_products


def run_crawl(extra_args):
    """配布版の巡回をそのまま呼ぶ。ブロック回避の作法は一切変えない。"""
    script = os.path.join(HERE, "scout_crawl.py")
    cmd = [sys.executable, script] + extra_args
    print("巡回を開始します:", " ".join(cmd))
    return subprocess.call(cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("SCOUT_API", DEFAULT_BASE))
    ap.add_argument("--token", default=os.environ.get("APP_TOKEN", ""))
    ap.add_argument("--run-by", default=os.environ.get("SCOUT_RUN_BY", ""),
                    help="誰が巡回したか（画面に出る）")
    ap.add_argument("--pull-only", action="store_true", help="セラーを取り込むだけ")
    ap.add_argument("--push-only", action="store_true", help="結果を送るだけ")
    ap.add_argument("--limit", type=int, default=0, help="先頭から何社まで巡回するか")
    ap.add_argument("--sellers", default="", help="セラーIDをカンマ区切りで指定")
    args, rest = ap.parse_known_args()

    base = args.base.rstrip("/")
    run_by = args.run_by or os.environ.get("USERNAME") or "unknown"

    if args.push_only:
        push_results(base, args.token, run_by)
        return

    pull_sellers(base, args.token)
    if args.pull_only:
        return

    crawl_args = []
    if args.sellers:
        crawl_args += ["--sellers", args.sellers]
    elif args.limit:
        crawl_args += ["--limit", str(args.limit)]
    else:
        crawl_args += ["--all"]
    crawl_args += rest

    rc = run_crawl(crawl_args)
    if rc != 0:
        print(f"巡回が異常終了しました（コード {rc}）。取れた分だけ送ります")

    push_results(base, args.token, run_by)


if __name__ == "__main__":
    main()
