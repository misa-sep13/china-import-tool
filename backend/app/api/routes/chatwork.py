"""Chatworkの窓口。

画像作成指示書のWordを、外注さんのルームへボタン一つで送る。
トークンはサーバー側だけで持ち、画面には出さない。

送信は取り消しにくい（相手に通知が飛ぶ）ので、押す前に画面で
送り先とファイル名を確認させる作りにしてある。ここは送るだけ。
"""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services import chatwork

router = APIRouter(prefix="/chatwork", tags=["chatwork"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except chatwork.ChatworkError as e:
        # 権限やトークンの話はそのまま画面に出したいので文言を保つ
        raise HTTPException(status_code=502, detail=e.message)


@router.get("/status")
def status():
    """設定が入っているか。ボタンを出すかどうかの判断に使う。"""
    return {"configured": chatwork.is_configured(),
            "default_room_id": chatwork.default_room()}


@router.get("/rooms")
def rooms():
    """送り先の候補。画面の選択欄に出す。"""
    if not chatwork.is_configured():
        raise HTTPException(status_code=502,
                            detail="Chatworkのトークンが未設定です（CHATWORK_API_TOKEN）")
    return {"items": _call(chatwork.list_rooms),
            "default_room_id": chatwork.default_room()}


@router.post("/send-file")
async def send_file(room_id: str = Form(...), file: UploadFile = File(...),
                    message: str = Form("")):
    """ファイルを1つ送る。画像作成指示書のWordを想定している。"""
    content = await file.read()
    return _call(chatwork.send_file, room_id,
                 file.filename or "指示書.docx", content, message)
