"""一元管理の「更新する」ボタンから、このPCで巡回を始められるようにする。

Windowsに「scout:// で始まるリンクは、このプログラムで開く」と教える。
登録先は HKEY_CURRENT_USER なので管理者権限は要らず、
このユーザーの分だけに入る（他のユーザーには影響しない）。

使い方:
  python register_button.py            … 登録する
  python register_button.py --remove   … 解除する
"""
import argparse
import os
import sys
import winreg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
KEY = r"Software\Classes\scout"


def line(n=56):
    print("=" * n)


def register():
    # pythonw ではなく python を使う。黒い画面が出たほうが、
    # 動いていることが分かって安心できる（進捗もそこに出る）
    agent = os.path.join(HERE, "scout_agent.py")
    cmd = f'"{sys.executable}" "{agent}" --once --interval 3 --timeout 90'

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "URL:Seller Scout")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY + r"\shell\open\command") as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, cmd)

    print("  登録しました。")
    print(f"    使うPython: {sys.executable}")
    print()
    print("  一元管理の「競合リサーチ」→「セラースカウト」で")
    print("  【更新する】または【ブックマークを取り込む】を押してください。")
    print()
    print("  初回だけ「Seller Scout を開きますか？」と確認が出ます。")
    print("  「常に許可する」にチェックを入れると、次からは確認なしで始まります。")
    print()
    print("  解除したいときは【ボタン起動を解除する】.bat を実行してください。")


def remove():
    # 子キーから順に消す。親から消そうとすると中身が残っていて失敗する
    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY + sub)
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"  消せませんでした: {KEY + sub} ({e})")
            return 1
    print("  解除しました。")
    print()
    print("  巡回そのものは【巡回する】.bat で今までどおり実行できます。")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    line()
    print(" セラースカウト  " + ("ボタン起動の解除" if args.remove else "ボタンから起動できるようにする"))
    line()
    print()
    if args.remove:
        print("  「更新する」ボタンからこのPCで巡回を始める登録を消します。")
    else:
        print("  「更新する」ボタンを押したときに、このPCで巡回が")
        print("  始まるようにWindowsへ登録します。")
        print()
        print("  ・管理者権限は要りません")
        print("  ・ご自身のログイン分だけに登録されます")
    print()
    return remove() if args.remove else (register() or 0)


if __name__ == "__main__":
    sys.exit(main() or 0)
