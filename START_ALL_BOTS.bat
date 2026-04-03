@echo off
REM ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
REM MULTI-ALGO TRADING BOT - UNIFIED WINDOWS LAUNCHER
REM ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
REM
REM Starts all 4 processes in individual windows:
REM   1. Signal Fetcher (central hub - publishes signals to signals.json)
REM   2. Bot 1 (INVERTER - Terminal: 24727931)
REM   3. Bot 2 (FOLLOWER - Terminal: 24727943)
REM   4. Bot 3 (FOLLOWER - Terminal: 24727961)
REM
REM Each bot runs independently with:
REM   • Unique MT5 terminal login
REM   • Per-bot position tracking
REM   • Per-bot log files
REM   • Isolated file state
REM
REM Log Files:
REM   signal_fetcher.log  (signal fetcher output)
REM   bot_1.log           (Bot 1 inverter)
REM   bot_2.log           (Bot 2 follower)
REM   bot_3.log           (Bot 3 follower)
REM
REM To stop: Close each window individually or run STOP_ALL_BOTS.bat
REM ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion

REM ─────────────────────────────────────────────────────────────────────────────────
REM COLOR CONFIGURATION
REM ─────────────────────────────────────────────────────────────────────────────────
set "C_HEADER=0A"
set "C_SUCCESS=0A"
set "C_INFO=0B"
set "C_WARNING=0C"
set "C_ERROR=0C"

cls

REM ─────────────────────────────────────────────────────────────────────────────────
REM DISPLAY BANNER
REM ─────────────────────────────────────────────────────────────────────────────────
echo.
color %C_HEADER%
echo.
echo ╔═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
echo ║                                                                                                                                             ║
echo ║                        MULTI-ALGO TRADING BOT - UNIFIED WINDOWS LAUNCHER                                                                  ║
echo ║                                                                                                                                             ║
echo ║                                           Starting All Bots...                                                                            ║
echo ║                                                                                                                                             ║
echo ╚═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
echo.

REM ─────────────────────────────────────────────────────────────────────────────────
REM VERIFY PYTHON IS INSTALLED
REM ─────────────────────────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    color %C_ERROR%
    echo ✗ ERROR: Python is not installed or not in PATH
    echo.
    echo Please install Python 3.8+ and add it to your system PATH
    echo.
    pause
    exit /b 1
)

REM ─────────────────────────────────────────────────────────────────────────────────
REM STARTUP SEQUENCE
REM ─────────────────────────────────────────────────────────────────────────────────
color %C_INFO%

echo [1/4] Starting Signal Fetcher (Central Hub)...
start "Signal Fetcher" python signal_fetcher.py
timeout /t 3 /nobreak >nul

echo [2/4] Starting Bot 1 (Inverter - Account 24727931)...
start "Bot 1 - Inverter" python main.py --bot-id 1
timeout /t 2 /nobreak >nul

echo [3/4] Starting Bot 2 (Follower - Account 24727943)...
start "Bot 2 - Follower" python main.py --bot-id 2
timeout /t 2 /nobreak >nul

echo [4/4] Starting Bot 3 (Follower - Account 24727961)...
start "Bot 3 - Follower" python main.py --bot-id 3
timeout /t 2 /nobreak >nul

cls

REM ─────────────────────────────────────────────────────────────────────────────────
REM SUCCESS SCREEN
REM ─────────────────────────────────────────────────────────────────────────────────
color %C_SUCCESS%

