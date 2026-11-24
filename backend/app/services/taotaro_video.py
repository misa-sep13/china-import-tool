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
from app.models.secretary import SecretaryForward, SecretaryVideo

logger = logging.getLogger("taotaro_video")

KIND = "taotaro_video"
# ツールが預かる上限。これを超えるものはDBに入れずに、
# 届いたことだけ知らせる（動画の実体はDBに入るので、際限なく
# 太らせない）。タオタロウの動画は10MB前後なので十分に余裕がある
MAX_STORE_BYTES = 25 * 1024 * 1024
# 預かった動画を残しておく日数。過ぎたら中身だけ消す（記録は残す）
KEEP_DAYS = 180
# 動画が届く差出人。変えたいときは環境変数 TAOTARO_VIDEO_FROM
DEFAULT_FROM = "service@yiwutaro.com"


def sender_address() -> str:
    import os
    return (os.environ.get("TAOTARO_VIDEO_FROM") or DEFAULT_FROM).strip().lower()


def folder() -> str:
    """見に行くフォルダ。既定は全フォルダ。

    届いたメールは受信トレイに置きっぱなしにならない（ご自身で
    「動画撮影」フォルダへ移している）。受信トレイだけ見ていると、
    移したあとのものを見つけられない。
    見出しだけ先に読む作りなので、全フォルダでも重くならない。
    """
    import os
    return (os.environ.get("TAOTARO_VIDEO_FOLDER") or permit_mail.ALL).strip()


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


def public_base() -> str:
    """動画のURLを組み立てる先。"""
    import os
    return (os.environ.get("PUBLIC_API_URL")
            or "https://china-import-tool.onrender.com").rstrip("/")


def _via_link(db: Session, row, item: dict, f: dict, room,
              sent: list, failed: list):
    """大きい動画をツールが預かって、URLで渡す。

    チャットワークは1ファイル5MBまでで、タオタロウの動画はたいてい
    超える。外注さんにログインは渡せないので、URLに入れた合言葉だけで
    開けるようにする（合言葉は動画ごとに違う長いランダム文字列）。
    """
    import secrets

    mb = f["size_bytes"] / 1024 / 1024
    video = SecretaryVideo(
        token=secrets.token_urlsafe(24),
        filename=f["filename"],
        content_type=chatwork.content_type_of(f["filename"]),
        size_bytes=f["size_bytes"],
        content=f["content"],
    )
    db.add(video)
    db.flush()

    url = f"{public_base()}/api/secretary/video/{video.token}"
    try:
        chatwork.send_message(str(room), (
            f"タオタロウから動画が届きました。\n"
            f"{item.get('mail_subject') or ''}\n"
            f"{f['filename']}（{mb:.1f}MB）\n"
            f"大きいのでリンクでお送りします。\n{url}"))
    except chatwork.ChatworkError as e:
        # 預かったことは残す。送り直せるように失敗として数える
        db.delete(video)
        row.status = "error"
        row.error = e.message[:300]
        row.mail_message_id = None
        failed.append({"filename": f["filename"], "reason": e.message})
        return

    row.status = "link"
    row.error = None          # 作ったときに入れておいた「処理の途中です」を消す
    row.drive_url = url
    row.sent_at = svc.now_jst()
    video.forward_id = row.id
    sent.append({"filename": f["filename"], "size_bytes": f["size_bytes"],
                 "url": url})


def _too_large(row, item: dict, f: dict, room, failed: list, why: str):
    """ドライブが使えないとき。届いたことだけでも知らせる。

    黙って飛ばすと、動画が来たこと自体に気づけない。
    """
    mb = f["size_bytes"] / 1024 / 1024
    row.status = "too_large"
    row.error = f"{mb:.1f}MB（チャットワークの上限5MB）／{why}"[:300]
    try:
        chatwork.send_message(str(room), (
            f"タオタロウから動画が届きましたが、"
            f"大きすぎて送れませんでした（{mb:.1f}MB）。\n"
            f"{item.get('mail_subject') or ''}\n"
            f"{f['filename']}\n"
            "お手数ですが、こちらから直接お送りします。"))
    except chatwork.ChatworkError as e:
        row.error = f"{row.error}／知らせも送れず: {e.message}"[:300]
    failed.append({"filename": f["filename"], "reason": row.error})


