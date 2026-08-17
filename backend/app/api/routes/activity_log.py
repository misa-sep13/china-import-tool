"""トップページの「更新履歴」パネル用API。

activity_logs（商品マスタの登録/更新/削除・在庫の直接変更など、このセッションで
新しく記録するようにした操作）に加えて、既存の在庫反映履歴（配送依頼・メーカー入荷）と
就労支援の入出庫履歴も同じ時系列に混ぜて返す。

すべての操作を網羅しているわけではない（このツールにある全エンドポイントに
記録を仕込むのは現実的ではないため）。特にリスクが大きい操作
（在庫の書き換え・マスタの登録/更新/削除）を優先して記録している。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.activity_log import ActivityLog
from app.models.inventory_reflection_log import InventoryReflectionLog
from app.models.welfare import WelfareInventoryMovement

router = APIRouter(prefix="/activity-log", tags=["activity-log"])

_ACTOR_LABEL = {"owner": "自分", "contractor": "外注さん", "service": "自動処理"}


@router.get("/recent")
def recent_activity(limit: int = Query(60, le=300), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 300))
    feed = []

    for r in db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit).all():
        feed.append({
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "actor": r.actor,
            "actor_label": _ACTOR_LABEL.get(r.actor, r.actor),
            "action": r.action,
            "entity_type": r.entity_type,
            "sku": r.sku,
            "summary": r.summary,
            "source": "activity_log",
        })

    for r in db.query(InventoryReflectionLog).order_by(InventoryReflectionLog.created_at.desc()).limit(limit).all():
        feed.append({
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "actor": None,
            "actor_label": None,
            "action": "stock_change",
            "entity_type": "rakuten_stock",
            "sku": r.sku,
            "summary": f"{r.source_label or r.source}: {r.name or r.sku} 在庫 {r.stock_before}→{r.stock_after}"
                       + (f"（{r.source_ref}）" if r.source_ref else ""),
            "source": "inventory_reflection_log",
        })

    for r in db.query(WelfareInventoryMovement).order_by(WelfareInventoryMovement.created_at.desc()).limit(limit).all():
        label = {"import": "荷受け反映", "withdraw": "出庫", "adjust": "残量修正"}.get(r.movement_type, r.movement_type)
        feed.append({
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "actor": None,
            "actor_label": None,
            "action": r.movement_type,
            "entity_type": "welfare_inventory",
            "sku": r.sku,
            "summary": f"就労支援 {label}: {r.sku or r.name_cn or ''} 数量{r.qty:+d}" if r.qty else f"就労支援 {label}: {r.sku or r.name_cn or ''}",
            "source": "welfare_movement",
        })

    feed = [f for f in feed if f["created_at"]]
    feed.sort(key=lambda f: f["created_at"], reverse=True)
    return {"items": feed[:limit]}
