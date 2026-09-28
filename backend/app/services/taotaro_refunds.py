"""タオタロウの配送依頼メールから、値引き（返金）の金額を拾って月ごとにまとめる。

配送依頼のメールの本文に、こう書かれていることがある。

    値引きした 170 元を返金させていただきます。 2.7kg 31/26/24

数えているのは「実際に返ってきた金額」で、請求書の合計とは別物。
どれだけ戻ってきているかを月ごとに見たい、という用途のもの。

メールは読むだけで、既読にも移動にもしない。
"""
import email
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.services import permit_mail

# 「値引きした 170 元を返金させていただきます」。数字は全角のこともある。
# 「170元」と続くことも、間に空白が入ることもあるので、どちらも拾う
_REFUND = re.compile(
    r"値引き(?:した|致しました|いたしました)?\s*([0-9０-９,，\.]+)\s*元")
# 追跡番号。どの便の返金かを添えるために拾う
_TRACK = re.compile(r"追跡番号[：:\s]*(?:\(\d+\))?\s*([A-Z0-9]{8,})")

_JST = timezone(timedelta(hours=9))


def _to_num(s: str) -> float:
    """全角の数字や区切りを直して数にする。"""
    z = str(s).translate(str.maketrans("０１２３４５６７８９，．", "0123456789,."))
    try:
        return float(z.replace(",", ""))
    except ValueError:
        return 0.0


def _body_text(msg) -> str:
    """本文を文字にする。HTMLしか無いメールはタグを落として使う。"""
    parts = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            raw = part.get_payload(decode=True) or b""
        except Exception:
            continue
        charset = part.get_content_charset() or "utf-8"
        for enc in (charset, "utf-8", "cp932", "iso-2022-jp"):
            try:
                text = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                text = ""
        if not text:
            continue
        if ctype == "text/html":
            text = re.sub(r"<[^>]+>", " ", text)
        parts.append(text)
    return "\n".join(parts)


def _sent_at(msg) -> datetime:
    """送られた日。取れなければ今日として扱う（月がずれるより落ちないほうを選ぶ）。"""
    try:
        d = email.utils.parsedate_to_datetime(msg.get("Date"))
        return d.astimezone(_JST) if d.tzinfo else d.replace(tzinfo=_JST)
    except Exception:
        return datetime.now(_JST)


def _find_folder(im, want: str) -> str:
    """読める名前でフォルダを探す。

    日本語のフォルダ名は符号化されているうえ、受信トレイの下にあると
    「INBOX.配送依頼」のような階層つきの名前になる。名前をそのまま比べると
    見つからないので、末尾の一段でも照合する。
    サーバーが返した名前（raw）をそのまま使って開く（組み立て直すと
    変形UTF-7の変換で取りこぼす）。
    """
    typ, boxes = im.list()
    exact, tail = None, None
    for b in boxes or []:
        line = b.decode(errors="replace") if isinstance(b, bytes) else str(b)
        raw = permit_mail.mailer._list_name(line)
        if not raw:
            continue
        label = permit_mail._utf7_decode(raw)
        if label == want:
            exact = raw
            break
        # 「INBOX.配送依頼」「INBOX/配送依頼」のどちらの区切りでも拾う
        last = re.split(r"[./]", label)[-1]
        if last == want and tail is None:
            tail = raw
    found = exact or tail
    if found:
        return found
    # 見つからなかったときは、何があったのかを伝える。名前が少し違うだけの
    # ことが多いので、一覧を添える
    names = []
    for b in boxes or []:
        line = b.decode(errors="replace") if isinstance(b, bytes) else str(b)
        raw = permit_mail.mailer._list_name(line)
        if raw:
            names.append(permit_mail._utf7_decode(raw))
    raise permit_mail.PermitMailError(
        f"フォルダ「{want}」が見つかりませんでした。"
        f"あるのは：{'、'.join(names[:30])}")


def collect(folder: str = "配送依頼", days: int = 365,
            cap: int = 2000) -> dict:
    """値引きの金額を拾って、月ごとにまとめる。読むだけ。"""
    im = permit_mail._connect()
    try:
        name = _find_folder(im, folder)
        if im.select(f'"{name}"', readonly=True)[0] != "OK":
            raise permit_mail.PermitMailError(
                f"フォルダ「{folder}」を開けませんでした")
        since = (datetime.now(_JST) - timedelta(days=max(1, days))
                 ).strftime("%d-%b-%Y")
        typ, data = im.search(None, "SINCE", since)
        if typ != "OK":
            raise permit_mail.PermitMailError("メールの検索に失敗しました")
        nums = (data[0] or b"").split()[-cap:]

        months = defaultdict(lambda: {"total": 0.0, "count": 0})
        rows = []
        scanned = 0
        for num in nums:
            try:
                typ, raw = im.fetch(num, "(RFC822)")
            except Exception:
                continue
            if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                continue
            msg = email.message_from_bytes(raw[0][1])
            scanned += 1
            text = _body_text(msg)
            hits = _REFUND.findall(text)
            if not hits:
                continue
            when = _sent_at(msg)
            key = when.strftime("%Y-%m")
            track = (_TRACK.search(text) or [None, ""])[1]
            for h in hits:
                amount = _to_num(h)
                if amount <= 0:
                    continue
                months[key]["total"] += amount
                months[key]["count"] += 1
                rows.append({
                    "month": key,
                    "date": when.strftime("%Y-%m-%d"),
                    "amount_cny": amount,
                    "tracking": track,
                    "subject": permit_mail._decode(msg.get("Subject")),
                })
    finally:
        try:
            im.logout()
        except Exception:
            pass

    out = [{"month": k, "total_cny": round(v["total"], 2), "count": v["count"]}
           for k, v in sorted(months.items())]
    return {
        "folder": folder,
        "days": days,
        "scanned": scanned,
        "months": out,
        "total_cny": round(sum(m["total_cny"] for m in out), 2),
        "count": sum(m["count"] for m in out),
        "rows": sorted(rows, key=lambda r: r["date"]),
    }
