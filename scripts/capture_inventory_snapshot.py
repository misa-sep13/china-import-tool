"""月末（JST 23:59）の在庫を期末在庫として確定する。

GitHub Actionsから毎月28〜31日の JST 23:59 に起動され、
「その日が月の最終日か」を判定して最終日だけ実行する。
（cronに「月末」の指定が無いため、日付側で絞る）

手動実行時は PERIOD / PLATFORMS 環境変数で対象を指定できる。
"""
import calendar
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

JST = timezone(timedelta(hours=9))
BACKEND_URL = (os.environ.get("BACKEND_URL") or "").rstrip("/")
PERIOD = (os.environ.get("PERIOD") or "").strip()
PLATFORMS = [p.strip() for p in (os.environ.get("PLATFORMS") or "rakuten,amazon").split(",") if p.strip()]
FORCE = (os.environ.get("FORCE") or "").lower() in ("1", "true", "yes")
# ログイン導入後、APIは認証必須になる（未設定の間は無視される）。
# GitHub Actions用のサービストークンをAUTH_SERVICE_TOKENで渡す。
_SERVICE_TOKEN = os.environ.get("AUTH_SERVICE_TOKEN") or ""
AUTH_HEADERS = {"Authorization": f"Bearer {_SERVICE_TOKEN}"} if _SERVICE_TOKEN else {}

if not BACKEND_URL:
    print("BACKEND_URL が設定されていません", file=sys.stderr)
    sys.exit(1)

now = datetime.now(JST)
last_day = calendar.monthrange(now.year, now.month)[1]

if not PERIOD and not FORCE and now.day != last_day:
    print(f"JST {now:%Y-%m-%d %H:%M} は月末（{now.year}-{now.month:02d}-{last_day}）ではないためスキップします")
    sys.exit(0)

period = PERIOD or f"{now.year:04d}-{now.month:02d}"
print(f"対象月: {period} / 対象: {', '.join(PLATFORMS)} （JST {now:%Y-%m-%d %H:%M}）")

failed = []
for platform in PLATFORMS:
    url = f"{BACKEND_URL}/inventory-snapshots/capture"
    try:
        # Amazonは在庫をSP-APIから取得するため時間がかかる
        res = httpx.post(url, json={"period": period, "platform": platform}, headers=AUTH_HEADERS, timeout=600)
    except Exception as e:
        print(f"  {platform}: 通信エラー {e}", file=sys.stderr)
        failed.append(platform)
        continue

    if res.status_code != 200:
        detail = ""
        try:
            detail = res.json().get("detail", "")
        except Exception:
            detail = res.text[:200]
        print(f"  {platform}: 失敗 HTTP {res.status_code} {detail}", file=sys.stderr)
        failed.append(platform)
        continue

    d = res.json()
    by_cat = d.get("by_category") or {}
    parts = " / ".join(f"{k} ¥{v:,}" for k, v in by_cat.items())
    no_cost = d.get("no_cost_skus") or []
    print(f"  {platform}: {d.get('items')}件  合計 ¥{d.get('total_amount', 0):,}  {parts}")
    if no_cost:
        print(f"    ※原価未設定で0円計上: {len(no_cost)}件 {', '.join(no_cost[:10])}")

if failed:
    print(f"失敗: {', '.join(failed)}", file=sys.stderr)
    sys.exit(1)
print("完了")
