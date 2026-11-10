"""タオタロウのサイト側（会員画面）から、公式APIに無いものを取る。

FBA指示書は公式API（api.yiwutaro.com）の一覧に無い。画面が使っている
GraphQL に exportFBA があるので、そちらを叩く。

    POST https://www.yiwutaro.com/graphql/member
      X-XSRF-TOKEN: （クッキー XSRF-TOKEN の値）
      mutation exportFBA($sid: Int){ exportFile: exportFBA(sid: $sid){ url msg } }
    → 署名付きのxlsxのURL（期限つき）

ログインには画像の確認コード（CAPTCHA）があるので、自動ではできない。
ブラウザでログインしたときのクッキーを設定に貼ってもらい、それを送る。

ただし貼ったものをそのまま使い続けると、すぐ「切れた（419）」になる。
419 は Laravel の CSRF ずれで、ログアウトとは限らない。貼った
XSRF-TOKEN は貼った瞬間のもので、向こうが作り直すと合わなくなる。

そこで毎回、使う直前に /sanctum/csrf-cookie を叩いて今の
XSRF-TOKEN と laravel_session をもらい直し、それで送る。もらい直した
クッキーは設定に書き戻す（Session クラス）。こうすると、ログインの
証（ログイン画面の「1ヶ月間ログインしたままにする」で入る
remember_web_… のクッキー）が生きているかぎり、向こうが勝手に
入り直してくれるので、貼り直す回数がぐっと減る。

公式の口ではないので、タオタロウ側の作りが変われば黙って動かなく
なる。そのときは今までどおり手で落とせるようにしてある。
"""
import contextlib
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

SITE = "https://www.yiwutaro.com"
# これを叩くと、今の XSRF-TOKEN と laravel_session をくれる。
# ログインが切れていても remember のクッキーがあれば入り直してくれる
CSRF_PATH = "/sanctum/csrf-cookie"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_EXPORT_FBA = (
    "mutation exportFBA($sid: Int){ exportFile: exportFBA(sid: $sid)"
    "{ url msg } }"
)


class WebError(Exception):
    pass


LOGIN_EXPIRED = (
    "タオタロウのログインが切れています。"
    "Chromeで www.yiwutaro.com にログインし直して"
    "（ログイン画面の「1ヶ月間ログインしたままにする」に"
    "チェックを入れてください）、Amazon設定にCookieを貼り直して"
    "ください")


def _parse(cookie: str) -> dict:
    """貼られたクッキーの文字列を名前→値の辞書にする。"""
    out = {}
    for part in (cookie or "").split(";"):
        k, sep, v = part.strip().partition("=")
        if k and sep:
            out[k] = v
    return out


def _join(jar: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in jar.items())


def _merge_set_cookie(jar: dict, res) -> None:
    """返ってきた Set-Cookie を手元のクッキーに重ねる。"""
    for line in res.headers.get_all("Set-Cookie") or []:
        head, _, rest = line.partition(";")
        k, sep, v = head.strip().partition("=")
        if not k or not sep:
            continue
        low = rest.lower()
        # 消しにきている行（Max-Age=0 や過去の expires）は消す
        if "max-age=0" in low.replace(" ", ""):
            jar.pop(k, None)
            continue
        jar[k] = v


class Session:
    """貼られたクッキーを持ち回しつつ、向こうの最新に追従する。

    使う側は、終わったあと cookie が変わっていたら設定に書き戻す。
    書き戻さないと、せっかくもらい直した laravel_session を毎回
    捨てることになり、また「切れた」と言われる。
    """

    def __init__(self, cookie: str):
        self.jar = _parse(cookie)
        self._refreshed = False

    @property
    def cookie(self) -> str:
        return _join(self.jar)

    @property
    def xsrf(self) -> str:
        return urllib.parse.unquote(self.jar.get("XSRF-TOKEN", ""))

    def refresh(self) -> None:
        """今の XSRF-TOKEN と laravel_session をもらい直す。"""
        req = urllib.request.Request(
            SITE + CSRF_PATH,
            headers={"Cookie": self.cookie, "User-Agent": UA,
                     "Referer": f"{SITE}/member"})
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                _merge_set_cookie(self.jar, res)
                res.read()
        except urllib.error.HTTPError as e:
            _merge_set_cookie(self.jar, e)
        except Exception as e:
            raise WebError(f"タオタロウに繋がりませんでした（{e}）")
        self._refreshed = True


