@echo off
rem LexFin one-click stop (containers + local dev processes).
title LexFin Stop
cd /d "%~dp0"
chcp 65001 >nul
set "PSEXE=powershell"
where pwsh >nul 2>nul && set "PSEXE=pwsh"
"%PSEXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1" %*
echo.
echo Press any key to close this window...
pause >nul
