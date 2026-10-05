@echo off
cd /d "%~dp0"
rem Fetch the latest TicketMgr and any new requirements. Your tickets in data\ are kept.
git pull
if errorlevel 1 (
    echo.
    echo Update failed. Is git installed, and was this folder set up with git clone?
    pause
    exit /b 1
)
py --version >NUL 2>NUL
if %errorlevel%==0 (
    py -m pip install -q -r requirements.txt
) else (
    python -m pip install -q -r requirements.txt
)
echo.
echo TicketMgr is up to date. Restart it to use the new version.
pause
