"""輸入許可書を、卸発注で使っているメールから拾ってくる。

通関業者からの許可書は毎回メールに埋もれてしまい、税理士へ渡すときに
探し直すことになっていた。受信箱を見て、輸入許可書のPDFだけを
ツールへ入れる。

差出人や件名では絞らない。通関業者が変わったり件名が変わったりすると
その時点で拾えなくなるため。添付PDFの中身を見て「輸入許可通知書」の
体裁かどうかで判断する。請求書などを誤って取り込まない代わりに、
どの業者から来ても拾える。
"""
import email
import email.utils
import imaplib
import io
import os
import re
import ssl
from datetime import datetime, timedelta
from email.header import decode_header, make_header

from app.services import mailer

# 既定の見に行き先。画面から選べるので、ふだんはこのままでよい
FOLDER = os.environ.get("IMAP_PERMIT_FOLDER", "INBOX")
# 1フォルダで見るメールの上限。多すぎると取り込みに時間がかかりRenderが切る
MAX_MESSAGES = 400
# 「すべてのフォルダ」を指定したときの1フォルダあたりの上限。
# 受信トレイが数千通あるので、全部見に行くと終わらない
MAX_MESSAGES_ALL = 150
ALL = "*"

# 許可書が入っているはずのないフォルダ。全部見るときに飛ばす
_SKIP_ATTRS = ("\\noselect", "\\trash", "\\junk", "\\drafts", "\\sent", "\\all")
_SKIP_WORDS = ("ごみ箱", "迷惑", "下書き", "送信済", "アーカイブ",
               "trash", "junk", "spam", "draft", "sent", "archive")


class PermitMailError(Exception):
    """画面にそのまま出せる日本語のエラー。"""


def _decode(value) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _pdf_text(content: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        # 画像だけのPDFや壊れたPDFはここに来る。取り込み自体は続ける
        return ""


# 輸入許可書かどうかの判定。通関業者ごとに体裁が少し違うので、
# どれか1つでも当たれば許可書とみなす
_MARKERS = ("輸入許可通知書", "輸入申告事項登録", "許可年月日", "納税額合計")


def looks_like_permit(text: str) -> bool:
    if not text:
        return False
    # 1つだけだと、請求書に「許可年月日」と書いてあるだけで拾ってしまう
    return sum(1 for m in _MARKERS if m in text) >= 2


def _find(pattern, text, cast=str, default=None):
    m = re.search(pattern, text)
    if not m:
        return default
    try:
        return cast(m.group(1).replace(",", "").strip())
    except Exception:
        return default


def _permit_date(text: str) -> str:
    """許可年月日。西暦・和暦のどちらでも拾えるようにする。"""
    m = re.search(r"許可年月日\s*[:：]?\s*(\d{4})[/\-年\.](\d{1,2})[/\-月\.](\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"許可年月日\s*[:：]?\s*令和\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})", text)
    if m:
        return f"{2018 + int(m.group(1))}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def parse_permit_pdf(content: bytes) -> dict:
    """許可書PDFから金額などを読み取る。読めない項目は0や空で返す。

    仕入管理の取り込みと同じ読み方に揃えてある。ここで読めた値は
    一覧に出して見分けるためのもので、原価の按分はこれまでどおり
    仕入管理側の解析結果を使う（二重に持って食い違わせない）。
    """
    text = _pdf_text(content)
    total = _find(r"納税額合計\s*[\\¥￥]?\s*([\d,]+)", text,
                  lambda x: int(x.replace(",", "")), 0)
    duty = _find(r"関税\s*[\\¥￥]\s*([\d,]+)", text,
                 lambda x: int(x.replace(",", "")), 0)
    ctax = _find(r"消費税\s*[\\¥￥]\s*([\d,]+)", text,
                 lambda x: int(x.replace(",", "")), 0)
    ltax = _find(r"地方消費税\s*[\\¥￥]\s*([\d,]+)", text,
                 lambda x: int(x.replace(",", "")), 0)
    return {
        "is_permit": looks_like_permit(text),
        "permit_no": _find(r"申告番号\s+([\d\s]+)", text,
                           lambda x: x.replace(" ", ""), "") or "",
        "permit_date": _permit_date(text),
        "permit_cny": _find(
            r"仕入書価格\s+[A-Z]\s+-\s+CIF\s+-\s+CNY\s+-\s+([\d,\.]+)",
            text, float, 0.0) or 0.0,
        "exchange_rate": _find(r"通貨レート\s+CNY\s*-\s*([\d,\.]+)",
                               text, float, 0.0) or 0.0,
        "total_tax": total or (duty + ctax + ltax),
        "customs_duty": duty,
        "consumption_tax": ctax,
        "local_consumption_tax": ltax,
    }


