"""Compassのブラウザを開く共通処理。

3つのスクリプトが同じことをしていたのでまとめた。
ログイン状態を残す作りもここに集約する。
"""
import json
import os
import sys

CONF = os.path.join(os.path.expanduser("~"), ".rakuten_register.json")
MENU = "https://www.compass-next.com/menu"


def load_conf():
    if os.path.exists(CONF):
        try:
            with open(CONF, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def profile_dir():
    """ブラウザの置き場。

    OneDrive配下だとキャッシュ数千件が同期されて大量削除の確認が
    出るので、必ずローカルに置く。
    """
    conf = load_conf()
    return conf.get("profile_dir") or os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "rakuten_register_profile")


async def open_compass(pw, url=MENU, ask=True):
    """Compassを開いて、ログイン済みの状態で返す。

    ログイン状態はプロファイルのCookieに残るので、2回目からは
    ログイン不要。ただしCompassのセッションには期限があるので、
    切れていたらその場でログインしてもらう。

    戻り値: (context, page)
    """
    ctx = await pw.chromium.launch_persistent_context(
        profile_dir(),
        headless=False,
        # 既定のままだと自動操縦だと見なされてログインを弾かれることがある
        args=["--disable-blink-features=AutomationControlled"],
        viewport=None,
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.goto(url)
    await page.wait_for_timeout(2000)

    # ログインが要るかどうかは、パスワード欄が描画されているかで見る。
    # SPAはセッション切れでも古いURLのまま白画面になることがあるため、
    # URLでは判断しない
    if await page.locator("#user_password").count():
        print()
        print("Compassのログインが切れています。ブラウザでログインしてください。")
        print("（一度ログインすれば、次回からは聞かれません）")
        input("  … ログインできたらEnter: ")
        await page.wait_for_timeout(2000)
        if page.url.rstrip("/").endswith("sign_in"):
            await page.goto(url)
            await page.wait_for_timeout(1500)
    elif ask:
        print()
        print(f"Compassを開きました（{page.url}）")

    return ctx, page


async def csrf_token(page):
    """CSRFトークンを用意して、ページに置いておく。

    metaタグに無いことがあるので、その場合は任意のGETの応答ヘッダから拾う。
    """
    got = await page.evaluate(
        """async () => {
             const m = document.querySelector('meta[name="csrf-token"]');
             if (m) return m.content;
             const r = await fetch(location.pathname, {credentials:'same-origin'});
             return r.headers.get('csrf-token') || '';
           }""")
    await page.evaluate("t => { window.__csrf = t }", got or "")
    return got


async def close(ctx):
    """閉じる。

    そのまま close() すると、Cookieがプロファイルへ書き戻される前に
    プロセスが終わることがある（毎回ログインを求められる原因）。
    少し待ってから閉じる。
    """
    try:
        for p in ctx.pages:
            await p.wait_for_timeout(300)
    except Exception:
        pass
    await ctx.close()
