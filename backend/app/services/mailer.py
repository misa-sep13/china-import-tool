"""メール送信。

発注書を取引先へ送る。誤送信は取り消せないので、送る前に必ず
画面で内容を確認する作りにしてある（ここは送るだけ）。

接続情報は環境変数から読む。パスワードをコードやDBに置くと
git やバックアップに残るため。
"""
import os
import smtplib
import ssl
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

    return to_list + cc_list


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
