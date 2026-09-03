"""一元管理の画面から出された巡回の依頼を、このPCで実行し続ける常駐。

巡回はブラウザ自動操縦なのでサーバーでは走らせられない（Amazonが
データセンターのipを弾く）。かといって毎回バッチを探して叩くのは
外注さんには続かないので、画面の「更新する」で依頼だけ積んでもらい、
これが拾って実行する。

起動しっぱなしにしておく想定。閉じれば止まる。
巡回中でなければCPUもネットもほとんど使わない（既定で30秒に1回、
依頼が無いか聞くだけ）。

使い方:
  python scout_agent.py                 # 【常駐する】.bat がこれを叩く
  python scout_agent.py --interval 60   # 確認の間隔を変える（秒）
  python scout_agent.py --once          # 1件だけ処理して終わる（動作確認用）
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(os.path.expanduser("~"), ".scout_config.json")
DEFAULT_BASE = "https://china-import-tool.onrender.com/api"
DEFAULT_INTERVAL = 30
KIND_LABEL = {"crawl": "巡回", "bookmarks": "ブックマークの取り込み"}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def load_conf():
    if not os.path.exists(CONF):
        raise SystemExit(
            "設定がありません。先に【初回設定】.bat を実行してください")
    with open(CONF, encoding="utf-8") as f:
        return json.load(f)


def api(base, path, token, method="GET", body=None, timeout=60):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def build_args(params):
    """画面の指定を巡回スクリプトの引数に直す。

    画面には配布版のころの項目がそのまま残っていて、巡回側に無いものもある
    （pace の slow など）。無いものは落とす。既定がもともと安全側なので、
    多少ずれても回って結果が集まるほうが大事。
    """
    args = []
    sellers = params.get("sellers")
    if sellers:
        args += ["--sellers", ",".join(str(x) for x in sellers)]
    elif params.get("stale_days"):
        args += ["--stale-days", str(params["stale_days"])]
    if params.get("pages"):
        args += ["--pages", str(params["pages"])]
    if params.get("early_stop") is False:      # 既定が有効なので、切るときだけ渡す
        args += ["--no-early-stop"]
    if params.get("fast"):
        args += ["--fast"]
    if params.get("resume"):
        args += ["--resume"]
    if params.get("hidden"):
        args += ["--hidden"]
    return args


def run_one(base, token, run_by, req):
    req_id = req["id"]
    kind = req.get("kind") or "crawl"
    params = req.get("params") or {}
    log(f"依頼 #{req_id}（{KIND_LABEL.get(kind, kind)}）を受け取りました"
        + (f": {json.dumps(params, ensure_ascii=False)}" if params else ""))

    if kind == "bookmarks":
        # ブックマークはこのPCの中にしか無いので、サーバーからは読めない
        cmd = [sys.executable, os.path.join(HERE, "push_sellers.py"),
               "--token", token]
        log("ブックマークを読んでいます")
    else:
        cmd = [sys.executable, os.path.join(HERE, "sync_server.py"),
               "--token", token, "--run-by", run_by] + build_args(params)
        log("巡回を始めます（Chromeのウィンドウが開きます）")

    ok, message = True, None
    try:
        rc = subprocess.call(cmd, cwd=HERE)
        label = KIND_LABEL.get(kind, kind)
        if rc != 0:
            ok = False
            message = f"{label}が異常終了しました（コード {rc}）"
            log(message)
        else:
            log(f"{label}が終わりました")
    except Exception as e:
        ok = False
        message = f"{type(e).__name__}: {e}"
        log(f"実行できませんでした: {message}")

    try:
        api(base, f"/scout/crawl-request/{req_id}/finish", token, "POST",
            {"ok": ok, "message": message})
    except Exception as e:
        # 報告に失敗しても巡回結果自体は sync_server が送っている。
        # ここで落とすと常駐が止まってしまうので、記録だけ残して続ける
        log(f"完了の報告に失敗しました（{type(e).__name__}）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                    help="依頼を確認する間隔（秒）")
    ap.add_argument("--once", action="store_true", help="1件処理したら終わる")
    ap.add_argument("--timeout", type=int, default=0,
                    help="依頼が来なければ何秒であきらめるか（0なら待ち続ける）")
    args = ap.parse_args()

    conf = load_conf()
    token = conf.get("token") or ""
    base = (conf.get("base") or DEFAULT_BASE).rstrip("/")
    run_by = conf.get("run_by") or os.environ.get("USERNAME") or "unknown"
    if not token:
        raise SystemExit("トークンがありません。【初回設定】.bat を実行してください")

    if args.timeout:
        log(f"巡回の依頼を確認しています（{run_by}）")
    else:
        log(f"常駐を開始しました（{run_by} / {args.interval}秒ごとに確認）")
        log("一元管理の「競合リサーチ」で『更新する』を押すと、ここで巡回が始まります")
        log("止めるときはこのウィンドウを閉じてください")

    quiet_errors = 0
    started = time.time()
    while True:
        # ボタンから呼ばれたときは、依頼が無ければすぐ引き下がる。
        # 常駐と同時に動いていると、先に取ったほうだけが回ることになる
        if args.timeout and time.time() - started > args.timeout:
            log("依頼が見つかりませんでした。常駐が先に受け取ったのかもしれません")
            return
        try:
            r = api(base, f"/scout/crawl-request?run_by={urllib.parse.quote(run_by)}",
                    token)
            quiet_errors = 0
            req = r.get("request")
            if req:
                run_one(base, token, run_by, req)
                if args.once:
                    return
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit(
                    "認証エラー: トークンが無効です。【初回設定】.bat をやり直してください")
            quiet_errors += 1
            if quiet_errors in (1, 10, 100):
                log(f"サーバーからエラー（{e.code}）。確認を続けます")
        except Exception as e:
            # ネットが切れている・Renderが寝ている等。常駐は止めずに待つ
            quiet_errors += 1
            if quiet_errors in (1, 10, 100):
                log(f"サーバーに繋がりません（{type(e).__name__}）。確認を続けます")
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("常駐を終了しました")
