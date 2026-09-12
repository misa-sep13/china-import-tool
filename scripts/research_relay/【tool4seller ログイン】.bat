@echo off
chcp 65001 > nul
cd /d "%~dp0"
title tool4seller ログイン
python relay.py --login
pause
