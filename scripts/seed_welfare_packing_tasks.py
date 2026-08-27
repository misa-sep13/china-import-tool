"""再梱包の作業マスタ40件を本番へ投入する。

作業名で照合して上書きするので、何度実行しても重複しない。
単価は既定3円で入れてあるので、違うものは画面から直す。

使い方（本番は認証が要るのでトークンを渡す）:
  python scripts/seed_welfare_packing_tasks.py --token <ログイン後のトークン>
  python scripts/seed_welfare_packing_tasks.py --dry-run     # 送らずに中身だけ見る
  python scripts/seed_welfare_packing_tasks.py --base http://127.0.0.1:8000/api
"""
import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "welfare_packing_tasks.json")

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="https://china-import-tool.onrender.com/api")
ap.add_argument("--token", default=os.environ.get("APP_TOKEN", ""))
ap.add_argument("--dry-run", action="store_true")
args = ap.parse_args()

payload = json.load(io.open(DATA, encoding="utf-8"))
linked = sum(1 for p in payload if p.get("sku"))
print(f"投入対象: {len(payload)}件（SKU紐づけ {linked}件 / 作業名のみ {len(payload) - linked}件）")

if args.dry_run:
    for p in payload[:5]:
        print("  ", json.dumps(p, ensure_ascii=False)[:110])
    print("  ...(dry-run なので送信しません)")
    raise SystemExit(0)

headers = {"Content-Type": "application/json"}
if args.token:
    headers["Authorization"] = f"Bearer {args.token}"

req = urllib.request.Request(
    f"{args.base}/welfare/packing-tasks/bulk",
    data=json.dumps(payload).encode(),
    headers=headers,
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=180) as res:
        print("結果:", json.load(res))
except urllib.error.HTTPError as e:
    body = e.read().decode()[:300]
    print(f"ERROR {e.code}: {body}")
    if e.code == 401:
        print("→ 認証が必要です。画面にログインしてトークンを --token で渡してください")
    raise SystemExit(1)
