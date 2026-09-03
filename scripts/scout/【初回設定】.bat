@echo off
chcp 65001 > nul
cd /d "%~dp0"
title セラースカウト 初回設定

python --version > nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python が見つかりません。
  echo.
  echo  https://www.python.org/downloads/ から入れてください。
  echo  インストール画面の「Add python.exe to PATH」に
  echo  必ずチェックを入れてください。
  echo.
  echo  入れ終わったらパソコンを再起動して、もう一度この画面を開いてください。
  echo.
  pause
  exit /b 1
)

python -c "import playwright" > nul 2>&1
if errorlevel 1 (
  echo.
  echo  巡回に必要な部品を入れています。数分かかります。そのままお待ちください。
  echo.
  python -m pip install playwright
  echo.
)

python setup.py
echo.
pause
