<#
.SYNOPSIS
    一键启动 FinRAG 本地前后端联调环境（基础设施 + 后端 + 前端）。

.DESCRIPTION
    1) deploy/docker-compose.infra.yml 起 MySQL(3307) / Milvus(19530) / MinIO / etcd / Attu(3000)
    2) backend：uvicorn app.main:app --reload --port 8002（只监听 app/，避免 .venv 变更触发重启）
    3) frontend：vite dev --port 5173（/api 代理到 127.0.0.1:8002）

    端口说明：本机 8000 可能被其他 uvicorn/服务占用，故联调默认使用 8002；
    如需改端口，用 -BackendPort 并同步修改 frontend/vite.config.js 的 proxy target。

    注意：Docker CLI 与 esbuild/uvicorn --reload 都需要命名管道，
    因此请在普通 PowerShell 窗口中运行本脚本，不要在受限沙箱里运行。

.EXAMPLE
    pwsh -File scripts/dev-start.ps1
    pwsh -File scripts/dev-start.ps1 -SkipInfra          # 只重启应用进程
    pwsh -File scripts/dev-start.ps1 -BackendPort 8000   # 换回 8000（需同步 vite proxy）
#>
[CmdletBinding()]
param(
    [switch]$SkipInfra,
    [int]$BackendPort = 8002,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

Write-Host "== FinRAG 联调环境 ==" -ForegroundColor Cyan
Write-Host "仓库根目录：$root"

# ---------------------------------------------------------------- 1. 基础设施
if (-not $SkipInfra) {
    Write-Host "`n[1/3] 启动基础设施（MySQL / Milvus / MinIO / etcd / Attu）..." -ForegroundColor Yellow
    Push-Location (Join-Path $root 'deploy')
    try {
        docker compose -f docker-compose.infra.yml up -d
    }
    finally {
        Pop-Location
    }
    Write-Host "等待 MySQL / Milvus 变为 healthy ..."
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 5
        $mysql = docker inspect --format '{{.State.Health.Status}}' finrag-mysql 2>$null
        $milvus = docker inspect --format '{{.State.Health.Status}}' finrag-milvus 2>$null
        Write-Host ("  mysql={0} milvus={1}" -f $mysql, $milvus)
    } while ((($mysql -ne 'healthy') -or ($milvus -ne 'healthy')) -and (Get-Date) -lt $deadline)
}
else {
    Write-Host "`n[1/3] 跳过基础设施启动（-SkipInfra）" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------- 2. 后端
Write-Host "`n[2/3] 启动后端（http://127.0.0.1:$BackendPort）..." -ForegroundColor Yellow
$backendDir = Join-Path $root 'backend'
$python = Join-Path $backendDir '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "未找到虚拟环境：$python`n请先执行：py -3.10 -m venv backend\.venv 并安装依赖（见 docs/12）。"
}
if (Test-Port $BackendPort) {
    Write-Host ("  端口 {0} 已被占用，跳过启动（如需重启请先运行 scripts/dev-stop.ps1）" -f $BackendPort) -ForegroundColor DarkYellow
}
else {
    $backendArgs = @(
        '-m', 'uvicorn', 'app.main:app',
        '--host', '127.0.0.1', '--port', "$BackendPort",
        '--reload', '--reload-dir', 'app'
    )
    $p = Start-Process -FilePath $python -ArgumentList $backendArgs `
        -WorkingDirectory $backendDir `
        -RedirectStandardOutput (Join-Path $logDir 'backend.out.log') `
        -RedirectStandardError (Join-Path $logDir 'backend.err.log') `
        -WindowStyle Hidden -PassThru
    Write-Host ("  后端 PID={0}，日志 logs\backend.out.log / backend.err.log" -f $p.Id)
}

# ---------------------------------------------------------------- 3. 前端
Write-Host "`n[3/3] 启动前端（http://localhost:$FrontendPort）..." -ForegroundColor Yellow
$frontendDir = Join-Path $root 'frontend'
if (Test-Port $FrontendPort) {
    Write-Host ("  端口 {0} 已被占用，跳过启动" -f $FrontendPort) -ForegroundColor DarkYellow
}
else {
    # 让 Vite 代理指向同一个后端端口（frontend/vite.config.js 读取 LEXFIN_BACKEND_PORT）
    $env:LEXFIN_BACKEND_PORT = "$BackendPort"
    $npmArgs = @('/c', 'npm run dev')
    $p = Start-Process -FilePath 'cmd.exe' -ArgumentList $npmArgs `
        -WorkingDirectory $frontendDir `
        -RedirectStandardOutput (Join-Path $logDir 'frontend.out.log') `
        -RedirectStandardError (Join-Path $logDir 'frontend.err.log') `
        -WindowStyle Hidden -PassThru
    Write-Host ("  前端 PID={0}，日志 logs\frontend.out.log / frontend.err.log" -f $p.Id)
}

# ---------------------------------------------------------------- 4. 探活
Write-Host "`n== 探活 ==" -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 3
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/v1/health" -TimeoutSec 5
        if ($health.code -eq 0) {
            $ok = $true
            Write-Host ("  后端 OK：status={0}" -f $health.data.status) -ForegroundColor Green
            break
        }
    }
    catch { }
}
if (-not $ok) { Write-Host "  后端暂未就绪，请查看 logs\backend.err.log" -ForegroundColor Red }

$feOk = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$FrontendPort/" -TimeoutSec 5 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $feOk = $true; break }
    }
    catch { Start-Sleep -Seconds 3 }
}
Write-Host ("  前端 {0}：http://localhost:{1}/" -f $(if ($feOk) { 'OK' } else { '未就绪' }), $FrontendPort) `
    -ForegroundColor $(if ($feOk) { 'Green' } else { 'Red' })

Write-Host @"

入口：
  前端        http://localhost:$FrontendPort/       （默认管理员 admin / Admin@123）
  Swagger     http://127.0.0.1:$BackendPort/docs
  健康检查    http://127.0.0.1:$BackendPort/api/v1/health
  Attu        http://localhost:3000
  MinIO 控制台 http://localhost:9001               （minioadmin / minioadmin）

停止：pwsh -File scripts/dev-stop.ps1
"@ -ForegroundColor Cyan
