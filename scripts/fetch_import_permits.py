"""輸入許可書をメールから取り込む（毎日 GitHub Actions から）。

取り込みは「輸入許可書」の画面のボタンを押したときだけ動いていたため、
10/13 を最後に止まっていて、11月の便の許可書が入っていなかった。
毎日1回、直近の許可書メールを見て、まだ入っていないものだけ入れる
（同じ添付・同じ申告番号は入らないので、何度動いても増えない）。

見るフォルダは画面と同じ選び方：名前に「許可書」「許可通知」「permit」を含む
フォルダ。無ければ全フォルダ（ごみ箱などを除く）。
"""
import os
import re
import sys

import httpx

BACKEND_URL = (os.environ.get("BACKEND_URL") or "").rstrip("/")
DAYS = int(os.environ.get("DAYS") or 14)
_SERVICE_TOKEN = os.environ.get("AUTH_SERVICE_TOKEN") or ""
AUTH_HEADERS = {"Authorization": f"Bearer {_SERVICE_TOKEN}"} if _SERVICE_TOKEN else {}

if not BACKEND_URL:
    print("BACKEND_URL が設定されていません", file=sys.stderr)
    sys.exit(1)

with httpx.Client(timeout=180, headers=AUTH_HEADERS) as c:
    # Renderが眠っていると最初の1回が遅いので、軽い口で起こしておく
    try:
        c.get(f"{BACKEND_URL}/api/health")
    except Exception:
        pass

    folder = "*"
    try:
        r = c.get(f"{BACKEND_URL}/api/import-permits/folders")
        r.raise_for_status()
        for f in r.json().get("items") or []:
            if f.get("skip"):
                continue
            if re.search(r"許可書|許可通知|permit", f.get("label") or "", re.I):
                folder = f.get("raw") or folder
                print(f"フォルダ: {f.get('label')}")
                break
        else:
            print("許可書のフォルダが無いので全フォルダを見ます")
    except Exception as e:
        print(f"フォルダ一覧を取れませんでした（全フォルダを見ます）: {e}")

    results = []
    # 許可書のフォルダに加えて、念のため全フォルダも見る（振り分けに漏れた許可書を拾う）
    for fd in ([folder, "*"] if folder != "*" else ["*"]):
        r = c.post(f"{BACKEND_URL}/api/import-permits/fetch-mail",
                   json={"days": DAYS, "folder": fd})
        if r.status_code >= 400:
            print(f"取り込みに失敗しました（{fd}）: {r.status_code} {r.text[:300]}", file=sys.stderr)
            sys.exit(1)
        d = r.json()
        results.append(d)
        print(f"[{fd}] 見たPDF {d.get('scanned')}件 / 新しく入れた {d.get('added')}件")
        for p in d.get("items") or []:
            print(f"  + {p.get('permit_date')} {p.get('permit_no')} 税 ¥{p.get('total_tax')}")

print("完了")
