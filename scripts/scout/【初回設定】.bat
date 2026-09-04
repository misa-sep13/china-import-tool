@echo off
chcp 65001 > nul
cd /d "%~dp0"
title Seller Scout - Setup
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
python -c "import playwright" > nul 2>&1
if errorlevel 1 (
  echo  Installing required parts... please wait
  python -m pip install playwright
)
python setup.py
echo.
pause
