@echo off
chcp 65001 > nul
cd /d "%~dp0"
title Seller Scout - Bookmarks from file
python --version > nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python is not installed  /  Python ga haitte imasen
  echo.
  echo  https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)
if "%~1"=="" (
  python push_sellers.py --help-html
  echo.
  pause
  exit /b 1
)
python push_sellers.py --html "%~1"
echo.
pause
