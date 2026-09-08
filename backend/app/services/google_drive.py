"""Googleドライブへファイルを置く（輸入許可書の控え用）。

税理士へ渡す資料なので、ツールの中だけでなく共有ドライブにも
置いておきたい、という用途。設定が無ければ何もしない。

設定（Renderの環境変数）:
  GOOGLE_SERVICE_ACCOUNT_JSON … サービスアカウントの鍵（JSONそのまま）
  GOOGLE_DRIVE_FOLDER_ID      … 置き先フォルダのID（URLの /folders/ の後ろ）

注意: サービスアカウント自身は保存容量を持たない。個人のマイドライブの
フォルダを共有しただけだと storageQuotaExceeded で弾かれる。
「共有ドライブ」（Google Workspace）を作り、そこへサービスアカウントを
編集者として招いてから、そのフォルダIDを指定すること。
Workspaceを使っていない場合は、ツールからのZIP書き出しで渡すほうが早い。
"""
import json
import os

SCOPE = "https://www.googleapis.com/auth/drive"
UPLOAD_URL = ("https://www.googleapis.com/upload/drive/v3/files"
              "?uploadType=multipart&supportsAllDrives=true"
              "&fields=id,webViewLink")


class DriveError(Exception):
    """画面にそのまま出せる日本語のエラー。"""


def is_configured() -> bool:
    return bool(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
                and os.environ.get("GOOGLE_DRIVE_FOLDER_ID"))


def _token() -> str:
    # 設定していない環境でも起動できるよう、ここで読み込む
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except ImportError:
        raise DriveError(
            "google-auth が入っていません（requirements.txt を確認してください）")
    try:
        info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    except Exception:
        raise DriveError("GOOGLE_SERVICE_ACCOUNT_JSON がJSONとして読めません")
    try:
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=[SCOPE])
        creds.refresh(Request())
    except Exception as e:
        raise DriveError(f"Googleの認証に失敗しました（{type(e).__name__}）")
    return creds.token


def upload_pdf(filename: str, content: bytes) -> dict:
    """PDFを1つ置く。既に同名があっても上書きせず、別ファイルとして増える。

    上書きにすると、取り違えたときに元が消えて戻せない。
    """
    if not is_configured():
        raise DriveError(
            "Googleドライブの設定がありません"
            "（GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_DRIVE_FOLDER_ID）")
    import httpx

    meta = {"name": filename,
            "parents": [os.environ["GOOGLE_DRIVE_FOLDER_ID"]]}
    files = {
        "metadata": ("metadata.json", json.dumps(meta), "application/json"),
        "file": (filename, content, "application/pdf"),
    }
    try:
        r = httpx.post(UPLOAD_URL, files=files, timeout=120,
                       headers={"Authorization": f"Bearer {_token()}"})
    except Exception as e:
        raise DriveError(f"Googleドライブに繋がりませんでした（{type(e).__name__}）")

    if r.status_code >= 300:
        detail = ""
        try:
            detail = (r.json().get("error") or {}).get("message") or ""
        except Exception:
            detail = r.text[:200]
        if "storageQuota" in detail or "storage quota" in detail.lower():
            detail += ("（サービスアカウントには容量がありません。"
                       "共有ドライブのフォルダを指定してください）")
        raise DriveError(f"Googleドライブへ置けませんでした: {detail}")

    d = r.json()
    return {"file_id": d.get("id"), "url": d.get("webViewLink")}
