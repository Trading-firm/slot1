@echo off
title  Trading Bot
echo ============================================================
echo   STARTING  TRADING BOT
echo ============================================================
echo.

:: Change directory to the script's location
cd /d "%~dp0"

:: Check for virtual environment
if not exist venv (
    echo [ERROR] Virtual environment 'venv' not found!
    echo Please run the deployment steps in DEPLOYMENT.md first.
    pause
    exit /b
)

:: Activate virtual environment
call venv\Scripts\activate

:loop
echo [INFO] Launching bot...
python main.py run

echo.
echo [WARNING] Bot crashed or stopped. Restarting in 10 seconds...
echo Press Ctrl+C to stop the loop.
timeout /t 10
goto loop