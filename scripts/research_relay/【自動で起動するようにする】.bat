@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 自動起動の設定
python autostart.py
pause
