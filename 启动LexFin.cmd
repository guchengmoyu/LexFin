@echo off
rem LexFin one-click launcher (all-in-one containers). Chinese UI text lives in scripts\start.ps1.
title LexFin Launcher
cd /d "%~dp0"
chcp 65001 >nul
set "PSEXE=powershell"
where pwsh >nul 2>nul && set "PSEXE=pwsh"
"%PSEXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Mode stack %*
echo.
echo Press any key to close this window...
pause >nul
