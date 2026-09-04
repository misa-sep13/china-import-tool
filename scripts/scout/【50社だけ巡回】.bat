@echo off
chcp 65001 > nul
cd /d "%~dp0"
title Seller Scout - Crawl 50
python --version > nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python is not installed  /  Python ga haitte imasen
  echo.
  echo  https://www.python.org/downloads/
  echo.
  echo  Check "Add python.exe to PATH" during install.
  echo.
  pause
  exit /b 1
)
python sync_server.py --limit 50
echo.
pause
