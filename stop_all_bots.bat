@echo off
REM Stop all Multi Algo bot instances gracefully
REM Run: stop_all_bots.bat

echo.
echo ════════════════════════════════════════════════════════════════════
echo  MULTI ALGO TRADING SYSTEM - STOPPING ALL INSTANCES
echo ════════════════════════════════════════════════════════════════════
echo.

echo Terminating bot processes...
taskkill /F /FI "WINDOWTITLE eq Signal Fetcher*" 2>nul
taskkill /F /FI "WINDOWTITLE eq Bot 1*" 2>nul
taskkill /F /FI "WINDOWTITLE eq Bot 2*" 2>nul
taskkill /F /FI "WINDOWTITLE eq Bot 3*" 2>nul

echo.
echo ════════════════════════════════════════════════════════════════════
echo  All bots stopped
echo ════════════════════════════════════════════════════════════════════
echo.
pause
