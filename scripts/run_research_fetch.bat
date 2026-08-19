@echo off
rem Rakuten research candidate fetch, launched from Task Scheduler.
rem Keeps a log so failures can be diagnosed afterwards.
rem (Comments are ASCII on purpose: .bat is read in the OEM code page.)

setlocal
set ROOT=%~dp0..
set PY=C:\Users\misa\AppData\Local\Python\pythoncore-3.14-64\python.exe
set LOGDIR=%ROOT%\logs

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
set LOG=%LOGDIR%\research_%TODAY%.log

echo ==== start %DATE% %TIME% ==== >> "%LOG%"
rem -u flushes output immediately; buffered output hides progress until the end.
"%PY%" -u "%ROOT%\scripts\research_fetch_local.py" >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%
echo ==== end %DATE% %TIME% (exit=%RC%) ==== >> "%LOG%"

rem Drop logs older than 30 days.
forfiles /p "%LOGDIR%" /m research_*.log /d -30 /c "cmd /c del @path" 2>nul

exit /b %RC%
