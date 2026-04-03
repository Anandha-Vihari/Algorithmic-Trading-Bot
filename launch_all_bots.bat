@echo off
REM Launch all Multi Algo bot instances with central signal fetcher
REM Run: launch_all_bots.bat

echo.
echo ════════════════════════════════════════════════════════════════════
echo  MULTI ALGO TRADING SYSTEM - LAUNCHING ALL INSTANCES
echo ════════════════════════════════════════════════════════════════════
echo.

REM Start signal fetcher in background (central process, required)
echo [1/4] Starting signal fetcher (central process)...
start "Signal Fetcher" cmd /k python signal_fetcher.py
timeout /t 2

REM Start bot instances in separate windows
echo [2/4] Starting Bot 1 (inverter mode, 13:00-17:00 IST)...
start "Bot 1" cmd /k python main.py --bot-id 1
timeout /t 1

echo [3/4] Starting Bot 2 (follower mode)...
start "Bot 2" cmd /k python main.py --bot-id 2
timeout /t 1

echo [4/4] Starting Bot 3 (follower mode)...
start "Bot 3" cmd /k python main.py --bot-id 3

echo.
echo ════════════════════════════════════════════════════════════════════
echo  All bots launched successfully!
echo ════════════════════════════════════════════════════════════════════
echo.
echo Checking logs and windows:
echo  - signal_fetcher.log   (central signal distribution)
echo  - bot_1.log            (Bot 1: inverter)
echo  - bot_2.log            (Bot 2: follower)
echo  - bot_3.log            (Bot 3: follower)
echo.
echo Press Ctrl+C in any window to stop individual bots
echo Or run: stop_all_bots.bat to terminate all instances
echo.
pause
