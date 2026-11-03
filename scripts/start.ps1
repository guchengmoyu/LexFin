<#
.SYNOPSIS
    LexFin 一键启动脚本（默认全栈容器模式；-Mode dev 切到本地开发模式）。

.DESCRIPTION
    默认（-Mode stack）：
      1) 检测 Docker 引擎；未启动则自动拉起 Docker Desktop 并等待就绪
      2) 若基础设施工况（infra 栈）占用了容器名，先将其停掉（数据卷保留）
      3) docker compose up -d（镜像缺失或传 -Build 时自动构建）
      4) 等待 backend healthy，探活 /api/v1/health，打印数据规模
      5) 打开浏览器 http://localhost:8080

    -Mode dev（改代码热更新）：
      1) 仅起基础设施（MySQL / Milvus / MinIO / etcd）
      2) 若全栈容器在跑，先停掉 backend/frontend，避免两个后端同时写库
      3) 调用 scripts/dev-start.ps1：uvicorn 8002 + vite 5173
      4) 打开浏览器 http://localhost:5173

    注意：Docker CLI 需要命名管道，请在普通 PowerShell / 双击 .cmd 运行，
    不要在受限沙箱里运行。

.EXAMPLE
    powershell -File scripts/start.ps1                  # 全栈，自动开浏览器
    powershell -File scripts/start.ps1 -Mode dev        # 开发模式
    powershell -File scripts/start.ps1 -Build           # 强制重建镜像
    powershell -File scripts/start.ps1 -NoOpen          # 只起服务，不开浏览器
#>
[CmdletBinding()]
param(
    [ValidateSet('stack', 'dev')]
    [string]$Mode = 'stack',
    [switch]$Build,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'

# 统一按 UTF-8 输出，避免中文在重定向到日志/其他终端时乱码
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
}
catch { }

$root = Split-Path -Parent $PSScriptRoot
$deployDir = Join-Path $root 'deploy'
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# ---------------------------------------------------------------- 工具函数
function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Write-Ok([string]$Text) { Write-Host "    [OK] $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "    [!!] $Text" -ForegroundColor Yellow }
function Write-Fail([string]$Text) { Write-Host "    [XX] $Text" -ForegroundColor Red }

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-DockerEngine {
    try {
        $v = & docker version --format '{{.Server.Version}}' 2>$null
        return (-not [string]::IsNullOrWhiteSpace($v))
    }
    catch {
        return $false
    }
}

function Get-DockerDesktopExe {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Docker\Docker Desktop.exe')
    )
    foreach ($p in $candidates) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    try {
        $key = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Docker Desktop.exe'
        if (Test-Path $key) { return (Get-ItemProperty -Path $key).'(default)' }
    }
    catch { }
    return $null
}

function Start-DockerEngine {
    if (Test-DockerEngine) { Write-Ok "Docker 引擎已在运行"; return }

    $exe = Get-DockerDesktopExe
    if (-not $exe) {
        Write-Fail "未找到 Docker Desktop，请先安装：https://www.docker.com/products/docker-desktop/"
        throw "Docker Desktop 未安装"
    }

    Write-Warn "Docker 引擎未运行，正在启动：$exe"
    Start-Process -FilePath $exe -WindowStyle Minimized | Out-Null

    $deadline = (Get-Date).AddMinutes(4)
    $tick = 0
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        $tick++
        if (Test-DockerEngine) {
            Write-Ok "Docker 引擎已就绪（约 $($tick * 5) 秒）"
            return
        }
        if ($tick % 6 -eq 0) { Write-Host "    仍在等待 Docker 引擎启动…（$($tick * 5)s）" -ForegroundColor DarkGray }
    }
    throw "等待 Docker 引擎超时（4 分钟）。请手动打开 Docker Desktop 后重试。"
}

function Read-EnvValue([string]$File, [string]$Key, [string]$Default) {
    if (-not (Test-Path $File)) { return $Default }
    $line = Get-Content -Path $File -Encoding UTF8 -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^\s*[#]?\s*$([regex]::Escape($Key))\s*=" } |
        Select-Object -Last 1
    if (-not $line) { return $Default }
    $val = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'")
    if ([string]::IsNullOrWhiteSpace($val)) { return $Default }
    return $val
}

function Wait-ContainerHealthy([string]$Name, [int]$TimeoutSec = 300) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $last = ''
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        $state = & docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $Name 2>$null
        if ($state -ne $last) {
            Write-Host ("    {0}: {1}" -f $Name, $state) -ForegroundColor DarkGray
            $last = $state
        }
        if ($state -eq 'healthy') { return $true }
        if ($state -eq 'exited' -or $state -eq 'dead') { return $false }
        Start-Sleep -Seconds 3
    }
    return $false
}

