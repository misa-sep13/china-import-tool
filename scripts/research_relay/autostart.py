"""取り込みサーバーを、Windowsのログイン時に自動で立ち上げる。

毎回 bat を押すのは忘れる。忘れるとシートから⚡が消えて、
「なぜか自動取得できない」という状態になる。

スタートアップフォルダにショートカットを置くだけの仕組みにしてある。
タスクスケジューラより見つけやすく、外すのも同じくらい簡単。

  【自動で起動するようにする】.bat   置く
  【自動起動をやめる】.bat           外す
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "china-import 取り込みサーバー.lnk"


def startup_dir() -> Path:
    return Path(os.path.expandvars(
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"))


def link_path() -> Path:
    return startup_dir() / NAME


def enable() -> None:
    """スタートアップにショートカットを置く。

    窓を出したままにすると邪魔なので、最小化で開く。
    止めたいときはその窓を閉じればよい（自動起動そのものは残る）。
    """
    target = HERE / "relay.py"
    # pythonw だと窓が出ない。ただし窓が無いと止め方が分かりにくいので、
    # 窓は出したうえで最小化する
    ps = f"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{link_path()}')
$s.TargetPath = 'cmd.exe'
$s.Arguments = '/c start "取り込みサーバー" /min python "{target}"'
$s.WorkingDirectory = '{HERE}'
$s.Description = '競合リサーチシートの取り込みサーバー'
$s.Save()
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    print("次のログインから自動で立ち上がります。")
    print("  置き場所:", link_path())
    print()
    print("今すぐ使うなら、【取り込みサーバーを起動】.bat を実行してください。")


def disable() -> None:
    p = link_path()
    if p.exists():
        p.unlink()
        print("自動起動をやめました。")
    else:
        print("自動起動は設定されていません。")


if __name__ == "__main__":
    try:
        if "--off" in sys.argv:
            disable()
        else:
            enable()
    except Exception as e:
        print("失敗しました:", type(e).__name__, e)
        sys.exit(1)
