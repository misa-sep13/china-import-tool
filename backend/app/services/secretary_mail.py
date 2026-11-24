"""請求のメールを拾って、振込待ちにする。

漏れるのは「メールが来た時点」と「振り込む時点」がずれるからで、
その間に忘れる。来た瞬間に期限付きで並べてしまえば、忘れようがなくなる。

やること:
  1. 登録した差出人から届いたメールの添付PDFを拾う
  2. 書類棚（import_permits）に原本を入れる。月次管理表からそのまま見られる
  3. 金額を読んで、支払期限を計算し、秘書に「振込待ち」として出す

くり返しの決まり（例：毎月のエジソン）と結び付けてある差出人は、
新しく立てずに、その月の実体に金額と原本を入れる。同じ仕事が
二重に並ぶのを避けるため。
"""
import calendar
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.import_permit import ImportPermit
from app.models.secretary import SecretaryRun, SecretarySender
from app.services import invoice_parse, permit_mail
from app.services import secretary as svc

logger = logging.getLogger("secretary_mail")


def _eom(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def due_date_for(sender: SecretarySender, arrived: date) -> date:
    """支払の期限。届いた日から決める。"""
    rule = sender.due_rule or "eom"
    day = max(1, min(int(sender.due_day or 10), 28))

    if rule == "eom":
        return _eom(arrived.year, arrived.month)
    if rule == "eom_next":
        y, m = svc.shift_month(arrived.year, arrived.month, 1)
        return _eom(y, m)
    if rule == "days":
        return arrived + timedelta(days=int(sender.due_day or 10))
    # day … 届いた月のその日。もう過ぎていれば翌月の同じ日
    want = date(arrived.year, arrived.month, day)
    if want < arrived:
        y, m = svc.shift_month(arrived.year, arrived.month, 1)
        want = date(y, m, min(day, calendar.monthrange(y, m)[1]))
    return want


def _amount(text: str):
    """請求書から請求額を読む。読めなければ None。

    読めなくても止めない。金額は確かめるための手がかりで、
    原本は書類棚に入っているので、画面で見れば分かる。
    """
    try:
        parsed = invoice_parse.parse_wholesale_invoice(text or "")
    except Exception:
        return None, ""
    total = parsed.get("total")
    if total is None and parsed.get("subtotal") is not None:
        total = parsed["subtotal"] + (parsed.get("tax") or 0)
    return (float(total) if total is not None else None), (parsed.get("issued") or "")


def _mail_date(value: str) -> date:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return svc.today_jst()


def fetch(db: Session, days: int = 45, folder: str = None) -> dict:
    """登録した差出人の請求書を取り込んで、振込待ちを立てる。"""
    senders = (db.query(SecretarySender)
               .filter(SecretarySender.active.is_(True)).all())
    if not senders:
        return {"added": 0, "skipped": 0, "items": [],
                "message": "請求元が登録されていません"}

    by_match = {s.match_from.strip().lower(): s for s in senders if s.match_from}
    stats = {}
    mails = permit_mail.scan_by_sender(list(by_match), days=days,
                                       folder=folder, stats=stats)

    # 同じ添付を二度入れない。書類棚の鍵（Message-ID＋添付名）で見分ける
    known = {(p.mail_message_id, p.filename) for p in
             db.query(ImportPermit.mail_message_id, ImportPermit.filename)
             .filter(ImportPermit.mail_message_id.isnot(None)).all()}

    added, skipped = [], 0
    for item in mails:
        sender = by_match.get(item["matched"])
        if not sender:
            continue
        key = (item["mail_message_id"], item["filename"])
        if key in known:
            skipped += 1
            continue
        known.add(key)

        arrived = _mail_date(item["mail_date"])
        amount, issued = _amount(item.get("text") or "")

        permit = ImportPermit(
            kind=sender.doc_kind or "wholesale",
            permit_date=issued or arrived.isoformat(),
            filename=item["filename"],
            size_bytes=item["size_bytes"],
            pdf=item["pdf"],
            source="mail",
            mail_message_id=item["mail_message_id"],
            mail_subject=item["mail_subject"],
            mail_from=item["mail_from"],
            mail_date=item["mail_date"],
            note=f"{sender.name} の請求書（秘書が取り込み）",
        )
        db.add(permit)
        db.flush()

        due = due_date_for(sender, arrived)
        run = _attach_or_create(db, sender, due, amount, permit, item)
        added.append({
            "sender": sender.name,
            "filename": item["filename"],
            "amount": amount,
            "due_date": due.isoformat(),
            "run_id": run.id,
            "permit_id": permit.id,
        })
        sender.last_found_at = svc.now_jst()

    db.commit()
    return {"added": len(added), "skipped": skipped, "items": added,
            "scanned": stats}


def _attach_or_create(db: Session, sender: SecretarySender, due: date,
                      amount, permit: ImportPermit, item: dict) -> SecretaryRun:
    """くり返しの決まりがあればその月の実体に入れる。無ければ1件立てる。"""
    period = svc.period_str(due.year, due.month)
    source_key = f"{item['mail_message_id']}|{item['filename']}"

    run = None
    if sender.task_id:
        run = (db.query(SecretaryRun)
               .filter(SecretaryRun.task_id == sender.task_id,
                       SecretaryRun.period == period,
                       SecretaryRun.status == "open")
               .order_by(SecretaryRun.id.asc())
               .first())

    if run is None:
        run = SecretaryRun(
            task_id=sender.task_id,
            title=f"{sender.name}の請求を振り込む",
            area=sender.area or "money",
            period=period,
            due_date=due,
            lead_days=sender.lead_days or 0,
            status="open",
            source="mail",
        )
        db.add(run)

    # 届いた請求のほうが確かなので、金額・期限・原本はこちらで上書きする。
    # 済みにしたものには触らない（上の絞り込みで open だけを拾っている）
    if amount is not None:
        run.amount = amount
    run.due_date = due
    run.period = period
    run.source = "mail"
    run.source_key = source_key
    run.permit_id = permit.id
    run.ref_url = f"#/accounting"
    db.flush()
    return run


# 聞き取りから。画面で足せるが、最初から入れておく
SEED_SENDERS = [
    dict(name="あざみ就労支援", match_from="azami@kounuma-hukusikai.or.jp",
         area="money", doc_kind="other", due_rule="day", due_day=10,
         lead_days=7, note="月初に請求メールが届く"),
    dict(name="エジソン", match_from="seikyu@edisonmama.com",
         area="money", doc_kind="wholesale", due_rule="eom", due_day=28,
         lead_days=10, note="月末締め翌月末払い"),
]


def seed_senders_if_empty(db: Session) -> int:
    """請求元が1件も無いときだけ入れる。くり返しの決まりとも結び付ける。"""
    if db.query(SecretarySender.id).first():
        return 0

    from app.models.secretary import SecretaryTask
    tasks = db.query(SecretaryTask).all()

    def find_task(word):
        hit = next((t for t in tasks if word in (t.title or "")), None)
        return hit.id if hit else None

    for row in SEED_SENDERS:
        db.add(SecretarySender(**row, task_id=find_task(
            "あざみ" if "あざみ" in row["name"] else "エジソン")))
    db.commit()
    return len(SEED_SENDERS)