function Wait-HttpOk([string]$Url, [int]$TimeoutSec = 120) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        try {
            $r = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing
            if ($r.StatusCode -eq 200) { return $true }
        }
        catch { }
        Start-Sleep -Seconds 3
    }
    return $false
}

function Open-Browser([string]$Url) {
    if ($NoOpen) { Write-Host "    （-NoOpen）请自行打开：$Url" -ForegroundColor DarkGray; return }
    Start-Process $Url | Out-Null
    Write-Ok "已打开浏览器：$Url"
}

function Invoke-Compose([string]$ComposeFile, [string[]]$ComposeArgs) {
    Push-Location $deployDir
    try {
        & docker compose -f $ComposeFile @ComposeArgs
        if ($LASTEXITCODE -ne 0) { throw "docker compose $($ComposeArgs -join ' ') 失败（exit $LASTEXITCODE）" }
    }
    finally {
        Pop-Location
    }
}

# ---------------------------------------------------------------- 开始
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "   LexFin 金融制度知识问答 · 一键启动" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "仓库：$root"
Write-Host "模式：$(if ($Mode -eq 'stack') { '全栈容器（演示/验收推荐）' } else { '本地开发（改代码热更新）' })"

Write-Step "1/4 检查 Docker"
if (-not (Test-Command 'docker')) {
    Write-Fail "未找到 docker 命令，请安装并启动 Docker Desktop 后重试。"
    throw "docker 不可用"
}
Start-DockerEngine
if (-not (& docker compose version 2>$null)) {
    Write-Fail "docker compose 插件不可用，请升级 Docker Desktop 到 4.x 以上。"
    throw "docker compose 不可用"
}
Write-Ok ("docker {0}" -f (& docker version --format '{{.Server.Version}}' 2>$null))

Write-Step "2/4 准备配置文件"
$envFile = Join-Path $deployDir '.env'
$envExample = Join-Path $deployDir '.env.example'
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Warn "deploy/.env 不存在，已从 .env.example 复制；请检查其中的 LLM_API_KEY 后重跑。"
    }
    else {
        Write-Fail "deploy/.env 缺失且无 .env.example，无法启动。"
        throw "缺少 deploy/.env"
    }
}
else {
    Write-Ok "deploy/.env 已存在"
}

$frontendPort = [int](Read-EnvValue $envFile 'FRONTEND_HOST_PORT' '8080')
$backendPort = [int](Read-EnvValue $envFile 'BACKEND_HOST_PORT' '8000')

