@echo off
chcp 65001 > nul
cd /d "%~dp0"
title Seller Scout - Bookmarks
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
python push_sellers.py
echo.
pause