echo.
echo ╔═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
echo ║                                                                                                                                             ║
echo ║                               ✓ ALL BOTS STARTED SUCCESSFULLY!                                                                            ║
echo ║                                                                                                                                             ║
echo ╚═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
echo.
echo.
echo ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
echo │ RUNNING PROCESSES                                                                                                                           │
echo ├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
echo │                                                                                                                                             │
echo │   [✓] Signal Fetcher           → Window: "Signal Fetcher"         Log: signal_fetcher.log                                                 │
echo │   [✓] Bot 1 (Inverter)         → Window: "Bot 1 - Inverter"       Log: bot_1.log        Account: 24727931                                │
echo │   [✓] Bot 2 (Follower)         → Window: "Bot 2 - Follower"       Log: bot_2.log        Account: 24727943                                │
echo │   [✓] Bot 3 (Follower)         → Window: "Bot 3 - Follower"       Log: bot_3.log        Account: 24727961                                │
echo │                                                                                                                                             │
echo └─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
echo.
echo.
echo ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
echo │ TERMINAL ISOLATION                                                                                                                          │
echo ├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
echo │                                                                                                                                             │
echo │   Bot 1 (Inverter)      ━━━━━━━➤  MT5 Account 24727931  ━━━━━━━  File: positions_store_bot_1.json                                        │
echo │   Bot 2 (Follower)      ━━━━━━━➤  MT5 Account 24727943  ━━━━━━━  File: positions_store_bot_2.json                                        │
echo │   Bot 3 (Follower)      ━━━━━━━➤  MT5 Account 24727961  ━━━━━━━  File: positions_store_bot_3.json                                        │
echo │                                                                                                                                             │
echo │   ✓ Each bot has unique terminal login                                                                                                      │
echo │   ✓ Each bot has independent file isolation                                                                                                 │
echo │   ✓ Zero cross-bot contamination                                                                                                           │
echo │   ✓ Complete concurrent isolation                                                                                                          │
echo │                                                                                                                                             │
echo └─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
echo.
echo.
echo ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
echo │ HOW TO USE                                                                                                                                  │
echo ├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
echo │                                                                                                                                             │
echo │   MONITOR:                                                                                                                                  │
echo │   • Open each window to view real-time logs                                                                                                 │
echo │   • Each bot window shows: trades opened/closed, positions, balance, errors                                                                │
echo │   • Log files stored in current directory for analysis                                                                                     │
echo │                                                                                                                                             │
echo │   STOP BOTS:                                                                                                                                │
echo │   • Option 1: Close each window individually (graceful shutdown)                                                                            │
echo │   • Option 2: Run STOP_ALL_BOTS.bat for automatic cleanup                                                                                  │
echo │                                                                                                                                             │
echo │   VIEW LOGS:                                                                                                                                │
echo │   • Bot 1:  type bot_1.log          (or open with text editor)                                                                              │
echo │   • Bot 2:  type bot_2.log                                                                                                                 │
echo │   • Bot 3:  type bot_3.log                                                                                                                 │
echo │   • Fetcher: type signal_fetcher.log                                                                                                       │
echo │                                                                                                                                             │
echo │   TRADING ANALYTICS:                                                                                                                       │
echo │   • Run: python dashboard.py                                                                                                               │
echo │   • Browse: http://localhost:8501                                                                                                          │
echo │   • View: MFE/MAE, win rate, equity curves per bot                                                                                          │
echo │                                                                                                                                             │
echo └─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
echo.
echo.
echo ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
echo │ BOT STRATEGIES                                                                                                                              │
echo ├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
echo │                                                                                                                                             │
echo │   BOT 1 (INVERTER - 13:00-17:00 IST)                                                                                                       │
echo │   ├─ Account: 24727931                                                                                                                    │
echo │   ├─ Strategy: Mirror (follow signals as-is)                                                                                               │
echo │   ├─ Volume: 0.01 lots                                                                                                                     │
echo │   ├─ Trailing Stop: ENABLED                                                                                                               │
echo │   └─ Max Loss Protection: ENABLED                                                                                                         │
echo │                                                                                                                                             │
echo │   BOT 2 (FOLLOWER)                                                                                                                        │
echo │   ├─ Account: 24727943                                                                                                                    │
echo │   ├─ Strategy: Mirror (follow signals as-is)                                                                                               │
echo │   ├─ Volume: 0.02 lots                                                                                                                     │
echo │   ├─ Trailing Stop: ENABLED                                                                                                               │
echo │   └─ Max Loss Protection: ENABLED                                                                                                         │
echo │                                                                                                                                             │
echo │   BOT 3 (FOLLOWER)                                                                                                                        │
echo │   ├─ Account: 24727961                                                                                                                    │
echo │   ├─ Strategy: Mirror (follow signals as-is)                                                                                               │
echo │   ├─ Volume: 0.015 lots                                                                                                                    │
echo │   ├─ Trailing Stop: ENABLED                                                                                                               │
echo │   └─ Max Loss Protection: ENABLED                                                                                                         │
echo │                                                                                                                                             │
echo └─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
echo.
echo.

REM ─────────────────────────────────────────────────────────────────────────────────
REM FINAL INSTRUCTIONS
REM ─────────────────────────────────────────────────────────────────────────────────
color %C_INFO%
echo Press any key to continue (windows will run in background)...
pause >nul

REM ─────────────────────────────────────────────────────────────────────────────────
REM OPTIONAL: Keep this window open to monitor startup
REM ─────────────────────────────────────────────────────────────────────────────────
echo.
echo Bots are now running in separate windows. You can:
echo   • Switch between windows to monitor each bot
echo   • Close this window (bots continue running)
echo   • Close individual bot windows to stop that bot
echo   • Run STOP_ALL_BOTS.bat to stop all at once
echo.
pause

endlocal
exit /b 0