def _connect():
    c = mailer.config()
    if not c["imap_host"] or not c["user"] or not c["password"]:
        raise PermitMailError(
            "メールの設定がありません（IMAP_HOST / SMTP_USER / SMTP_PASSWORD）")
    try:
        im = imaplib.IMAP4_SSL(c["imap_host"], c["imap_port"],
                               ssl_context=ssl.create_default_context(),
                               timeout=60)
    except Exception as e:
        raise PermitMailError(
            f"メールサーバーに繋がりませんでした（{type(e).__name__}）")

    # メールソフト側が「暗号化されたパスワード認証」になっているサーバーだと、
    # 通常のログインを拒むことがある。その場合はCRAM-MD5で入り直す。
    # どちらもSSLの中なので、通信そのものは暗号化されている
    try:
        im.login(c["user"], c["password"])
    except Exception as first:
        try:
            im.login_cram_md5(c["user"], c["password"])
        except Exception:
            raise PermitMailError(
                f"メールにログインできませんでした（{first}）。"
                "IMAP_HOST とユーザー名・パスワードをご確認ください")
    return im


def _utf7_decode(name: str) -> str:
    """IMAPのフォルダ名を日本語に戻す。

    IMAPは「変形UTF-7」という古い方式で日本語のフォルダ名を持つ。
    そのまま画面に出すと &ZgSMTA- のような文字列になって選べない。
    """
    out, i = [], 0
    while i < len(name):
        if name[i] != "&":
            out.append(name[i])
            i += 1
            continue
        j = name.find("-", i)
        if j < 0:
            out.append(name[i])
            i += 1
            continue
        chunk = name[i + 1:j]
        if not chunk:
            out.append("&")                     # &- は & そのもの
        else:
            try:
                out.append(("+" + chunk.replace(",", "/") + "-")
                           .encode("ascii").decode("utf-7"))
            except Exception:
                out.append(name[i:j + 1])       # 読めなければそのまま出す
        i = j + 1
    return "".join(out)


def list_folders():
    """メールのフォルダ一覧。画面で選んでもらうため。

    選択に使う名前（raw）は、サーバーが返したものをそのまま持つ。
    こちらで組み立て直すと、変形UTF-7の変換で取りこぼす。
    """
    im = _connect()
    try:
        typ, boxes = im.list()
        if typ != "OK":
            raise PermitMailError("フォルダの一覧を取得できませんでした")
        out = []
        for b in boxes or []:
            line = b.decode(errors="replace") if isinstance(b, bytes) else str(b)
            raw = mailer._list_name(line)
            if not raw:
                continue
            label = _utf7_decode(raw)
            attrs = line[:line.find(")") + 1].lower()
            skip = (any(a in attrs for a in _SKIP_ATTRS)
                    or any(w in label.lower() for w in _SKIP_WORDS))
            out.append({"raw": raw, "label": label, "skip": skip})
        return out
    finally:
        try:
            im.logout()
        except Exception:
            pass


def _targets(im, folder):
    """見に行くフォルダを決める。"""
    if folder and folder != ALL:
        return [folder]
    if folder != ALL:
        return [FOLDER]
    typ, boxes = im.list()
    out = []
    for b in boxes or []:
        line = b.decode(errors="replace") if isinstance(b, bytes) else str(b)
        raw = mailer._list_name(line)
        if not raw:
            continue
        label = _utf7_decode(raw).lower()
        attrs = line[:line.find(")") + 1].lower()
        if any(a in attrs for a in _SKIP_ATTRS) or any(w in label for w in _SKIP_WORDS):
            continue
        out.append(raw)
    return out or [FOLDER]


def _open(im, folder, readonly=True):
    if im.select(f'"{folder}"', readonly=readonly)[0] != "OK":
        raise PermitMailError(
            f"フォルダを開けませんでした（{_utf7_decode(folder)}）")


def _recent_nums(im, days: int, cap: int = MAX_MESSAGES):
    since = (datetime.now() - timedelta(days=max(1, days))).strftime("%d-%b-%Y")
    typ, data = im.search(None, "SINCE", since)
    if typ != "OK":
        raise PermitMailError("メールの検索に失敗しました")
    # 新しいものから見る。古いぶんは日数を伸ばして取り直せる
    return (data[0] or b"").split()[-cap:][::-1]


