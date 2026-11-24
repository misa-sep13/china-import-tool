"""タオタロウから届く動画を、チャットワークの北田しずくさんへ流す。

メールに添付で届いた動画を、いちど落として貼り直していた。
届いたら自動で送る。人がするのは中身を見ることだけにする。

同じ動画を二度送らないよう、見たメールは Message-ID で控える。
添付が無かったメールも控えるので、次からは中身を落とさずに済む
（動画は1通で数MBある。毎回落とすと通信量が無駄になる）。
"""
import logging

from sqlalchemy.orm import Session

from app.services import chatwork, permit_mail
from app.services import secretary as svc
from app.models.secretary import SecretaryForward

logger = logging.getLogger("taotaro_video")

KIND = "taotaro_video"
# 動画が届く差出人。変えたいときは環境変数 TAOTARO_VIDEO_FROM
DEFAULT_FROM = "service@yiwutaro.com"


def sender_address() -> str:
    import os
    return (os.environ.get("TAOTARO_VIDEO_FROM") or DEFAULT_FROM).strip().lower()


def _known_ids(db: Session) -> set:
    return {x[0] for x in
            db.query(SecretaryForward.mail_message_id)
            .filter(SecretaryForward.kind == KIND).all() if x[0]}


def _body(item: dict, filename: str) -> str:
    """チャットワークに出す本文。件名に動画のIDが入っているので、そのまま載せる。"""
    subject = (item.get("mail_subject") or "").strip()
    lines = ["タオタロウから動画が届きました。"]
    if subject:
        lines.append(subject)
    lines.append(filename)
    return "\n".join(lines)


def fetch_and_forward(db: Session, days: int = 14, folder: str = None,
                      room_id: str = None) -> dict:
    """届いた動画をチャットワークへ送る。何度呼んでも同じものは送らない。"""
    if not chatwork.is_configured():
        return {"sent": 0, "skipped": 0,
                "message": "Chatworkのトークンが未設定です"}

    room = room_id or chatwork.work_room()
    if not room:
        return {"sent": 0, "skipped": 0,
                "message": "送り先の部屋が見つかりませんでした（北田しずく）"}

    stats = {}
    mails = permit_mail.scan_new_from(
        [sender_address()], _known_ids(db), permit_mail.VIDEO_EXTS,
        days=days, folder=folder, stats=stats)

    sent, failed, skipped = [], [], 0
    for item in mails:
        base = dict(
            kind=KIND,
            mail_message_id=item["mail_message_id"],
            mail_subject=item["mail_subject"],
            mail_from=item["mail_from"],
            mail_date=item["mail_date"],
            room_id=str(room),
        )
        videos = item.get("files") or []
        if not videos:
            # 動画の付いていないメール。見たことだけ残して次から飛ばす
            db.add(SecretaryForward(**base, status="none"))
            skipped += 1
            continue

        for f in videos:
            row = SecretaryForward(**base, filename=f["filename"],
                                   size_bytes=f["size_bytes"])
            if f["size_bytes"] > chatwork.MAX_FILE_BYTES:
                # 上限を超える動画。送れないことを本文だけで知らせる。
                # 黙って飛ばすと、届いたこと自体に気づけない
                mb = f["size_bytes"] / 1024 / 1024
                row.status = "too_large"
                row.error = f"{mb:.1f}MB（チャットワークの上限5MB）"
                try:
                    chatwork.send_message(str(room), (
                        f"タオタロウから動画が届きましたが、"
                        f"大きすぎて送れませんでした（{mb:.1f}MB）。\n"
                        f"{item.get('mail_subject') or ''}\n"
                        f"{f['filename']}\n"
                        "お手数ですが、こちらから直接お送りします。"))
                except chatwork.ChatworkError as e:
                    row.error = f"{row.error}／知らせも送れず: {e.message}"[:300]
                failed.append({"filename": f["filename"],
                               "reason": row.error})
            else:
                try:
                    chatwork.send_file(str(room), f["filename"], f["content"],
                                       message=_body(item, f["filename"]))
                    row.status = "sent"
                    row.sent_at = svc.now_jst()
                    sent.append({"filename": f["filename"],
                                 "size_bytes": f["size_bytes"]})
                except chatwork.ChatworkError as e:
                    # 失敗したものは控えに残すが、status=error なので
                    # 次に走ったときにもう一度試す（下の _known_ids で
                    # 拾われないよう、Message-IDは入れない）
                    row.status = "error"
                    row.error = e.message[:300]
                    row.mail_message_id = None
                    failed.append({"filename": f["filename"],
                                   "reason": e.message})
            db.add(row)

    db.commit()
    return {"sent": len(sent), "failed": len(failed), "skipped": skipped,
            "items": sent, "errors": failed[:5], "room_id": str(room),
            "scanned": stats}


def tick(db: Session) -> dict:
    """スケジューラから呼ばれる。短い窓で見に行く。"""
    try:
        return fetch_and_forward(db, days=7)
    except permit_mail.PermitMailError as e:
        logger.warning(f"[taotaro_video] メールを見に行けませんでした: {e}")
        return {"error": str(e)}
