<#
.SYNOPSIS
    一键停止 LexFin：全栈容器 + 本地开发进程 + 基础设施（可选连 Docker Desktop 一起退出）。

.EXAMPLE
    powershell -File scripts/stop.ps1
    powershell -File scripts/stop.ps1 -StopDocker
#>
[CmdletBinding()]
param(
    [switch]$StopDocker
)

$ErrorActionPreference = 'Continue'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
}
catch { }

$root = Split-Path -Parent $PSScriptRoot
$deployDir = Join-Path $root 'deploy'

Write-Host "== 停止 LexFin ==" -ForegroundColor Cyan

# 1. 全栈容器（数据在 deploy/volumes 与仓库 data/，down 不删数据）
if (Test-Path $deployDir) {
    Push-Location $deployDir
    try {
        if (& docker compose version 2>$null) {
            $running = & docker compose -f docker-compose.yml ps -q 2>$null
            if ($running) {
                Write-Host "  停止全栈容器…" -ForegroundColor Yellow
                & docker compose -f docker-compose.yml down --remove-orphans
            }
            else {
                Write-Host "  全栈容器未运行" -ForegroundColor DarkGray
            }
        }
    }
    finally {
        Pop-Location
    }
}

# 2. 本地开发进程（uvicorn 8002 / vite 5173）
$devStop = Join-Path $PSScriptRoot 'dev-stop.ps1'
if (Test-Path $devStop) {
    & $devStop -IncludeInfra
}

# 3. 可选：退出 Docker Desktop（释放内存）
if ($StopDocker) {
    Write-Host ""
    Write-Host "  退出 Docker Desktop…" -ForegroundColor Yellow
    $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path $exe) {
        & $exe -Quit 2>$null
    }
    Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "已停止。" -ForegroundColor Green
