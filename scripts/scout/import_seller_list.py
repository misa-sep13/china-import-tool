"""配布された「セラーリスト」zip（sellers.json / sellers.csv）をサーバーへ登録する。

配布版セラースカウトから書き出した名簿を、そのまま一元管理へ入れるためのもの。
ローカルDBを作らずに済むので、引き継ぎのときはこれが一番早い。

使うのは seller_id / name / folder / url の4つだけ。
product_count や last_run_at は渡した側の巡回結果なので取り込まない
（こちらの巡回記録と混ざると、どちらの結果か分からなくなるため）。

使い方:
  python import_seller_list.py --file <展開したフォルダ>/sellers.json --token <トークン>
  python import_seller_list.py --file .../sellers.json --token <...> --dry-run
  python import_seller_list.py --zip "C:\\...\\セラーリスト_2026-08-30.zip" --token <...>
"""
import argparse
import csv
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_BASE = "https://china-import-tool.onrender.com/api"
KEEP = ("seller_id", "name", "folder", "url")


def rows_from_json(text):
    d = json.loads(text)
    # 書き出し方によって、配列そのものか {"sellers": [...]} のどちらかになる
    return d if isinstance(d, list) else d.get("sellers", [])


def rows_from_csv(text):
    # Excelで開けるようBOM付きで書き出されているので、それを剥がす
    return list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))


def load(args):
    if args.zip:
        with zipfile.ZipFile(args.zip) as z:
            names = z.namelist()
            for want, parse in (("sellers.json", rows_from_json),
                                ("sellers.csv", rows_from_csv)):
                hit = next((n for n in names if n.endswith(want)), None)
                if hit:
                    return parse(z.read(hit).decode("utf-8"))
        raise SystemExit("zipの中に sellers.json も sellers.csv もありません")

    path = args.file
    if not os.path.exists(path):
        raise SystemExit(f"ファイルがありません: {path}")
    text = io.open(path, encoding="utf-8").read()
    return rows_from_csv(text) if path.lower().endswith(".csv") else rows_from_json(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="", help="sellers.json か sellers.csv")
    ap.add_argument("--zip", default="", help="配布されたzipをそのまま指定してもよい")
    ap.add_argument("--base", default=os.environ.get("SCOUT_API", DEFAULT_BASE))
    ap.add_argument("--token", default=os.environ.get("APP_TOKEN", ""))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.file and not args.zip:
        raise SystemExit("--file か --zip を指定してください")

    rows = load(args)
    print(f"読み込み: {len(rows)}件")

    payload, skipped = [], 0
    seen = set()
    for r in rows:
        sid = (r.get("seller_id") or "").strip()
        if not sid or sid in seen:
            skipped += 1
            continue
        seen.add(sid)
        payload.append({k: (r.get(k) or None) for k in KEEP} | {"seller_id": sid})

    if skipped:
        print(f"  除外: {skipped}件（seller_idが空、または重複）")
    if not payload:
        raise SystemExit("送るものがありません")

    by_folder = {}
    for p in payload:
        by_folder[p["folder"] or "(なし)"] = by_folder.get(p["folder"] or "(なし)", 0) + 1
    print()
    print("フォルダ別:")
    for f, n in sorted(by_folder.items(), key=lambda x: -x[1]):
        print(f"  {n:>4}件  {f}")

    if args.dry_run:
        print()
        print(f"--dry-run なので送信しません（{len(payload)}件）。先頭3件:")
        for p in payload[:3]:
            print("  ", json.dumps(p, ensure_ascii=False)[:120])
        return 0

    print()
    print(f"サーバーへ送ります（{len(payload)}件）…")
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    req = urllib.request.Request(
        f"{args.base.rstrip('/')}/scout/sellers/bulk",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as res:
            r = json.load(res)
        print(f"完了: 新規{r.get('created', 0)}件 / 更新{r.get('updated', 0)}件")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code == 401:
            print("認証エラー: --token にログイン後のトークンを渡してください")
        else:
            print(f"エラー {e.code}: {body}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
