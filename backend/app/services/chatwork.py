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
import os
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


# 実際に送るのはこの2つだけ。入っている部屋を全部並べると、
# 選ぶのが面倒なうえ送り先を間違える。名前の一部で見る（部屋名が
# 多少変わっても拾えるように）。増やしたいときはここに足すか、
# 環境変数 CHATWORK_ROOMS に部屋名かroom_idをカンマ区切りで入れる。
_ROOM_ALLOW = ("画像制作依頼", "北田しずく", "HAMU-ha")


def _allow_list() -> tuple:
    raw = os.environ.get("CHATWORK_ROOMS", "")
    items = tuple(x.strip() for x in raw.split(",") if x.strip())
    return items or _ROOM_ALLOW


def _wanted(room: dict, allow: tuple) -> bool:
    name = str(room.get("name") or "")
    rid = str(room.get("room_id") or "")
    return any(a == rid or a in name for a in allow)


def list_rooms(all_rooms: bool = False) -> list:
    """送り先の一覧。既定では実際に使う部屋だけ返す。"""
    try:
        r = httpx.get(f"{settings.CHATWORK_API_BASE}/rooms",
                      headers=_headers(), timeout=TIMEOUT)
    except ChatworkError:
        raise
    except Exception as e:
        raise ChatworkError(f"Chatworkに繋がりませんでした（{type(e).__name__}）")
    rooms = _check(r) or []
    allow = _allow_list()
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
    if all_rooms:
        return out
    # 絞った結果が空なら、部屋名が変わったということ。黙って0件にすると
    # 送れなくなるので、そのときは全部返す
    picked = [x for x in out if _wanted(x, allow)]
    return picked or out


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


# ============================================================
# 状況確認シートの知らせ
# ============================================================
# シートに書き込んでも、相手が見に来るまで気づかれない。
# 書き込んだときだけチャットワークへ1行流して、見に行く合図にする。
# 送り先は「北田しずく(HAMU-ha)」。二人の部屋なので、どちらが
# 書いてももう一方に通知が飛ぶ。

_WORK_ROOM_HINTS = ("北田しずく", "HAMU-ha")
_work_room_cache: Optional[str] = None


def work_room() -> Optional[str]:
    """知らせを送る部屋。環境変数 CHATWORK_WORK_ROOM があればそれを使う。"""
    global _work_room_cache
    rid = os.environ.get("CHATWORK_WORK_ROOM", "").strip()
    if rid:
        return rid
    if _work_room_cache:
        return _work_room_cache
    try:
        for r in list_rooms(all_rooms=True):
            name = str(r.get("name") or "")
            if any(h in name for h in _WORK_ROOM_HINTS):
                _work_room_cache = str(r.get("room_id"))
                return _work_room_cache
    except Exception:
        return default_room()
    return default_room()


def work_sheet_url() -> str:
    """外注さんが開くシートのURL。"""
    url = os.environ.get("WORK_SHARE_URL", "").strip()
    if url:
        return url
    base = os.environ.get(
        "PUBLIC_SITE_URL",
        "https://misa-sep13.github.io/china-import-tool").rstrip("/")
    token = os.environ.get("KEEP_SHARE_TOKEN", "").strip()
    return f"{base}/work-public" + (f"?share={token}" if token else "")


def notify_work(title: str, lines: list) -> None:
    """状況確認シートの動きを知らせる。

    送れなくても画面の操作は止めない（知らせはおまけで、
    書き込みそのものは保存できているため）。
    """
    if not is_configured():
        return
    try:
        room = work_room()
        if not room:
            return
        body = "\n".join([f"[info][title]{title}[/title]"]
                         + [str(x) for x in lines if str(x).strip()]
                         + [work_sheet_url(), "[/info]"])
        send_message(room, body)
    except Exception:
        pass
