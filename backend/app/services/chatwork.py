"""Chatworkへの送信。

画像作成指示書のWordを、外注さんのルームへそのまま送るために使う。
これまでは書き出したファイルを手でチャットに貼っていた。

トークンはそのアカウントとして書き込める権限そのものなので、
ブラウザには渡さずここで持つ（タオタロウのトークンと同じ扱い）。

仕様上の注意点:
  ・認証はヘッダー X-ChatWorkToken
  ・ファイルは multipart/form-data の file。1ファイル5MBまで
  ・レート制限は5分300回
  ・送ったメッセージは取り消せる（相手が読む前なら）が、
    通知は飛ぶ。押す前に画面で確認させる
"""
from typing import Optional

import httpx

from app.core.config import settings

TIMEOUT = 60
MAX_FILE_BYTES = 5 * 1024 * 1024


class ChatworkError(Exception):
    """業務エラー。message はそのまま画面に出せる日本語。"""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.message = message
        self.status = status


def is_configured() -> bool:
    return bool(settings.CHATWORK_API_TOKEN)


def _headers() -> dict:
    if not is_configured():
        raise ChatworkError("Chatworkのトークンが未設定です（CHATWORK_API_TOKEN）")
    return {"X-ChatWorkToken": settings.CHATWORK_API_TOKEN,
            "Accept": "application/json"}


def _check(r: httpx.Response) -> dict:
    if r.status_code == 401:
        raise ChatworkError("Chatworkのトークンが通りませんでした", status=401)
    if r.status_code == 403:
        raise ChatworkError(
            "このトークンでは書き込めません（ルームの権限か、"
            "トークンの発行元アカウントをご確認ください）", status=403)
    if r.status_code == 429:
        raise ChatworkError("Chatworkの回数制限に当たりました。少し待ってください",
                            status=429)
    if r.status_code >= 300:
        detail = ""
        try:
            errs = r.json().get("errors") or []
            detail = "／".join(str(x) for x in errs)
        except Exception:
            detail = r.text[:200]
        raise ChatworkError(
            f"Chatworkがエラーを返しました（{r.status_code}）{detail}",
            status=r.status_code)
    try:
        return r.json()
    except Exception:
        return {}


def list_rooms() -> list:
    """入っているルームの一覧。送り先を画面で選んでもらうため。"""
    try:
        r = httpx.get(f"{settings.CHATWORK_API_BASE}/rooms",
                      headers=_headers(), timeout=TIMEOUT)
    except ChatworkError:
        raise
    except Exception as e:
        raise ChatworkError(f"Chatworkに繋がりませんでした（{type(e).__name__}）")
    rooms = _check(r) or []
    out = []
    for x in rooms:
        # 自分のマイチャットや既読専用の部屋まで並べると選びにくい。
        # 書き込める部屋だけに絞る
        if x.get("type") == "my":
            continue
        out.append({
            "room_id": x.get("room_id"),
            "name": x.get("name"),
            "type": x.get("type"),
            "can_post": (x.get("role") in ("admin", "member")),
        })
    out.sort(key=lambda x: str(x.get("name") or ""))
    return out


def send_file(room_id: str, filename: str, content: bytes,
              message: str = "") -> dict:
    """ファイルを1つ送る。メッセージを付けると本文になる。"""
    if not room_id:
        raise ChatworkError("送り先のルームが選ばれていません")
    if not content:
        raise ChatworkError("送るファイルが空です")
    if len(content) > MAX_FILE_BYTES:
        raise ChatworkError(
            f"ファイルが大きすぎます（{len(content) // 1024}KB／上限5MB）")

    files = {"file": (filename, content,
                      "application/vnd.openxmlformats-officedocument"
                      ".wordprocessingml.document")}
    data = {"message": message} if message else None
    try:
        r = httpx.post(f"{settings.CHATWORK_API_BASE}/rooms/{room_id}/files",
                       headers=_headers(), files=files, data=data,
                       timeout=TIMEOUT)
    except ChatworkError:
        raise
    except Exception as e:
        raise ChatworkError(f"Chatworkに繋がりませんでした（{type(e).__name__}）")
    d = _check(r)
    return {"file_id": d.get("file_id"), "room_id": room_id}


def send_message(room_id: str, body: str) -> dict:
    if not body.strip():
        raise ChatworkError("送る本文が空です")
    try:
        r = httpx.post(f"{settings.CHATWORK_API_BASE}/rooms/{room_id}/messages",
                       headers=_headers(), data={"body": body}, timeout=TIMEOUT)
    except ChatworkError:
        raise
    except Exception as e:
        raise ChatworkError(f"Chatworkに繋がりませんでした（{type(e).__name__}）")
    d = _check(r)
    return {"message_id": d.get("message_id"), "room_id": room_id}


def default_room() -> Optional[str]:
    return settings.CHATWORK_DEFAULT_ROOM_ID or None