def peek(db: Session, days: int = 14, in_folder: str = None) -> dict:
    """見るだけ。送らないし、何も残さない。

    うまくいかないときに、メールを落とすところで困っているのか、
    送るところで困っているのかを切り分けるため。
    """
    stats = {}
    found = []
    for item in permit_mail.scan_new_from(
            [sender_address()], _known_ids(db), permit_mail.VIDEO_EXTS,
            days=days, folder=in_folder or folder(), stats=stats,
            headers_only=True):
        found.append({"mail_date": item["mail_date"],
                      "mail_subject": item["mail_subject"],
                      "mail_bytes": item.get("mail_bytes") or 0})
    return {"found": found, "scanned": stats}


def fetch_and_forward(db: Session, days: int = 14, in_folder: str = None,
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
        days=days, folder=in_folder or folder(), stats=stats)

    sent, failed, skipped = [], [], 0
    for item in mails:
        # 1通ずつ確定させる。途中で落ちても、そこまでは残る
        base = dict(
            kind=KIND,
            mail_message_id=item["mail_message_id"],
            mail_subject=item["mail_subject"],
            mail_from=item["mail_from"],
            mail_date=item["mail_date"],
            room_id=str(room),
        )
        if item.get("oversize"):
            # 丸ごと読むとサーバーが落ちる大きさ。中身は取りに行っていない
            mb = item["oversize"] / 1024 / 1024
            db.add(SecretaryForward(
                **base, status="too_large",
                error=f"メールが{mb:.0f}MBあり、開けませんでした"))
            db.commit()
            try:
                chatwork.send_message(str(room), "\n".join([
                    f"タオタロウから動画が届きましたが、メールが大きすぎて"
                    f"開けませんでした（{mb:.0f}MB）。",
                    item.get("mail_subject") or "",
                    "お手数ですが、こちらから直接お送りします。",
                ]))
            except chatwork.ChatworkError:
                pass
            failed.append({"filename": item.get("mail_subject") or "",
                           "reason": f"メールが{mb:.0f}MB"})
            continue

        videos = item.get("files") or []
        if not videos:
            # 動画の付いていないメール。見たことだけ残して次から飛ばす
            db.add(SecretaryForward(**base, status="none"))
            db.commit()
            skipped += 1
            continue

        for f in videos:
            row = SecretaryForward(**base, filename=f["filename"],
                                   size_bytes=f["size_bytes"],
                                   status="error",
                                   error="処理の途中です")
            db.add(row)
            # ここでいったん確定させる。この先で落ちても、どこまで進んだかが残る。
            # Message-ID はまだ入っているが、status=error なので画面から送り直せる
            db.commit()
            if f["size_bytes"] > chatwork.MAX_FILE_BYTES:
                # チャットワークに載らない大きさ。預かってリンクを送る。
                # タオタロウの動画は5MB超のほうが多いので、ここが通らないと
                # 半分以上が手作業のまま残る
                if f["size_bytes"] > MAX_STORE_BYTES:
                    _too_large(row, item, f, room, failed,
                               f"{MAX_STORE_BYTES // 1024 // 1024}MBを超えています")
                else:
                    _via_link(db, row, item, f, room, sent, failed)
            else:
                try:
                    row.error = None
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

        # 動画の中身を抱えたまま次へ進まない。1通ごとに確定して手放す
        db.commit()
        for f in (item.get("files") or []):
            f["content"] = None

    return {"sent": len(sent), "failed": len(failed), "skipped": skipped,
            "items": sent, "errors": failed[:5], "room_id": str(room),
            "scanned": stats}


def drop_old_videos(db: Session, days: int = KEEP_DAYS) -> int:
    """古い動画の中身を消す。記録とURLは残すが、開くと空になる。

    動画の実体をDBに持つので、置きっぱなしだと際限なく太る。
    半年も経てば確認は済んでいる。
    """
    from datetime import timedelta
    limit = svc.now_jst() - timedelta(days=max(1, days))
    rows = (db.query(SecretaryVideo)
            .filter(SecretaryVideo.created_at < limit)
            .filter(SecretaryVideo.content.isnot(None)).all())
    for r in rows:
        r.content = None
    if rows:
        db.commit()
    return len(rows)


def tick(db: Session) -> dict:
    """スケジューラから呼ばれる。短い窓で見に行く。"""
    try:
        drop_old_videos(db)
        return fetch_and_forward(db, days=7)
    except permit_mail.PermitMailError as e:
        logger.warning(f"[taotaro_video] メールを見に行けませんでした: {e}")
        return {"error": str(e)}
