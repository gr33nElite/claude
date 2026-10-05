@echo off
cd /d "%~dp0"
rem Prefer the Python launcher (py), which the python.org installer sets up.
py --version >NUL 2>NUL
if %errorlevel%==0 (
    py -m ticketmgr
) else (
    python -m ticketmgr
)
pause
