@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 取り込みサーバー（閉じると止まります）
echo.
echo  競合リサーチシートの取り込みサーバーを起動します。
echo.
python relay.py
pause
