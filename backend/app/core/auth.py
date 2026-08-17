"""簡易ログイン（オーナー／外注さん1名）用の認証まわり。

このツールはもともと認証なしで運用してきた小規模な社内ツールのため、
本格的なユーザー管理システムは過剰。環境変数でオーナー・外注の
パスワードを1つずつ設定するだけの軽量な仕組みにしている。

- AUTH_OWNER_PASSWORD / AUTH_CONTRACTOR_PASSWORD が未設定の間は
  認証を一切要求しない（今までどおり動く）。設定して初めて有効になるので、
  デプロイしただけでは誰もロックアウトされない。
- AUTH_TOKEN_SECRET はトークン署名用の鍵。未設定でも動くが、
  本番では必ず固有の値を設定すること（省略時は再デプロイのたびに
  全員ログアウトされる簡易フォールバックを使う）。
- AUTH_SERVICE_TOKEN はGitHub Actionsの自動実行（売上同期・SEOチェック・
  月末在庫確定）用。ログイン画面からは使わない。

トークンには発行時点のパスワードの指紋(pwfp)を埋め込み、検証のたびに
「今の」パスワードから計算した指紋と突き合わせる。これにより
AUTH_CONTRACTOR_PASSWORD を変更した瞬間、有効期限内でも発行済みの
トークンが（ブックマークしてある分も含めて）すべて無効になる
＝契約終了時に確実に遮断できる。
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

_FALLBACK_SECRET = "china-import-tool-dev-secret-not-for-production"

# オーナーは毎回パスワードを打ちたくないという要望のため長め（実質「パスワードを
# 変えない限りずっと有効」）。本当の失効手段はTTLではなくパスワード変更＝pwfp不一致。
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 365  # 365日


def _secret() -> str:
    return os.environ.get("AUTH_TOKEN_SECRET") or _FALLBACK_SECRET


def _sign(payload_b64: str) -> str:
    return hmac.new(_secret().encode(), payload_b64.encode(), hashlib.sha256).hexdigest()


def _password_fingerprint(role: str) -> str:
    pw = os.environ.get(f"AUTH_{role.upper()}_PASSWORD") or ""
    return hashlib.sha256(pw.encode()).hexdigest()[:16]


def issue_token(role: str) -> str:
    payload = json.dumps({
        "role": role,
        "exp": int(time.time()) + _TOKEN_TTL_SECONDS,
        "pwfp": _password_fingerprint(role),
    })
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_token(token: str) -> Optional[dict]:
    if not token or "." not in token:
        return None
    payload_b64, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign(payload_b64), sig):
        return None
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    role = payload.get("role", "")
    if payload.get("pwfp") != _password_fingerprint(role):
        return None  # パスワードが変わった＝このトークンはもう無効
    return payload


def auth_enabled() -> bool:
    return bool(os.environ.get("AUTH_OWNER_PASSWORD"))


def check_credentials(username: str, password: str) -> Optional[str]:
    """ユーザー名・パスワードが正しければロール("owner"/"contractor")を返す。"""
    owner_pw = os.environ.get("AUTH_OWNER_PASSWORD")
    contractor_pw = os.environ.get("AUTH_CONTRACTOR_PASSWORD")
    if owner_pw and username == "owner" and hmac.compare_digest(password, owner_pw):
        return "owner"
    if contractor_pw and username == "contractor" and hmac.compare_digest(password, contractor_pw):
        return "contractor"
    return None


def check_service_token(token: str) -> bool:
    service_token = os.environ.get("AUTH_SERVICE_TOKEN")
    return bool(service_token) and hmac.compare_digest(token, service_token)