def _as_session(cookie) -> Session:
    return cookie if isinstance(cookie, Session) else Session(cookie)


def _post(sess: Session, query: str, variables: dict):
    req = urllib.request.Request(
        f"{SITE}/graphql/member",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-XSRF-TOKEN": sess.xsrf,
            "Cookie": sess.cookie,
            # 画面からの通信に見えるようにしておく
            "Origin": SITE,
            "Referer": f"{SITE}/member/send-order",
            "User-Agent": UA,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        _merge_set_cookie(sess.jar, res)
        return res.read()


def _graphql(cookie, query: str, variables: dict) -> dict:
    sess = _as_session(cookie)
    if not sess.jar:
        raise WebError(
            "タオタロウのクッキーが入っていません。"
            "Amazon設定に貼ってください")

    # 貼られた XSRF-TOKEN は貼った瞬間のもの。先にもらい直す
    if not sess._refreshed:
        sess.refresh()
    if not sess.xsrf:
        got = list(sess.jar)
        raise WebError(
            "XSRF-TOKEN をもらえませんでした"
            f"（手元にあるのは {len(got)}個："
            f"{'、'.join(got[:4])}…）。"
            "クッキーが途中で切れているか、ログインが切れています。"
            "Cookie の中身を最後まで丸ごと貼り直してください")

    try:
        body = _post(sess, query, variables)
    except urllib.error.HTTPError as e:
        if e.code == 419:
            # CSRF ずれ。もらい直してもう一度だけ試す
            _merge_set_cookie(sess.jar, e)
            e.read()
            sess.refresh()
            try:
                body = _post(sess, query, variables)
            except urllib.error.HTTPError as e2:
                if e2.code == 419:
                    raise WebError(LOGIN_EXPIRED + "（419）")
                raise WebError(f"タオタロウが HTTP {e2.code} を返しました")
            except Exception as e2:
                raise WebError(f"タオタロウに繋がりませんでした（{e2}）")
        else:
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
        msg = str(errs[0].get("message") or "エラーが返りました")
        # ログインしていないと中国語で「鉴权失败（認証に失敗）」が返る。
        # そのまま出しても何をすればいいか分からないので言い換える
        if any(w in msg for w in ("鉴权失败", "未登录", "Unauthenticated")):
            raise WebError(LOGIN_EXPIRED)
        raise WebError(msg)
    return data.get("data") or {}


@contextlib.contextmanager
def logged_in(db, row):
    """設定のクッキーで開き、終わったら新しいクッキーを書き戻す。

    書き戻しを忘れると、もらい直した laravel_session を毎回捨てる
    ことになるので、使う側は必ずこれを通す。
    """
    cookie = (getattr(row, "taotaro_web_cookie", "") or "").strip()
    if not cookie:
        raise WebError(
            "タオタロウのログイン情報が入っていません"
            "（Amazon設定で貼ってください）")
    sess = Session(cookie)
    try:
        yield sess
    finally:
        new = sess.cookie
        if new and new != cookie:
            try:
                row.taotaro_web_cookie = new
                db.commit()
            except Exception:
                db.rollback()


def fba_instruction_url(cookie, sid: int) -> str:
    """配送依頼1件のFBA指示書のURLを返す（署名つき・期限あり）。"""
    d = _graphql(cookie, _EXPORT_FBA, {"sid": int(sid)})
    f = d.get("exportFile") or {}
    url = (f.get("url") or "").strip()
    if not url:
        raise WebError(f.get("msg") or "指示書がまだできていません")
    return url


def fba_instruction_file(cookie, sid: int) -> tuple:
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


def is_login_error(e) -> bool:
    """「ログインが切れている」系のエラーかどうか。

    これが出たら、残りの注文も全部同じ理由で失敗する。
    何十回も叩かずその場で止めるために使う。
    """
    return "ログインが切れています" in str(e)


def who(cookie) -> dict:
    """ログインできているなら、誰で入っているかを返す。"""
    d = _graphql(cookie, "query{ getUserInfo { uid uname } }", {})
    return d.get("getUserInfo") or {}


def check(cookie) -> Optional[str]:
    """クッキーが生きているかだけ見る。生きていればNone。"""
    try:
        _graphql(cookie, "query{ getUserInfo { uid } }", {})
        return None
    except WebError as e:
        return str(e)


# ---------- 注文のASIN・FNSKU・管理番号 ----------
#
# 公式API（api.yiwutaro.com）には注文を作る口とキャンセルする口しかなく、
# 作ったあとでASIN・FNSKU・管理番号を書き換えられない。
# 会員画面には1件ずつの入力欄があり、その裏が updateOrder なので、
# FBA指示書と同じやり方（貼ってもらったクッキー）で叩く。
#
#   updateOrder(oid: Int!, remark: String, ASIN: String,
#               FNSKU: String, outId: String): String
#
# 初回発注の時点では、その商品をまだAmazonに出品していないので
# FNSKUはこの世に存在しない。だから発注時には入れようがなく、
# 出品してFNSKUが出てから後追いで入れるしかない。

_LIST_ORDER = (
    "query($c:OrderListInput){ listOrder(conditions:$c){ has_more_pages "
    "data{ oid outId ASIN FNSKU FBA state goodsName goodsUrl skuId "
    "goodsRemark createdAt } } }"
)

_UPDATE_ORDER = (
    "mutation($oid:Int!,$remark:String,$ASIN:String,$FNSKU:String,"
    "$outId:String){ updateOrder(oid:$oid,remark:$remark,ASIN:$ASIN,"
    "FNSKU:$FNSKU,outId:$outId) }"
)


def list_orders(cookie, states: Optional[list] = None,
                pages: int = 4, limit: int = 100) -> list:
    """注文を新しいほうから読む。ASIN・FNSKU・管理番号の今の中身つき。

    公式APIの一覧にはこの3つが入っていないので、こちらで読む。
    states を渡すと、そのステータスのものだけ返す。
    備考（goodsRemark）も読む。書き込みのときに元のまま送り返すため。
    """
    out: list = []
    for page in range(1, max(1, int(pages)) + 1):
        d = _graphql(cookie, _LIST_ORDER,
                     {"c": {"limit": int(limit), "page": page}})
        got = (d.get("listOrder") or {})
        rows = got.get("data") or []
        for o in rows:
            if states and o.get("state") not in states:
                continue
            out.append({
                "oid": o.get("oid"),
                "out_id": (o.get("outId") or "").strip(),
                "asin": (o.get("ASIN") or "").strip(),
                "fnsku": (o.get("FNSKU") or "").strip(),
                "remark": o.get("goodsRemark") or "",
                "fba": str(o.get("FBA") or "").strip(),
                "state": o.get("state"),
                "title": o.get("goodsName") or "",
                "url": o.get("goodsUrl") or "",
                "sku_id": str(o.get("skuId") or ""),
                "created_at": o.get("createdAt"),
            })
        if not got.get("has_more_pages"):
            break
    return out


def update_order(cookie, oid: int, asin: str, fnsku: str,
                 out_id: str, remark: str) -> None:
    """注文1件のASIN・FNSKU・管理番号・備考を入れ替える。

    4つとも必ず送る。送らなかった項目を向こうが「変更しない」と
    扱うのか「空にする」と扱うのかが分からないため。
    変えないものは今入っている値をそのまま送り返す。
    備考には「楽天用」「船便用」のような大事な指示が入っているので、
    うっかり消すと現場が止まる。
    """
    _graphql(cookie, _UPDATE_ORDER, {
        "oid": int(oid),
        "ASIN": (asin or "").strip(),
        "FNSKU": (fnsku or "").strip(),
        "outId": (out_id or "").strip(),
        "remark": remark or "",
    })
