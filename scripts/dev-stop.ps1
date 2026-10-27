<#
.SYNOPSIS
    停止 FinRAG 本地联调的应用进程（后端默认 8002 / 前端 5173）。

.DESCRIPTION
    仅停止本机 uvicorn / vite 进程；Docker 基础设施默认保留（-IncludeInfra 可一并停止）。

.EXAMPLE
    pwsh -File scripts/dev-stop.ps1
    pwsh -File scripts/dev-stop.ps1 -BackendPort 8000
    pwsh -File scripts/dev-stop.ps1 -IncludeInfra
#>
[CmdletBinding()]
param(
    [int]$BackendPort = 8002,
    [int]$FrontendPort = 5173,
    [switch]$IncludeInfra
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot

function Stop-ByPort([int]$Port, [string]$Name) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Sort-Object OwningProcess -Unique
    if (-not $conns) {
        Write-Host ("  {0}（端口 {1}）未在运行" -f $Name, $Port) -ForegroundColor DarkGray
        return
    }
    foreach ($procId in ($conns | Select-Object -ExpandProperty OwningProcess -Unique)) {
        try {
            $proc = Get-Process -Id $procId -ErrorAction Stop
            Write-Host ("  停止 {0}：PID={1} {2}" -f $Name, $proc.Id, $proc.ProcessName)
            Stop-Process -Id $proc.Id -Force
        }
        catch {
            Write-Host ("  无法停止 PID={0}：{1}" -f $procId, $_.Exception.Message) -ForegroundColor Red
            Write-Host ("    提示：该进程可能属于其他用户/会话，请在任务管理器中结束，或改用其他端口。" -f $procId) -ForegroundColor DarkYellow
        }
    }
}

Write-Host "== 停止 FinRAG 应用进程 ==" -ForegroundColor Cyan
Stop-ByPort $BackendPort '后端 uvicorn'
Stop-ByPort $FrontendPort '前端 vite'

# uvicorn --reload 会留下 reloader 子进程，按命令行兜底清理
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'uvicorn\s+app\.main:app' } |
    ForEach-Object {
        Write-Host ("  停止残留 reloader：PID={0}" -f $_.ProcessId)
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

if ($IncludeInfra) {
    Write-Host "`n== 停止 Docker 基础设施 ==" -ForegroundColor Yellow
    Push-Location (Join-Path $root 'deploy')
    try {
        docker compose -f docker-compose.infra.yml stop
    }
    finally {
        Pop-Location
    }
}

Write-Host "完成。" -ForegroundColor Green
