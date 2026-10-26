"""配送依頼の状態が変わったらChatworkへ知らせる。

支払いのお願いはメールで来るので、すぐに気づけず出荷が遅れていた。
メールを読まなくても、タオタロウのAPIに状態（7=お支払い待ち）が出ている
ので、そちらを見に行って変わった瞬間に流す。

前に見たときの状態は order_settings に JSON で持つ。テーブルを増やす
ほどのものではないし、消えても次の巡回で入り直る（初回は知らせない）。
"""
import json
import logging
from typing import Optional

from app.models.settings import OrderSettings
from app.services import chatwork, taotaro

logger = logging.getLogger(__name__)

# 知らせる状態。全部流すと「梱包作業中」まで毎回来て埋もれる。
# 支払いを自動にしてあるので、7（お支払い待ち）には止まらず
# 8（出荷待ち）に飛ぶ。インボイスができるのもこのとき
NOTIFY_STATES = {
    8: "出荷待ち",
    7: "お支払い待ち",
    2: "出荷済み",
}

SITE_URL = "https://www.yiwutaro.com/member/send-order"


def _load(row: Optional[OrderSettings]) -> dict:
    try:
        return json.loads(getattr(row, "send_order_states", "") or "{}")
    except Exception:
        return {}


def check_once(db) -> dict:
    """1回だけ見に行く。戻り値は知らせた件数（動作確認用）。"""
    if not taotaro.is_configured():
        return {"skipped": "タオタロウのトークンが未設定"}

    row = db.query(OrderSettings).first()
    if row is None:
        row = OrderSettings()
        db.add(row)
        db.commit()
        db.refresh(row)

    before = _load(row)
    first_time = not before

    now, notices = {}, []
    try:
        d = taotaro.list_send_orders(page=1, limit=50)
    except Exception as e:
        logger.warning(f"[send-order-watch] 一覧が取れません: {e}")
        return {"error": str(e)}

    for x in d.get("items") or []:
        sid = str(x.get("sid") or "")
        if not sid:
            continue
        state = int(x.get("state") or 0)
        now[sid] = state
        if first_time:
            continue                      # 初回は今の状態を覚えるだけ
        if before.get(sid) == state:
            continue
        label = NOTIFY_STATES.get(state)
        if not label:
            continue
        notices.append({
            "sid": sid,
            "sn": x.get("sn") or sid,
            "state": state,
            "label": label,
            "weight": x.get("count_weight"),
            "total": x.get("total_send_fee"),
        })

    for n in notices:
        _send(n)

    row.send_order_states = json.dumps(now, ensure_ascii=False)
    db.commit()
    return {"watched": len(now), "notified": len(notices),
            "first_time": first_time}


def _send(n: dict) -> None:
    if not chatwork.is_configured():
        return
    try:
        room = chatwork.alert_room()
        if not room:
            return
        lines = [f"配送依頼 {n['sn']}　が「{n['label']}」になりました"]
        if n["state"] in (7, 8):
            if n.get("total"):
                lines.append(f"金額: {n['total']} 元")
            if n.get("weight"):
                lines.append(f"重量: {n['weight']} kg")
        if n["state"] == 8:
            lines.append("インボイスができています。"
                         "納品プランの④（箱の中身）まで進められます。")
        elif n["state"] == 7:
            lines.append("支払うとインボイスができます。"
                         "そのあと納品プランの④（箱の中身）まで進めます。")
        lines.append(SITE_URL)
        body = "\n".join([f"[info][title]タオタロウ {n['label']}[/title]"]
                         + lines + ["[/info]"])
        chatwork.send_message(room, body)
    except Exception as e:
        # 知らせはおまけ。落ちても巡回そのものは止めない
        logger.warning(f"[send-order-watch] 送れませんでした: {e}")
