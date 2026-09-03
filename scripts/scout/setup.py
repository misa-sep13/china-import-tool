"""トークンを一度だけ保存する。以後は入力不要。

トークンは長いうえ会話やメモに残ると漏れるので、
このPCのユーザーフォルダに置いて、他の人からは読めないようにする。
リポジトリの中には置かない（gitに乗ってしまうため）。
"""
import subprocess
import json
import os
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONF = os.path.join(os.path.expanduser("~"), ".scout_config.json")
DEFAULT_BASE = "https://china-import-tool.onrender.com/api"


def load():
    if os.path.exists(CONF):
        try:
            with open(CONF, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _shape(token):
    """中身は出さずに、正しく渡ったか確かめられる程度の情報だけ返す。"""
    return f"{token[:6]}...{token[-6:]}" if len(token) > 16 else "(短すぎます)"


def _from_clipboard():
    """クリップボードの中身を取り出す。取れなければ空文字。

    PowerShell を使う。pyperclip などを入れずに済ませたい
    （外注さんのPCに追加インストールを増やしたくない）。
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            capture_output=True, timeout=20)
    except Exception:
        return ""
    if out.returncode != 0:
        return ""
    text = out.stdout.decode("utf-8", "replace").strip().strip('"' + "'")
    # トークンらしくないものを拾っても混乱するだけなので弾く
    if "." not in text or len(text) < 40 or len(text) > 4000:
        return ""
    return text



def check(base, token):
    """保存する前に、そのトークンで実際に通るか確かめる。

    間違ったまま保存すると、巡回を1時間走らせた末に送信で落ちる。
    """
    req = urllib.request.Request(
        f"{base.rstrip('/')}/scout/sellers",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.load(res).get("total", 0)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SystemExit(
                "このトークンでは通りませんでした。\n"
                "  ・貼り付けが途中で切れていないか（上の文字数を確認）\n"
                "  ・ログアウトして入り直し、取り直してみてください")
        raise SystemExit(f"サーバーに繋がりませんでした（{e.code}）")
    except Exception as e:
        raise SystemExit(f"サーバーに繋がりませんでした（{type(e).__name__}）")


def main():
    cur = load()
    print("=" * 56)
    print(" セラースカウト  初回設定")
    print("=" * 56)
    print()
    if cur.get("token"):
        print("すでに設定済みです。変えるときだけ入力してください。")
        print(f"  名前: {cur.get('run_by') or '(未設定)'}")
        print()

    print("一元管理ツールにログインした状態で F12 を押し、")
    print("Console に次を貼って Enter してください。")
    print("（画面には何も出ませんが、トークンがコピーされます）")
    print()
    print("  copy(localStorage.getItem('auth_token'))")
    print()

    # クリップボードから直接読む。
    # 以前は伏せ字入力に貼り付けてもらっていたが、Windowsのコンソールでは
    # 貼り付けが途中で切れることがある（151文字が6文字になった）。
    # コピーさえできていれば貼り付け作業そのものが要らない。
    token = _from_clipboard()
    if token:
        print(f"  クリップボードから読み取りました: {len(token)}文字  {_shape(token)}")
        if input("  これを使いますか？ [Y/n]: ").strip().lower() in ("n", "no"):
            token = ""
        else:
            print()
    if not token:
        print()
        print("クリップボードから読めませんでした。")
        print("上のコピーを実行してからもう一度開くか、ここに貼り付けてください。")
        print("（今度は入力した文字が見えます。人に見られない状態で行ってください）")
        token = input("トークン: ")
    token = token.strip().strip('"' + "'")

    if token:
        print(f"  受け取った文字数: {len(token)}文字  {_shape(token)}")
        if "." not in token or len(token) < 40:
            print("  ※ 形が違うようです。コピーが途中で切れていないか確認してください")
    if not token:
        token = cur.get("token", "")
    if not token:
        raise SystemExit("トークンが空です")

    run_by = input(f"あなたの名前 [{cur.get('run_by') or ''}]: ").strip() or cur.get("run_by") or ""
    base = cur.get("base") or DEFAULT_BASE

    print()
    print("確認しています…")
    n = check(base, token)
    print(f"  OK。セラーが {n} 社登録されています")

    with open(CONF, "w", encoding="utf-8") as f:
        json.dump({"token": token, "run_by": run_by, "base": base}, f,
                  ensure_ascii=False, indent=2)
    try:                      # 他のユーザーから読めないようにする
        os.chmod(CONF, 0o600)
    except Exception:
        pass

    print()
    print(f"保存しました: {CONF}")
    print("以後は【巡回する】をダブルクリックするだけです。")


if __name__ == "__main__":
    main()
