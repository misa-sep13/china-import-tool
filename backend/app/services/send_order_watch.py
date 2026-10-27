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
        label = NOTIFY_STATES.get(state)

        # インボイスができたか。これが true なら箱の中身まで取れるので、
        # そのまま④へ進める。状態から推測せず、直接確かめる。
        # 出荷待ちになった後でインボイスができることがあるので、
        # 状態だけでなく、できたかどうかも覚えて見分ける
        ready = None
        if label and state in (7, 8):
            try:
                ready = bool(taotaro.send_order_boxes(int(sid)).get(
                    "boxes_ready"))
            except Exception as e:
                logger.warning(f"[send-order-watch] 箱の確認に失敗 {sid}: {e}")

        key = f"{state}R" if ready else str(state)
        now[sid] = key
        if first_time:
            continue                      # 初回は今の状態を覚えるだけ
        if str(before.get(sid)) == key:
            continue
        if not label:
            continue
        notices.append({
            "sid": sid,
            "sn": x.get("sn") or sid,
            "state": state,
            "label": label,
            "weight": x.get("count_weight"),
            "total": x.get("total_send_fee"),
            "boxes_ready": ready,
            # 出荷済みになると sn がそのまま追跡番号になる
            "carrier": x.get("delivery_name") or "",
            "tracking_url": x.get("tracking_url") or "",
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
        head = ("インボイスができました" if n.get("boxes_ready")
                else f"「{n['label']}」になりました")
        lines = [f"配送依頼 {n['sn']}　{head}"]
        if n["state"] in (7, 8):
            if n.get("total"):
                lines.append(f"金額: {n['total']} 元")
            if n.get("weight"):
                lines.append(f"重量: {n['weight']} kg")
        if n["state"] == 2:
            # 追跡番号は配送依頼番号（sn）そのもの
            if n.get("carrier"):
                lines.append(f"業者: {n['carrier']}")
            lines.append(f"追跡番号: {n['sn']}")
            lines.append("納品プランの⑤でAmazonに入れられます。")
        if n.get("boxes_ready"):
            lines.append("インボイスができています。"
                         "納品プランの④（箱の中身）まで進められます。")
        elif n["state"] == 8:
            lines.append("インボイスはまだできていません。"
                         "できたら④（箱の中身）に進めます。")
        elif n["state"] == 7:
            lines.append("支払うとインボイスができます。"
                         "そのあと納品プランの④（箱の中身）まで進めます。")
        lines.append(SITE_URL)
        title = "インボイス作成" if n.get("boxes_ready") else n["label"]
        body = "\n".join([f"[info][title]タオタロウ {title}[/title]"]
                         + lines + ["[/info]"])
        chatwork.send_message(room, body)

        # メッセージは自分の発言なので自分には通知が出ない。
        # 動く必要がある知らせはタスクにする（自分あてでも通知される）
        if n.get("boxes_ready"):
            try:
                chatwork.create_task(
                    room,
                    f"配送依頼 {n['sn']} インボイス作成。"
                    f"納品プランの④（箱の中身）まで進める")
            except Exception as e:
                logger.warning(f"[send-order-watch] タスクを作れません: {e}")
    except Exception as e:
        # 知らせはおまけ。落ちても巡回そのものは止めない
        logger.warning(f"[send-order-watch] 送れませんでした: {e}")
