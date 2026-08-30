@echo off
chcp 65001 > nul
cd /d "%~dp0"
python setup.py
echo.
pause