# ---------------------------------------------------------------- 全栈模式
if ($Mode -eq 'stack') {

    Write-Step "3/4 启动全栈服务（MySQL / Milvus / MinIO / etcd / backend / frontend）"

    # 若本地开发进程（uvicorn 8002 / vite 5173）还在跑，先停掉，避免两个后端同时写库
    $devStop = Join-Path $PSScriptRoot 'dev-stop.ps1'
    if (Test-Path $devStop) {
        $devListen = Get-NetTCPConnection -LocalPort 8002, 5173 -State Listen -ErrorAction SilentlyContinue
        if ($devListen) {
            Write-Warn "检测到本地开发进程（8002/5173），先停掉它们（数据不受影响）"
            & $devStop *> $null
        }
    }

    Push-Location $deployDir
    try {
        $infraIds = & docker compose -f docker-compose.infra.yml ps -a -q 2>$null
        if ($infraIds) {
            Write-Warn "检测到基础设施工况（infra 栈）占用容器名，先停掉它（./volumes 数据保留）"
            & docker compose -f docker-compose.infra.yml down
        }
    }
    finally {
        Pop-Location
    }

    $needBuild = $Build.IsPresent
    if (-not $needBuild) {
        & docker image inspect 'finrag-backend:1.0.0' *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "未找到 finrag-backend:1.0.0 镜像，首次启动需要构建（约 10~15 分钟，pip 走清华源）"
            $needBuild = $true
        }
    }

    if ($needBuild) {
        Invoke-Compose 'docker-compose.yml' @('up', '-d', '--build')
    }
    else {
        Invoke-Compose 'docker-compose.yml' @('up', '-d')
    }
    Write-Ok "compose 已下发"

    Write-Host "    等待 backend 就绪（首次启动需加载 BGE 权重，约 1~2 分钟）…" -ForegroundColor DarkGray
    if (-not (Wait-ContainerHealthy 'finrag-backend' 420)) {
        Write-Fail "backend 未在 7 分钟内变为 healthy，最近日志："
        Push-Location $deployDir
        try { & docker compose -f docker-compose.yml logs --tail 40 backend } finally { Pop-Location }
        throw "backend 启动失败"
    }
    Write-Ok "finrag-backend healthy"

    Write-Step "4/4 探活与自检"
    $apiBase = "http://localhost:$frontendPort/api/v1"
    if (-not (Wait-HttpOk "$apiBase/health" 120)) {
        Write-Fail "接口未响应：$apiBase/health"
        throw "探活失败"
    }

    try {
        $h = Invoke-RestMethod -Uri "$apiBase/health" -TimeoutSec 10
        $d = $h.data
        $dep = $d.dependencies
        Write-Ok ("health ok | status={0} | embedding={1}({2}d) | llm={3} | 向量实体={4}" -f `
                $d.status, $dep.embedding.provider, $dep.embedding.dim, $dep.llm.model, $dep.milvus.entities)
        if ($dep.embedding.provider -eq 'fake') {
            Write-Warn "embedding 当前为 fake（哈希伪向量），与库中 BGE 1024 维向量不匹配，检索会失真；请把 deploy/.env 的 EMBEDDING_PROVIDER 改为 local 后 docker compose up -d backend"
        }
    }
    catch {
        Write-Warn "health 解析失败（不影响使用）：$($_.Exception.Message)"
    }

    $frontendOk = Wait-HttpOk "http://localhost:$frontendPort/" 60
    Write-Ok ("前端首页 http://localhost:{0}/ {1}" -f $frontendPort, $(if ($frontendOk) { '可访问' } else { '暂不可访问' }))

    Write-Host ""
    Write-Host "================ 启动完成 ================" -ForegroundColor Green
    Write-Host ("  系统入口    http://localhost:{0}/" -f $frontendPort) -ForegroundColor Green
    Write-Host "  登录账号    admin / Admin@123"
    Write-Host ("  接口文档    http://localhost:{0}/docs" -f $backendPort)
    Write-Host ("  健康检查    http://localhost:{0}/api/v1/health" -f $frontendPort)
    Write-Host "  Attu        http://localhost:3000   （docker compose --profile tools up -d attu）"
    Write-Host "  MinIO 控制台 http://localhost:9001   （minioadmin / minioadmin）"
    Write-Host ""
    Write-Host "  查看日志    docker compose -f deploy/docker-compose.yml logs -f backend" -ForegroundColor DarkGray
    Write-Host "  停止服务    双击 停止LexFin.cmd" -ForegroundColor DarkGray
    Write-Host "  提示        首次提问约 10~20 秒（冷启动加载模型），之后 1~3 秒" -ForegroundColor DarkGray
    Write-Host "==========================================" -ForegroundColor Green

    Open-Browser "http://localhost:$frontendPort/"
    return
}

# ---------------------------------------------------------------- 开发模式
Write-Step "3/4 启动基础设施 + 应用进程（dev）"
Push-Location $deployDir
try {
    # 全栈栈与基础设施工况共用容器名（finrag-mysql 等），必须先把全栈栈整体停掉，
    # 否则 dev-start 的 infra compose 会因容器名冲突失败。
    $stackIds = & docker compose -f docker-compose.yml ps -a -q 2>$null
    if ($stackIds) {
        Write-Warn "全栈容器与基础设施工况共用容器名，先停掉全栈栈（deploy/volumes 与 data/ 数据保留）"
        & docker compose -f docker-compose.yml down --remove-orphans
    }
}
finally {
    Pop-Location
}

$devStart = Join-Path $PSScriptRoot 'dev-start.ps1'
if (-not (Test-Path $devStart)) { throw "缺少 scripts/dev-start.ps1" }
& $devStart -BackendPort 8002 -FrontendPort 5173

Write-Step "4/4 探活"
if (Wait-HttpOk 'http://127.0.0.1:8002/api/v1/health' 120) {
    Write-Ok "后端 health ok（http://127.0.0.1:8002）"
}
else {
    Write-Fail "后端未就绪，请查看 logs/backend.err.log"
}

Write-Host ""
Write-Host "================ 启动完成（开发模式） ================" -ForegroundColor Green
Write-Host "  前端（热更新） http://localhost:5173/"
Write-Host "  后端 API       http://127.0.0.1:8002/docs"
Write-Host "  Attu           http://localhost:3000"
Write-Host "  账号           admin / Admin@123"
Write-Host ""
Write-Host "  改前端代码即时生效；改后端代码 uvicorn 自动重载（只监听 backend/app）。" -ForegroundColor DarkGray
Write-Host "  停止：脚本 停止LexFin.cmd 或 pwsh -File scripts/dev-stop.ps1" -ForegroundColor DarkGray
Write-Host "====================================================" -ForegroundColor Green

Open-Browser "http://localhost:5173/"