def _pdf_attachments(msg):
    """PDFの添付だけを取り出す。

    拡張子だけで見ると、業者によって application/octet-stream で
    送られてきたものを落としてしまう。中身の先頭が %PDF- かどうかも見る。
    """
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        name = _decode(part.get_filename())
        ctype = (part.get_content_type() or "").lower()
        if not name and ctype != "application/pdf":
            continue
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            continue
        if not data:
            continue
        if not (name.lower().endswith(".pdf") or ctype == "application/pdf"
                or data[:5] == b"%PDF-"):
            continue
        yield (name or "permit.pdf"), data


def _headers(msg):
    mail_date = ""
    try:
        dt = email.utils.parsedate_to_datetime(msg.get("Date"))
        mail_date = dt.strftime("%Y-%m-%d") if dt else ""
    except Exception:
        pass
    return {
        "subject": _decode(msg.get("Subject")),
        "from": _decode(msg.get("From")),
        "message_id": (msg.get("Message-ID") or "").strip(),
        "date": mail_date,
    }


def _fetch_message(im, num, prefilter=True):
    """1通ぶんを取る。添付が無さそうなものは構造だけ見て飛ばす。

    全文を落とすと通信量が無駄なので、先に BODYSTRUCTURE を見る。
    """
    try:
        if prefilter:
            typ, st = im.fetch(num, "(BODYSTRUCTURE)")
            if typ != "OK":
                return None
            blob = b" ".join(x for x in st if isinstance(x, bytes)).lower()
            if b"pdf" not in blob and b"octet-stream" not in blob:
                return None
        typ, raw = im.fetch(num, "(RFC822)")
        if typ != "OK" or not raw or not isinstance(raw[0], tuple):
            return None
        return email.message_from_bytes(raw[0][1])
    except Exception:
        return None


def _walk(im, folder, days, cap, handle):
    """1フォルダぶんを見る。開けないフォルダは飛ばす。

    権限の無いフォルダや、一覧には出るが実体の無いものがある。
    そこで止めると他のフォルダまで見られなくなるので、黙って次へ進む。
    """
    try:
        _open(im, folder)
    except PermitMailError:
        return
    for num in _recent_nums(im, days, cap):
        msg = _fetch_message(im, num)
        if msg is None:
            continue
        handle(msg, folder)


def scan(days: int = 60, folder: str = None):
    """メールを見て、輸入許可書らしいPDFを返す。保存はしない。

    戻り値は取り込み側がそのままDBへ入れられる形にしてある。
    folder に ALL("*") を渡すと、ごみ箱などを除く全フォルダを見る。
    """
    im = _connect()
    found = []
    try:
        targets = _targets(im, folder)
        cap = MAX_MESSAGES_ALL if len(targets) > 1 else MAX_MESSAGES

        def handle(msg, box):
            h = _headers(msg)
            for name, data_bytes in _pdf_attachments(msg):
                parsed = parse_permit_pdf(data_bytes)
                if not parsed.pop("is_permit"):
                    continue
                found.append({
                    **parsed,
                    "filename": name,
                    "size_bytes": len(data_bytes),
                    "pdf": data_bytes,
                    "source": "mail",
                    # Message-IDを出さないサーバーがあるので、無ければ
                    # 差出人と件名と日付で代える（同じ組は同じメール）
                    "mail_message_id": (h["message_id"]
                                        or f"{h['from']}|{h['subject']}|{h['date']}"),
                    "mail_subject": h["subject"],
                    "mail_from": h["from"],
                    "mail_date": h["date"],
                })

        for box in targets:
            _walk(im, box, days, cap, handle)
    finally:
        try:
            im.logout()
        except Exception:
            pass
    return found


def scan_candidates(days: int = 60, folder: str = None):
    """PDFの添付を、許可書かどうかに関わらず並べる（調査用）。

    自動で拾えなかったときに、何を見て何を落としたのかが分からないと
    直しようがない。件名と添付名だけを返し、本体は持たない。
    """
    im = _connect()
    out = []
    try:
        targets = _targets(im, folder)
        cap = MAX_MESSAGES_ALL if len(targets) > 1 else MAX_MESSAGES

        def handle(msg, box):
            h = _headers(msg)
            for name, data_bytes in _pdf_attachments(msg):
                text = _pdf_text(data_bytes)
                out.append({
                    "folder": _utf7_decode(box),
                    "subject": h["subject"],
                    "from": h["from"],
                    "date": h["date"],
                    "filename": name,
                    "size_bytes": len(data_bytes),
                    "is_permit": looks_like_permit(text),
                    # 拾えなかったときに、何のPDFだったのかが分かる程度に
                    "text_head": (text or "")[:120].replace("\n", " "),
                })

        for box in targets:
            _walk(im, box, days, cap, handle)
    finally:
        try:
            im.logout()
        except Exception:
            pass
    return out
