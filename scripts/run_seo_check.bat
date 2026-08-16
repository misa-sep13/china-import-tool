@echo off
rem Rakuten SEO ranking check, launched from Task Scheduler.
rem Keeps a log so failures can be diagnosed afterwards -- running python
rem directly left no trace, so a failed run went unnoticed for days.
rem (Comments are ASCII on purpose: .bat is read in the OEM code page.)

setlocal
set ROOT=%~dp0..
set PY=C:\Users\misa\AppData\Local\Python\pythoncore-3.14-64\python.exe
set LOGDIR=%ROOT%\logs

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
set LOG=%LOGDIR%\seo_%TODAY%.log

echo ==== start %DATE% %TIME% ==== >> "%LOG%"
rem -u flushes output immediately; buffered output hides progress until the end.
"%PY%" -u "%ROOT%\scripts\check_seo_rankings_local.py" >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%
echo ==== end %DATE% %TIME% (exit=%RC%) ==== >> "%LOG%"

rem Drop logs older than 30 days.
forfiles /p "%LOGDIR%" /m seo_*.log /d -30 /c "cmd /c del @path" 2>nul

exit /b %RC%
