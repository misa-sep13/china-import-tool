"""SEO順位チェックをRenderのバックエンドに実行させ、完了までポーリングするスクリプト（GH Actions用）。

楽天へのアクセスはGitHub ActionsのIPがブロックされて機能しないため、
実際の順位取得はRenderサーバー側（/api/seo/check、楽天ウェブサービスAPI経由）で行う。
このスクリプトはジョブを開始し、完了をポーリングして結果を表示するだけ。
"""
import httpx
import os
import time

BACKEND = os.environ.get("BACKEND_URL", "https://china-import-tool.onrender.com")
POLL_INTERVAL_SEC = 15
MAX_WAIT_SEC = 3000


def main():
    with httpx.Client(timeout=30) as client:
        print("SEO順位チェックジョブを開始します（Renderサーバー側で実行）...")
        res = client.post(f"{BACKEND}/api/seo/check")
        res.raise_for_status()
        job_id = res.json()["job_id"]
        print(f"job_id={job_id}")

        waited = 0
        while waited < MAX_WAIT_SEC:
            time.sleep(POLL_INTERVAL_SEC)
            waited += POLL_INTERVAL_SEC
            status_res = client.get(f"{BACKEND}/api/seo/check/status/{job_id}")
            status_res.raise_for_status()
            data = status_res.json()
            if data["status"] == "done":
                results = data.get("results", [])
                errors = [r for r in results if r.get("error")]
                ok = [r for r in results if not r.get("error")]
                hit = [r for r in ok if r.get("ranks")]
                print(f"完了: {len(results)}件処理, ヒット{len(hit)}件, 圏外{len(ok) - len(hit)}件, エラー{len(errors)}件")
                for r in errors[:10]:
                    print(f"  ERROR: {r.get('keyword')}: {r.get('error')}")
                return
            if data["status"] == "error":
                print(f"ジョブ失敗: {data.get('error')}")
                raise SystemExit(1)
            print(f"実行中... ({waited}秒経過)")

        print("タイムアウト: ジョブが時間内に完了しませんでした")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
