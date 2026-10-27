<#
.SYNOPSIS
    FinRAG 联调环境体检 / 修复：容器、后端健康、文档与任务状态、知识点统计。

.DESCRIPTION
    1) 打印 Docker 容器状态
    2) 调 /api/v1/health 看 MySQL / Milvus / LLM / Embedding
    3) 统计文档：ready / pending / failed 各多少、切片总数
    4) 列出未完成（queued/parsing/embedding）的入库任务
    5) -Reparse：对「状态不是 ready 且 chunk_count=0」的文档重新触发解析，并轮询直到完成
    6) 打印知识点总数 / 已发布 / 已通过

.EXAMPLE
    pwsh -File scripts/dev-status.ps1
    pwsh -File scripts/dev-status.ps1 -Reparse          # 自动补跑卡住的文档
    pwsh -File scripts/dev-status.ps1 -Reparse -TimeoutMinutes 20
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:8002',
    [string]$Username = 'admin',
    [string]$Password = 'Admin@123',
    [switch]$Reparse,
    [int]$TimeoutMinutes = 15
)

$ErrorActionPreference = 'Stop'
$api = "$BaseUrl/api/v1"

Write-Host "== 1/5 Docker 容器 ==" -ForegroundColor Cyan
docker ps --format "table {{.Names}}\t{{.Status}}" 2>&1 | Select-Object -First 8

Write-Host "`n== 2/5 后端健康 ==" -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod -Uri "$api/health" -TimeoutSec 20
    $h = $health.data
    Write-Host ("  状态={0}  MySQL={1}  Milvus={2}({3} 实体)  LLM={4}/{5}  Embedding={6}" -f `
            $h.status, $h.dependencies.mysql.status, $h.dependencies.milvus.status, `
            $h.dependencies.milvus.entities, $h.dependencies.llm.provider, $h.dependencies.llm.model, `
            $h.dependencies.embedding.provider)
}
catch {
    Write-Host "  后端不可达：$BaseUrl（先运行 scripts/dev-start.ps1）" -ForegroundColor Red
    exit 1
}

Write-Host "`n== 3/5 登录并读取文档 ==" -ForegroundColor Cyan
$login = Invoke-RestMethod -Uri "$api/auth/login" -Method Post `
    -ContentType 'application/json; charset=utf-8' `
    -Body (@{ username = $Username; password = $Password } | ConvertTo-Json)
$token = $login.data.access_token
$headers = @{ Authorization = "Bearer $token" }

$docs = (Invoke-RestMethod -Uri "$api/documents?page=1&size=100" -Headers $headers).data
$byStatus = $docs.items | Group-Object status | ForEach-Object { "$($_.Name)=$($_.Count)" }
$chunkSum = ($docs.items | Measure-Object -Property chunk_count -Sum).Sum
Write-Host ("  文档 {0} 个（{1}），切片合计 {2}" -f $docs.total, ($byStatus -join ' '), $chunkSum)
$docs.items | Where-Object { $_.status -ne 'ready' } |
    Select-Object id, title, status, chunk_count | Format-Table -AutoSize

Write-Host "== 4/5 未完成任务 ==" -ForegroundColor Cyan
$tasks = (Invoke-RestMethod -Uri "$api/tasks?page=1&size=50" -Headers $headers).data.items
$running = $tasks | Where-Object { $_.status -notin @('success', 'failed') }
if ($running) {
    $running | Select-Object task_no, document_id, status, progress, total_chunks | Format-Table -AutoSize
}
else {
    Write-Host "  无进行中的任务" -ForegroundColor Green
}

if ($Reparse) {
    $stuck = $docs.items | Where-Object { $_.status -ne 'ready' -and [int]$_.chunk_count -eq 0 }
    if (-not $stuck) {
        Write-Host "  没有需要补跑的文档" -ForegroundColor Green
    }
    else {
        Write-Host ("`n== 补跑解析：{0} 个文档 ==" -f $stuck.Count) -ForegroundColor Yellow
        $pending = @{}
        foreach ($d in $stuck) {
            $r = Invoke-RestMethod -Uri "$api/documents/$($d.id)/reparse" -Method Post -Headers $headers
            $taskNo = $r.data.task_no
            $pending[$taskNo] = $d.id
            Write-Host ("  doc {0} {1} -> task {2}" -f $d.id, $d.title, $taskNo)
            Start-Sleep -Seconds 2
        }
        $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
        while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 15
            foreach ($taskNo in @($pending.Keys)) {
                $t = (Invoke-RestMethod -Uri "$api/tasks/$taskNo" -Headers $headers).data
                Write-Host ("    {0} doc={1} {2}/{3}" -f $taskNo, $pending[$taskNo], $t.status, $t.progress)
                if ($t.status -in @('success', 'failed')) {
                    if ($t.status -eq 'failed') { Write-Host ("      失败：{0}" -f $t.error_message) -ForegroundColor Red }
                    $pending.Remove($taskNo)
                }
            }
        }
        if ($pending.Count -gt 0) {
            Write-Host "  仍有任务未完成，可稍后再跑一次本脚本" -ForegroundColor DarkYellow
        }
    }
}

Write-Host "`n== 5/5 知识点统计 ==" -ForegroundColor Cyan
$stats = (Invoke-RestMethod -Uri "$api/knowledge-points/stats" -Headers $headers).data
Write-Host ("  总数={0}  草稿={1}  已发布={2}  无来源={3}  覆盖率={4}" -f `
        $stats.total, $stats.draft, $stats.published, $stats.without_source, $stats.coverage_rate)

Write-Host "`n完成。" -ForegroundColor Green
