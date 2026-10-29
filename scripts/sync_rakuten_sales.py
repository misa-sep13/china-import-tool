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
    # ログイン導入後、APIは認証必須になる（未設定の間は無視される）。
    service_token = os.environ.get("AUTH_SERVICE_TOKEN") or ""
    auth_headers = {"Authorization": f"Bearer {service_token}"} if service_token else {}

    # 1) RMSキーをRenderの設定APIから取得
    with httpx.Client(timeout=60, headers=auth_headers) as c:
        res = c.get(f"{backend}/api/rakuten/settings")
        res.raise_for_status()
        settings = res.json()
    secret = settings.get("rms_service_secret")
    license_key = settings.get("rms_license_key")
    if not secret or not license_key:
        print("ERROR: RMS APIキーが未設定です（楽天設定で登録してください）")
        return 1

    # 2) 重い受注取得 — GitHubランナーのメモリで実行
    #
    # 普段は60日。これは発注計算が見る窓に合わせてある。
    # DAYS を伸ばすと過去を遡って日別実績を埋める（季節商品の
    # 判定には去年の同じ時期が要る）。ただしそのときは
    # SKU別の合計を書き換えてはいけない。400日分の合計を
    # 「直近60日の販売数」として入れると、発注数が大幅に狂う
    days = int(os.environ.get("DAYS") or 60)
    backfill = days > 60
    order_qty_cap = settings.get("order_qty_cap", 3) or 0
    print(f"受注データ取得中（{days}日分、1注文キャップ={order_qty_cap}）...")
    if backfill:
        print("過去を埋めるモードです。日別実績だけ入れ、販売数の合計は触りません。")
    try:
        sku_sales, sku_daily = asyncio.run(
            fetch_sales_by_sku(secret, license_key, days=days, include_daily=True,
                               order_qty_cap=order_qty_cap)
        )
    except Exception as e:
        # 楽天RMSは定期メンテナンスで止まる（503 / ES01-02 API In Maintenance）。
        # こちらに直すところは無く、翌日の実行で通る。失敗にすると毎回
        # 通知メールが飛んで、本当の異常に気づけなくなるので静かに終える
        msg = str(e)
        if "ES01-02" in msg or "In Maintenance" in msg or "HTTP 503" in msg:
            print("楽天RMSがメンテナンス中のため、今回は何もせず終わります。")
            print(f"（楽天からの応答: {msg[:200]}）")
            print("次の定時実行で取り直します。")
            return 0
        raise
    print(f"取得SKU数: {len(sku_sales)}")

    with httpx.Client(timeout=180, headers=auth_headers) as c:
        # 3) 集計結果をRenderに送ってDB更新（従来のSKU別集計）
        if backfill:
            print("販売数の合計は更新しません（過去を埋めるモード）")
        else:
            res = c.post(f"{backend}/api/rakuten/rms/sales/apply", json={"sales": sku_sales})
            res.raise_for_status()
            result = res.json()
            print("反映結果:", result)

        # 4) 日別販売数をRenderに送ってDB更新（50 SKUずつバッチ送信）
        all_skus = list(sku_daily.keys())
        daily_count = sum(len(d) for d in sku_daily.values())
        print(f"日別データ送信中（{len(all_skus)} SKU × {daily_count} レコード）...")
        BATCH = 50
        total_upserted = 0
        for i in range(0, len(all_skus), BATCH):
            batch_skus = all_skus[i:i + BATCH]
            batch_data = {s: sku_daily[s] for s in batch_skus}
            res = c.post(
                f"{backend}/api/rakuten/rms/daily-sales/apply",
                json={"daily": batch_data},
                timeout=300,
            )
            res.raise_for_status()
            r = res.json()
            total_upserted += r.get("upserted", 0)
            print(f"  バッチ {i // BATCH + 1}/{-(-len(all_skus) // BATCH)}: {len(batch_skus)} SKU done")
        print(f"日別反映結果: upserted={total_upserted}")

        # 5) 在庫切れSKUをマーク。今の在庫を見るので、過去を
        #    埋めるときに走らせると昔の日まで在庫切れ扱いになる
        if not backfill:
            res = c.post(f"{backend}/api/rakuten/rms/daily-sales/mark-stockouts")
            res.raise_for_status()
            stockout_result = res.json()
            print("在庫切れマーク:", stockout_result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
