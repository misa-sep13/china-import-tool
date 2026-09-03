@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ============================================================
echo  セラースカウト  ボタンから起動できるようにする
echo ============================================================
echo.
echo  一元管理の「更新する」ボタンを押したときに、
echo  このPCで巡回が始まるようにWindowsへ登録します。
echo.
echo  登録するのはこのユーザーの分だけです。
echo  管理者権限は要りません。他のユーザーには影響しません。
echo.
pause

set "PYEXE="
for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYEXE set "PYEXE=%%i"
if not defined PYEXE (
  echo.
  echo  Python が見つかりませんでした。
  echo  https://www.python.org/downloads/ から入れてください。
  echo  インストール画面の「Add python.exe to PATH」に必ずチェックを入れてください。
  echo.
  pause
  exit /b 1
)

set "CMD=\"%PYEXE%\" \"%~dp0scout_agent.py\" --once --interval 3 --timeout 90"

reg add "HKCU\Software\Classes\scout" /ve /d "URL:Seller Scout" /f > nul
reg add "HKCU\Software\Classes\scout" /v "URL Protocol" /d "" /f > nul
reg add "HKCU\Software\Classes\scout\shell\open\command" /ve /d "%CMD%" /f > nul

echo.
echo  登録しました。
echo    使う Python : %PYEXE%
echo.
echo  一元管理の「競合リサーチ」で【更新する】を押してください。
echo  初回だけ「Seller Scout を開きますか？」と確認が出ます。
echo  「常に許可する」にチェックを入れると、次からは確認なしで始まります。
echo.
echo  解除したいときは【ボタン起動を解除する】.bat を実行してください。
echo.
pause
