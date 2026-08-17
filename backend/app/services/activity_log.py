"""影響の大きい操作を activity_logs へ記録するヘルパー。

呼び出し側で db.commit() する前提（他の変更と同じトランザクションでまとめてcommitされる）。
actor はミドルウェアが request.state.actor_role にセットしたもの
（認証が無効な間は "owner" 扱いにしておく＝今までどおり全部自分の操作として見える）。
"""
from fastapi import Request
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog


def get_actor(request: Request) -> str:
    return getattr(request.state, "actor_role", None) or "owner"


def log_activity(
    db: Session,
    request: Request,
    action: str,
    entity_type: str,
    entity_id=None,
    summary: str = "",
    sku: str | None = None,
):
    db.add(ActivityLog(
        actor=get_actor(request),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        sku=sku,
        summary=summary,
    ))
