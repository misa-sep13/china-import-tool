"""毎朝のLINE。今日やることと、遅れているものを1通にまとめて送る。

何通も送らない。鳴りすぎると見なくなって、結局いつもの忘れ方に戻るため、
1日1通だけにしてある。やることが無い日は既定では送らない。

トークンはそのアカウントとして送れる権限そのものなので、ブラウザには
渡さずここで持つ（Chatworkと同じ扱い）。
"""
import logging
from datetime import date, datetime

import httpx

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.secretary import SecretaryNotify
from app.services import secretary as svc

logger = logging.getLogger("secretary_line")

PUSH_URL = "https://api.line.me/v2/bot/message/push"
TIMEOUT = 30
# LINEの1通の上限は5000字。超えると丸ごと弾かれるので手前で切る
MAX_CHARS = 4500


class LineError(Exception):
    """画面にそのまま出せる日本語のエラー。"""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.message = message
        self.status = status


def is_configured() -> bool:
    return bool(settings.LINE_CHANNEL_TOKEN and settings.LINE_TO)


def push(text: str, to: str = None) -> dict:
    """1通送る。"""
    if not settings.LINE_CHANNEL_TOKEN:
        raise LineError("LINEのトークンが未設定です（LINE_CHANNEL_TOKEN）")
    target = to or settings.LINE_TO
    if not target:
        raise LineError("LINEの送り先が未設定です（LINE_TO）")

    body = text if len(text) <= MAX_CHARS else text[:MAX_CHARS - 20] + "\n…（長いので省略）"
    try:
        r = httpx.post(
            PUSH_URL, timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {settings.LINE_CHANNEL_TOKEN}",
                     "Content-Type": "application/json"},
            json={"to": target, "messages": [{"type": "text", "text": body}]},
        )
    except Exception as e:
        raise LineError(f"LINEに繋がりませんでした（{type(e).__name__}）")

    if r.status_code == 401:
        raise LineError("LINEのトークンが通りませんでした", status=401)
    if r.status_code == 403:
        raise LineError("このトークンでは送れません（送り先がお友だちか確認してください）",
                        status=403)
    if r.status_code == 429:
        raise LineError("LINEの送信数の上限に達しました（無料枠を使い切っています）",
                        status=429)
    if r.status_code >= 400:
        detail = ""
        try:
            detail = r.json().get("message") or ""
        except Exception:
            detail = (r.text or "")[:120]
        raise LineError(f"LINEが受け付けませんでした（{r.status_code} {detail}）",
                        status=r.status_code)
    return {"ok": True}


def _yen(n) -> str:
    return f"¥{int(round(n)):,}" if n is not None else ""


def build_message(db: Session, today: date = None, ahead_days: int = 0) -> str:
    """送る文面を組み立てる。無ければ空で返す。

    並びは画面と同じで、遅れているものが先。電話の画面で縦に読むので、
    1件1行を崩さない。
    """
    today = today or svc.today_jst()
    svc.ensure_runs(db, today)

    from app.models.secretary import SecretaryRun
    rows = (db.query(SecretaryRun)
            .filter(SecretaryRun.status == "open")
            .order_by(SecretaryRun.due_date.asc(), SecretaryRun.id.asc())
            .all())
    limit = today.toordinal() + max(0, ahead_days)
    rows = [r for r in rows if svc.visible_from(r).toordinal() <= limit]
    if not rows:
        return ""

    late = [r for r in rows if r.due_date < today]
    rest = [r for r in rows if r.due_date >= today]

    def line(r):
        head = f"・{r.title}"
        bits = []
        if r.target_period:
            bits.append(f"{int(r.target_period[5:7])}月分")
        if r.amount is not None:
            bits.append(_yen(r.amount))
        gap = (r.due_date - today).days
        if gap < 0:
            bits.append(f"{-gap}日 過ぎています")
        elif gap == 0:
            bits.append("今日まで")
        elif gap == 1:
            bits.append("明日まで")
        else:
            bits.append(f"あと{gap}日")
        return head + "（" + "・".join(bits) + "）"

    out = [f"おはようございます。{today.month}月{today.day}日のやることです。", ""]
    if late:
        out.append(f"■ 期限を過ぎています（{len(late)}件）")
        out += [line(r) for r in late]
        out.append("")
    if rest:
        out.append(f"■ これから（{len(rest)}件）")
        out += [line(r) for r in rest]
    return "\n".join(out).strip()


def get_or_create_settings(db: Session) -> SecretaryNotify:
    row = db.query(SecretaryNotify).filter(SecretaryNotify.id == 1).first()
    if not row:
        row = SecretaryNotify(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def send_now(db: Session, force: bool = False) -> dict:
    """今の内容で1通送る。force なら、やることが無くても送る（試し送り用）。"""
    conf = get_or_create_settings(db)
    text = build_message(db, ahead_days=conf.ahead_days or 0)
    if not text:
        if not force:
            return {"sent": False, "reason": "やることがありません"}
        text = "おはようございます。今日やることはありません。"

    push(text)
    now = datetime.now(svc.JST)
    conf.last_sent_on = now.date().isoformat()
    conf.last_sent_at = now
    conf.last_error = None
    db.commit()
    return {"sent": True, "text": text}


def daily_tick(db: Session) -> dict:
    """スケジューラから1分ごとに呼ばれる。送る時刻になっていれば1通だけ送る。

    送ったかどうかは日本時間の日付で覚えるので、再起動しても二度送らない。
    """
    conf = get_or_create_settings(db)
    if not conf.enabled:
        return {"skipped": "止めています"}
    # 画面を一度も開いていなくても動くように、ここでも初期登録を見る。
    # スケジューラは人の操作を待たずに走るため
    svc.seed_if_empty(db)
    from app.services import secretary_mail as _sm
    _sm.seed_senders_if_empty(db)
    if not is_configured():
        return {"skipped": "LINEが未設定です"}

    now = datetime.now(svc.JST)
    if now.hour < (conf.hour or 7):
        return {"skipped": "まだ時刻前です"}
    if conf.last_sent_on == now.date().isoformat():
        return {"skipped": "今日はもう送りました"}

    # 先に請求メールを見る。届いた請求をその朝の知らせに間に合わせるため
    fetched = None
    if conf.fetch_mail:
        try:
            from app.services import secretary_mail
            fetched = secretary_mail.fetch(db, days=45)
        except Exception as e:
            # メールが取れなくても知らせは出す。取れなかったことは控えに残す
            logger.warning(f"[secretary] 請求メールの取り込みでエラー: {e}")
            conf.last_error = f"請求メール: {e}"[:300]
            db.commit()

    text = build_message(db, today=now.date(), ahead_days=conf.ahead_days or 0)
    if not text and not conf.send_when_empty:
        # 何も無い日は送らないが、今日はもう見たことにしておく
        conf.last_sent_on = now.date().isoformat()
        db.commit()
        return {"skipped": "やることがありません"}
    if not text:
        text = "おはようございます。今日やることはありません。"

    try:
        push(text)
    except LineError as e:
        conf.last_error = e.message[:300]
        db.commit()
        return {"error": e.message}

    conf.last_sent_on = now.date().isoformat()
    conf.last_sent_at = now
    conf.last_error = None
    db.commit()
    return {"sent": True, "fetched": (fetched or {}).get("added", 0),
            "chars": len(text)}
