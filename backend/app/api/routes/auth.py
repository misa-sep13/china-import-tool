from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.auth import auth_enabled, check_credentials, issue_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(data: LoginIn):
    if not auth_enabled():
        raise HTTPException(400, "ログインは設定されていません")
    role = check_credentials(data.username.strip(), data.password)
    if not role:
        raise HTTPException(401, "ユーザー名またはパスワードが違います")
    return {"token": issue_token(role), "role": role}


@router.get("/status")
def status():
    """ログイン画面を出す必要があるかどうか。パスワード未設定なら常に無効。"""
    return {"auth_enabled": auth_enabled()}
