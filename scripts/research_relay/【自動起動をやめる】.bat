@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 自動起動の解除
python autostart.py --off
pause
