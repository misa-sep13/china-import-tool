@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo  50社だけ巡回します（15分ほど）。
echo  Amazonからログアウトしているか確認してください。
echo.
pause
python sync_server.py --limit 50
echo.
pause
