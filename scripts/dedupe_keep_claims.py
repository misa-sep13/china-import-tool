"""商品キープの重複行を片付ける。

「採用したものを取り込む」が配送依頼済み（shipped）を見ておらず、押すたびに
同じ商品が keep として増えていた。その取りこぼし分を消す。

同じASINで shipped と keep が並んでいる場合、あとから入った keep のほうが
取り込みで生まれた重複なので、そちらを消して shipped を残す。
shipped 同士が並んでいる場合は、古いほう（先に工程が進んでいるほう）を残す。

既定は確認だけ。実際に消すときは --apply を付ける。
"""
import argparse
import os
import sys
from collections import defaultdict

import httpx

sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")

_ENV = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")


def _env() -> dict:
    v = {}
    try:
        with open(_ENV, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, val = line.partition("=")
                    v[k.strip()] = val.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="実際に消す（既定は確認だけ）")
    args = ap.parse_args()

    env = _env()
    backend = (os.environ.get("BACKEND_URL") or env.get("BACKEND_URL")
               or "https://china-import-tool.onrender.com").rstrip("/")
    token = os.environ.get("AUTH_SERVICE_TOKEN") or env.get("AUTH_SERVICE_TOKEN") or ""
    if not token:
        print(f"AUTH_SERVICE_TOKEN が見つかりません: {os.path.abspath(_ENV)}")
        return 1
    h = {"Authorization": f"Bearer {token}"}

    with httpx.Client(timeout=180, headers=h) as c:
        res = c.get(f"{backend}/api/keep-claims")
        res.raise_for_status()
        items = res.json().get("items", [])

    by_asin = defaultdict(list)
    for x in items:
        if x.get("asin"):
            by_asin[x["asin"]].append(x)

    # 残すものを決める。shipped を優先し、同じ状態なら古いほうを残す
    order = {"shipped": 0, "keep": 1, "expired": 2, "released": 3}
    targets = []
    for asin, rows in by_asin.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: (order.get(r.get("status"), 9), r.get("id") or 0))
        keep, drop = rows[0], rows[1:]
        targets.append((asin, keep, drop))

    if not targets:
        print("重複はありませんでした")
        return 0

    print(f"重複しているASIN: {len(targets)}件")
    total = 0
    for asin, keep, drop in targets:
        print(f"\n{asin}  {(keep.get('title') or '')[:34]}")
        print(f"   残す: id={keep.get('id')} status={keep.get('status')}")
        for d in drop:
            print(f"   消す: id={d.get('id')} status={d.get('status')} "
                  f"claimed={str(d.get('claimed_at'))[:10]}")
            total += 1

    if not args.apply:
        print(f"\n確認のみ（{total}件が対象）。実際に消すには --apply を付けてください")
        return 0

    print(f"\n{total}件を削除します...")
    done = 0
    with httpx.Client(timeout=180, headers=h) as c:
        for _, _, drop in targets:
            for d in drop:
                r = c.delete(f"{backend}/api/keep-claims/{d['id']}")
                if r.is_success:
                    done += 1
                else:
                    print(f"  id={d['id']} の削除に失敗: HTTP {r.status_code}")
    print(f"完了: {done}件を削除しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
