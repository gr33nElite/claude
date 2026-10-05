@echo off
cd /d "%~dp0"
rem Shares TicketMgr with other computers on this network.
py --version >NUL 2>NUL
if %errorlevel%==0 (
    py -m ticketmgr serve --share
) else (
    python -m ticketmgr serve --share
)
pause
