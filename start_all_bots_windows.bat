@echo off
REM ═══════════════════════════════════════════════════════════════════════════════
REM START ALL BOTS - Windows Batch Launcher
REM ═══════════════════════════════════════════════════════════════════════════════
REM
REM Starts all 4 processes in background:
REM 1. Signal Fetcher (central hub)
REM 2. Bot 1 (Inverter - 13:00-17:00 IST)
REM 3. Bot 2 (Follower)
REM 4. Bot 3 (Follower)
REM
REM Usage:
REM   start_all_bots.bat              # Start all bots
REM   start_all_bots.bat --test       # Test mode
REM
REM This will start all processes in background windows.
REM To stop all bots: Close each window or run stop_all_bots.bat
REM ═══════════════════════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion

echo.
echo ╔════════════════════════════════════════════════════════════════════╗
echo ║       MULTI-ALGO TRADING BOT - WINDOWS LAUNCHER                   ║
echo ╚════════════════════════════════════════════════════════════════════╝
echo.
echo Starting all bots...
echo.

REM Create individual windows for each process
echo [1/4] Starting Signal Fetcher...
start "Signal Fetcher" cmd /k python signal_fetcher.py

timeout /t 2 /nobreak

echo [2/4] Starting Bot 1 (Inverter)...
start "Bot 1 - Inverter" cmd /k python main.py --bot-id 1

timeout /t 1 /nobreak

echo [3/4] Starting Bot 2 (Follower)...
start "Bot 2 - Follower" cmd /k python main.py --bot-id 2

timeout /t 1 /nobreak

echo [4/4] Starting Bot 3 (Follower)...
start "Bot 3 - Follower" cmd /k python main.py --bot-id 3

echo.
echo ╔════════════════════════════════════════════════════════════════════╗
echo ║ ✓ All bots started in background windows!                         ║
echo ║                                                                    ║
echo ║ Running Processes:                                                ║
echo ║  • Signal Fetcher: signal_fetcher.log                             ║
echo ║  • Bot 1 (Inverter): bot_1.log                                    ║
echo ║  • Bot 2 (Follower): bot_2.log                                    ║
echo ║  • Bot 3 (Follower): bot_3.log                                    ║
echo ║                                                                    ║
echo ║ To stop:                                                          ║
echo ║  → Close each window individually, or                             ║
echo ║  → Run: stop_all_bots.bat                                         ║
echo ║                                                                    ║
echo ║ Terminal Identification:                                          ║
echo ║  • Bot 1 → Account 24727931                                       ║
echo ║  • Bot 2 → Account 24727943                                       ║
echo ║  • Bot 3 → Account 24727961                                       ║
echo ╚════════════════════════════════════════════════════════════════════╝
echo.

pause
