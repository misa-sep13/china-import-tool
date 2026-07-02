"""
楽天売上同期（GitHub Actions実行用）

重い受注取得(60日分)はメモリ7GBのGitHubランナーで実行し、
集計したSKU別販売数だけをRenderの /api/rakuten/rms/sales/apply に送ってDB更新する。
（Renderは512MBのため、60日分の受注取得を走らせるとOOMして再起動するのを回避）

環境変数:
  BACKEND_URL  例: https://china-import-tool.onrender.com
"""
import asyncio
import os
import sys

import httpx

# backend/app/services/rakuten_rms.py を import できるようにする
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "backend"))

from app.services.rakuten_rms import fetch_sales_by_sku  # noqa: E402


def main() -> int:
    backend = os.environ.get("BACKEND_URL", "").rstrip("/")
    if not backend:
        print("ERROR: BACKEND_URL が未設定です")
        return 1

    # 1) RMSキーをRenderの設定APIから取得
    with httpx.Client(timeout=60) as c:
        res = c.get(f"{backend}/api/rakuten/settings")
        res.raise_for_status()
        settings = res.json()
    secret = settings.get("rms_service_secret")
    license_key = settings.get("rms_license_key")
    if not secret or not license_key:
        print("ERROR: RMS APIキーが未設定です（楽天設定で登録してください）")
        return 1

    # 2) 重い受注取得(60日) — GitHubランナーのメモリで実行
    print("受注データ取得中（60日分）...")
    sku_sales = asyncio.run(fetch_sales_by_sku(secret, license_key, days=60))
    print(f"取得SKU数: {len(sku_sales)}")

    # 3) 集計結果だけをRenderに送ってDB更新（Render側は軽い書き込みのみ）
    with httpx.Client(timeout=180) as c:
        res = c.post(f"{backend}/api/rakuten/rms/sales/apply", json={"sales": sku_sales})
        res.raise_for_status()
        result = res.json()
    print("反映結果:", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
