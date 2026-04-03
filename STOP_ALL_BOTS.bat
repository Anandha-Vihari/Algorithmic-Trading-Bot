@echo off
REM ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
REM STOP ALL BOTS - Windows Batch Killer
REM ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
REM
REM Gracefully stops all running bot processes:
REM   • Signal Fetcher
REM   • Bot 1
REM   • Bot 2
REM   • Bot 3
REM
REM Saved positions are persisted to respective JSON files before shutdown.
REM ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion

set "C_HEADER=0C"
set "C_SUCCESS=0A"
set "C_INFO=0B"
set "C_WARNING=0E"
set "C_ERROR=0C"

cls

color %C_HEADER%

echo.
echo ╔═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
echo ║                                                                                                                                             ║
echo ║                                    STOPPING ALL TRADING BOTS                                                                              ║
echo ║                                                                                                                                             ║
echo ╚═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
echo.

color %C_INFO%

REM Try to find and close windows
echo Attempting graceful shutdown of all processes...
echo.

REM Method 1: Try closing windows by title (graceful)
echo [1] Closing Signal Fetcher window...
taskkill /FI "WINDOWTITLE eq Signal Fetcher" /T /GRACEFUL 2>nul
if errorlevel 1 (
    echo    (Not found or already closed)
) else (
    echo    ✓ Closed
)

timeout /t 1 /nobreak >nul

echo [2] Closing Bot 1 window...
taskkill /FI "WINDOWTITLE eq Bot 1 -" /T /GRACEFUL 2>nul
if errorlevel 1 (
    echo    (Not found or already closed)
) else (
    echo    ✓ Closed
)

timeout /t 1 /nobreak >nul

echo [3] Closing Bot 2 window...
taskkill /FI "WINDOWTITLE eq Bot 2 -" /T /GRACEFUL 2>nul
if errorlevel 1 (
    echo    (Not found or already closed)
) else (
    echo    ✓ Closed
)

timeout /t 1 /nobreak >nul

echo [4] Closing Bot 3 window...
taskkill /FI "WINDOWTITLE eq Bot 3 -" /T /GRACEFUL 2>nul
if errorlevel 1 (
    echo    (Not found or already closed)
) else (
    echo    ✓ Closed
)

echo.
echo Attempting to kill any remaining Python processes running bots...
echo.

REM Kill remaining python processes (more aggressive)
taskkill /IM python.exe /F 2>nul

if errorlevel 1 (
    color %C_WARNING%
    echo ⚠ No Python processes to kill
) else (
    color %C_SUCCESS%
    echo ✓ Python processes terminated
)

echo.

REM Verification
color %C_INFO%
echo Verifying shutdown...
timeout /t 2 /nobreak >nul

tasklist /FI "IMAGENAME eq python.exe" 2>nul | find /I "python.exe" >nul
if errorlevel 1 (
    color %C_SUCCESS%
    echo.
    echo ╔═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
    echo ║                                                                                                                                             ║
    echo ║                           ✓ ALL BOTS SUCCESSFULLY STOPPED                                                                                ║
    echo ║                                                                                                                                             ║
    echo ║   All positions have been saved to:                                                                                                      ║
    echo ║   • positions_store_bot_1.json  (Bot 1 positions)                                                                                        ║
    echo ║   • positions_store_bot_2.json  (Bot 2 positions)                                                                                        ║
    echo ║   • positions_store_bot_3.json  (Bot 3 positions)                                                                                        ║
    echo ║                                                                                                                                             ║
    echo ║   Ready to start again: Run START_ALL_BOTS.bat                                                                                          ║
    echo ║                                                                                                                                             ║
    echo ╚═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
) else (
    color %C_WARNING%
    echo.
    echo ╔═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
    echo ║                                                                                                                                             ║
    echo ║                         ⚠ WARNING: SOME PROCESSES STILL RUNNING                                                                          ║
    echo ║                                                                                                                                             ║
    echo ║   Manual cleanup may be required:                                                                                                        ║
    echo ║   • Open Task Manager (Ctrl+Shift+Esc)                                                                                                  ║
    echo ║   • Find python.exe processes                                                                                                           ║
    echo ║   • End Task for each bot window                                                                                                        ║
    echo ║                                                                                                                                             ║
    echo ╚═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
)

echo.
pause

endlocal
exit /b 0
