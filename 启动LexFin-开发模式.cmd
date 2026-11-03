@echo off
rem LexFin one-click launcher (dev mode: uvicorn + vite hot reload).
title LexFin Dev Launcher
cd /d "%~dp0"
chcp 65001 >nul
set "PSEXE=powershell"
where pwsh >nul 2>nul && set "PSEXE=pwsh"
"%PSEXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Mode dev %*
echo.
echo Press any key to close this window...
pause >nul
