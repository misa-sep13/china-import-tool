"""タオタロウのサイト側（会員画面）から、公式APIに無いものを取る。

FBA指示書は公式API（api.yiwutaro.com）の一覧に無い。画面が使っている
GraphQL に exportFBA があるので、そちらを叩く。

    POST https://www.yiwutaro.com/graphql/member
      X-XSRF-TOKEN: （クッキー XSRF-TOKEN の値）
      mutation exportFBA($sid: Int){ exportFile: exportFBA(sid: $sid){ url msg } }
    → 署名付きのxlsxのURL（期限つき）

ログインは画像認証があるので自動ではできない。ブラウザでログインした
ときのクッキーを設定に貼ってもらい、それを送る。1か月ほどで切れるので、
切れたら貼り直す。公式の口ではないので、タオタロウ側の作りが変われば
黙って動かなくなる。そのときは今までどおり手で落とせるようにしてある。
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

SITE = "https://www.yiwutaro.com"
_EXPORT_FBA = (
    "mutation exportFBA($sid: Int){ exportFile: exportFBA(sid: $sid)"
    "{ url msg } }"
)


class WebError(Exception):
    pass


def _xsrf(cookie: str) -> str:
    for part in (cookie or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == "XSRF-TOKEN":
            return urllib.parse.unquote(v)
    return ""


def _graphql(cookie: str, query: str, variables: dict) -> dict:
    token = _xsrf(cookie)
    if not token:
        # 長いので途中までしか貼られていないことが多い。
        # 何が入っていて何が足りないかまで言う
        got = [p.strip().split("=")[0] for p in (cookie or "").split(";")
               if p.strip()]
        raise WebError(
            "クッキーに XSRF-TOKEN が入っていません"
            f"（入っていたのは {len(got)}個："
            f"{'、'.join(got[:4])}…）。"
            "途中で切れている可能性があります。"
            "Cookie の中身を最後まで丸ごと貼り直してください")

    req = urllib.request.Request(
        f"{SITE}/graphql/member",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-XSRF-TOKEN": token,
            "Cookie": cookie,
            # 画面からの通信に見えるようにしておく
            "Origin": SITE,
            "Referer": f"{SITE}/member/send-order",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/131.0.0.0 Safari/537.36"),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            body = res.read()
    except urllib.error.HTTPError as e:
        if e.code == 419:
            # Laravel の CSRF 切れ。クッキーが古いか、
            # 貼り付けが途中で切れて XSRF-TOKEN が合っていない
            raise WebError(
                "タオタロウのログインが切れています（419）。"
                "Chromeで www.yiwutaro.com を開いてログインし直し、"
                "Cookie を貼り直してください。"
                "（クッキーは1か月ほどで切れます）")
        raise WebError(f"タオタロウが HTTP {e.code} を返しました")
    except Exception as e:
        raise WebError(f"タオタロウに繋がりませんでした（{e}）")

    try:
        data = json.loads(body)
    except Exception:
        # ログインが切れていると画面のHTMLが返ってくる
        raise WebError("ログインが切れています。クッキーを貼り直してください")

    errs = data.get("errors") or []
    if errs:
        raise WebError(str(errs[0].get("message") or "エラーが返りました"))
    return data.get("data") or {}


def fba_instruction_url(cookie: str, sid: int) -> str:
    """配送依頼1件のFBA指示書のURLを返す（署名つき・期限あり）。"""
    d = _graphql(cookie, _EXPORT_FBA, {"sid": int(sid)})
    f = d.get("exportFile") or {}
    url = (f.get("url") or "").strip()
    if not url:
        raise WebError(f.get("msg") or "指示書がまだできていません")
    return url


def fba_instruction_file(cookie: str, sid: int) -> tuple:
    """FBA指示書を落として (ファイル名, 中身) で返す。"""
    url = fba_instruction_url(cookie, sid)
    try:
        with urllib.request.urlopen(url, timeout=60) as res:
            raw = res.read()
    except Exception as e:
        raise WebError(f"指示書を落とせませんでした（{e}）")

    name = urllib.parse.unquote(
        urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]) or f"FBA_{sid}.xlsx"
    return name, raw


def check(cookie: str) -> Optional[str]:
    """クッキーが生きているかだけ見る。生きていればNone。"""
    try:
        _graphql(cookie, "query{ userInfo { id } }", {})
        return None
    except WebError as e:
        return str(e)
