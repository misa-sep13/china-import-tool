"""メール送信。

発注書を取引先へ送る。誤送信は取り消せないので、送る前に必ず
画面で内容を確認する作りにしてある（ここは送るだけ）。

接続情報は環境変数から読む。パスワードをコードやDBに置くと
git やバックアップに残るため。
"""
import imaplib
import os
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate


class MailNotConfigured(Exception):
    """送信設定が入っていない。画面に出して設定を促すため分けている。"""


def config():
    return {
        "host": os.environ.get("SMTP_HOST", ""),
        "port": int(os.environ.get("SMTP_PORT", "465") or 465),
        "user": os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "from_email": os.environ.get("SMTP_FROM_EMAIL", "")
                      or os.environ.get("SMTP_USER", ""),
        "from_name": os.environ.get("SMTP_FROM_NAME", ""),
        # 送信済みトレイへの保存用。SMTPは送るだけで控えを残さないので、
        # メールソフトと同じようにIMAPで自分の送信済みへ入れる
        "imap_host": os.environ.get("IMAP_HOST", "")
                     or os.environ.get("SMTP_HOST", ""),
        "imap_port": int(os.environ.get("IMAP_PORT", "993") or 993),
        "imap_folder": os.environ.get("IMAP_SENT_FOLDER", ""),
    }


def is_configured():
    c = config()
    return bool(c["host"] and c["user"] and c["password"])


def _addresses(value):
    """カンマ区切りの宛先を配列にする。空白や全角カンマも受ける。"""
    if not value:
        return []
    v = value.replace("、", ",").replace("，", ",").replace(";", ",")
    return [a.strip() for a in v.split(",") if a.strip()]


# 送信済みトレイの名前はサーバーによって違う。よくあるものを順に試す
SENT_CANDIDATES = ["Sent", "INBOX.Sent", "Sent Messages", "Sent Items",
                   "INBOX.送信済みトレイ", "送信済みトレイ", "INBOX.Sent Messages"]


def _list_name(line):
    """IMAPのLIST応答からフォルダ名だけ取り出す。

    応答は (属性) "区切り" "名前" の形。素朴に split すると区切り文字
    まで拾ってしまうので、末尾の引用符の中だけを取る。
    引用符が無いサーバーもあるので、その場合は最後の語を使う。
    """
    m = re.search(r'"([^"]*)"\s*$', line)
    if m:
        return m.group(1)
    parts = line.rsplit(" ", 1)
    return parts[-1].strip() if parts else ""


def _find_sent_folder(im):
    """送信済みトレイを探す。

    RFC6154 の Sent 属性（バックスラッシュ付き）が付いていればそれが確実。
    付いていない
    サーバーもあるので、その場合はよくある名前を順に試す。
    """
    try:
        typ, boxes = im.list()
        if typ == "OK":
            for raw in boxes:
                line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
                if r"\Sent" in line:
                    name = _list_name(line)
                    if name:
                        return name
    except Exception:
        pass

    for name in SENT_CANDIDATES:
        try:
            if im.select(f'"{name}"', readonly=True)[0] == "OK":
                return name
        except Exception:
            continue
    return None


def save_to_sent(msg):
    """送ったメールを自分の送信済みトレイへ入れる。

    SMTPは送るだけで控えを残さない。メールソフトから送ったときと
    同じように手元にも残るよう、IMAPで保存する。

    ここが失敗しても送信そのものは成功しているので、例外は投げず
    理由を返す。控えが無いことより、送れたのに失敗と表示される方が困る。
    """
    c = config()
    if not c["imap_host"]:
        return {"saved": False, "reason": "IMAPの接続先が分かりません"}
    try:
        ctx = ssl.create_default_context()
        with imaplib.IMAP4_SSL(c["imap_host"], c["imap_port"],
                               ssl_context=ctx, timeout=30) as im:
            im.login(c["user"], c["password"])
            folder = c["imap_folder"] or _find_sent_folder(im)
            if not folder:
                return {"saved": False, "reason": "送信済みトレイが見つかりません"}
            im.append(f'"{folder}"', r"\Seen",
                      imaplib.Time2Internaldate(time.time()),
                      msg.as_bytes())
            return {"saved": True, "folder": folder}
    except Exception as e:
        return {"saved": False, "reason": f"{type(e).__name__}: {e}"}


def send(to, subject, body, cc=None, attachments=None):
    """メールを送る。

    attachments: [(ファイル名, バイト列, MIMEタイプ)]
    戻り値: 実際に送った宛先（記録に残すため）
    """
    c = config()
    if not is_configured():
        raise MailNotConfigured(
            "メールの送信設定が入っていません。"
            "SMTP_HOST / SMTP_USER / SMTP_PASSWORD を設定してください")

    to_list = _addresses(to)
    cc_list = _addresses(cc)
    if not to_list:
        raise ValueError("宛先がありません")

    msg = EmailMessage()
    msg["From"] = formataddr((c["from_name"], c["from_email"])) if c["from_name"] \
                  else c["from_email"]
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body)

    for name, data, mime in (attachments or []):
        main, _, sub = mime.partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)

    ctx = ssl.create_default_context()
    if c["port"] == 465:                       # SSL/TLS
        with smtplib.SMTP_SSL(c["host"], c["port"], context=ctx, timeout=60) as s:
            s.login(c["user"], c["password"])
            s.send_message(msg)
    else:                                      # STARTTLS
        with smtplib.SMTP(c["host"], c["port"], timeout=60) as s:
            s.starttls(context=ctx)
            s.login(c["user"], c["password"])
            s.send_message(msg)

    # 送ったあと、自分の送信済みトレイにも入れる。
    # 失敗しても送信は成功しているので、結果だけ返して止めない
    saved = save_to_sent(msg)

    return {"recipients": to_list + cc_list, "sent_copy": saved}


def test_connection():
    """設定が正しいか、送らずに確かめる。

    実際にログインまでやる。宛先を間違えたまま本番の発注書を
    送ってしまう前に、設定だけ検証できるようにするため。
    """
    c = config()
    if not is_configured():
        raise MailNotConfigured("SMTP_HOST / SMTP_USER / SMTP_PASSWORD が未設定です")
    ctx = ssl.create_default_context()
    if c["port"] == 465:
        with smtplib.SMTP_SSL(c["host"], c["port"], context=ctx, timeout=30) as s:
            s.login(c["user"], c["password"])
    else:
        with smtplib.SMTP(c["host"], c["port"], timeout=30) as s:
            s.starttls(context=ctx)
            s.login(c["user"], c["password"])
    return {"host": c["host"], "port": c["port"], "user": c["user"],
            "from": c["from_email"]}


def check_sent_folder():
    """送信済みトレイに繋がるか、どのフォルダを使うかを見る。

    サーバーごとに名前が違うので、実際に繋いで確かめられるようにする。
    """
    c = config()
    if not c["imap_host"] or not c["password"]:
        return {"ok": False, "reason": "IMAPの設定がありません"}
    try:
        ctx = ssl.create_default_context()
        with imaplib.IMAP4_SSL(c["imap_host"], c["imap_port"],
                               ssl_context=ctx, timeout=30) as im:
            im.login(c["user"], c["password"])
            folder = c["imap_folder"] or _find_sent_folder(im)
            typ, boxes = im.list()
            names = []
            if typ == "OK":
                for raw in boxes:
                    line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
                    n = _list_name(line)
                    if n:
                        names.append(n)
            return {"ok": bool(folder), "folder": folder,
                    "host": c["imap_host"], "port": c["imap_port"],
                    "folders": names[:40]}
    except Exception as e:
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
