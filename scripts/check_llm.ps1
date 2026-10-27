<#
.SYNOPSIS
    验证后端是否真的接上了真实 LLM（而不是联调用的 FakeLLM）。

.DESCRIPTION
    登录 → 调 `/qa/ask`（非流式，内部复用 SSE 链路）→ 打印模型名、token 用量、时延与答案。
    判定依据：`model_name` 是否为 `fake-llm`。真实模型应显示 `deepseek-chat` / `qwen-plus` 等。

.EXAMPLE
    pwsh -File scripts/check_llm.ps1
    pwsh -File scripts/check_llm.ps1 -Question "流动性覆盖率的监管标准是什么？"
    pwsh -File scripts/check_llm.ps1 -BaseUrl http://127.0.0.1:8002
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:8002',
    [string]$Question = '商业银行核心一级资本充足率的最低要求是多少？',
    [string]$Username = 'admin',
    [string]$Password = 'Admin@123'
)

$ErrorActionPreference = 'Stop'
$api = "$BaseUrl/api/v1"

Write-Host "== 1/3 健康检查 ==" -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod -Uri "$api/health" -TimeoutSec 10
}
catch {
    Write-Host "后端不可达：$BaseUrl（先跑 scripts/dev-start.ps1）" -ForegroundColor Red
    exit 1
}
$llm = $health.data.dependencies.llm
Write-Host ("  服务状态：{0}" -f $health.data.status)
Write-Host ("  LLM：provider={0} model={1} status={2}" -f $llm.provider, $llm.model, $llm.status)
if ($llm.degraded) { Write-Host ("  提示：{0}" -f $llm.degraded) -ForegroundColor Yellow }

Write-Host "`n== 2/3 登录 ==" -ForegroundColor Cyan
$login = Invoke-RestMethod -Uri "$api/auth/login" -Method Post `
    -ContentType 'application/json; charset=utf-8' `
    -Body (@{ username = $Username; password = $Password } | ConvertTo-Json)
if ($login.code -ne 0) {
    Write-Host "登录失败：$($login.message)" -ForegroundColor Red
    exit 1
}
$token = $login.data.access_token
$headers = @{ Authorization = "Bearer $token" }
Write-Host ("  {0}（{1}）" -f $login.data.user.username, $login.data.user.role)

Write-Host "`n== 3/3 提问（真实调用一次大模型） ==" -ForegroundColor Cyan
Write-Host ("  Q: {0}" -f $Question)
$body = @{
    question    = $Question
    mode        = 'hybrid'
    top_k       = 5
    use_history = $false
} | ConvertTo-Json

try {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $answer = Invoke-RestMethod -Uri "$api/qa/ask" -Method Post -Headers $headers `
        -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 120
    $sw.Stop()
}
catch {
    $detail = $_.ErrorDetails.Message
    Write-Host "  调用失败（HTTP $($_.Exception.Response.StatusCode.value__)）：" -ForegroundColor Red
    Write-Host $detail -ForegroundColor Red
    Write-Host "`n常见原因：LLM_API_KEY 未配置/无效、LLM_BASE_URL 不可达、模型名不对、超时（LLM_TIMEOUT）。" -ForegroundColor Yellow
    exit 1
}

$data = $answer.data
Write-Host ("  A: {0}" -f ($data.answer -replace "`n", ' '))
Write-Host ""
Write-Host ("  模型      : {0}" -f $data.model_name)
Write-Host ("  类型/置信 : {0} / {1}（{2}）" -f $data.answer_type, $data.confidence, $data.confidence_level)
Write-Host ("  时延      : 总 {0}ms（改写 {1} / 检索 {2} / 首token {3}）" -f `
        $data.latency_detail.total, $data.latency_detail.rewrite, `
        $data.latency_detail.retrieve, $data.latency_detail.llm_ttft)
Write-Host ("  耗时      : 客户端 {0}ms" -f $sw.ElapsedMilliseconds)
if ($data.token_usage) {
    Write-Host ("  tokens    : prompt={0} completion={1} total={2}" -f `
            $data.token_usage.prompt_tokens, $data.token_usage.completion_tokens, $data.token_usage.total_tokens)
}
Write-Host ("  引用      : {0} 条（{1}）" -f $data.citations.Count,
    (($data.citations | ForEach-Object { "$($_.doc_title)#$($_.article_no)" }) -join '；'))

Write-Host ""
if ($data.model_name -eq 'fake-llm') {
    Write-Host "结论：仍在用 FakeLLM（联调占位）。按 docs/12 §9 配置真实 LLM 后重启后端。" -ForegroundColor Yellow
    exit 2
}
Write-Host "结论：已接真实大模型，链路正常。" -ForegroundColor Green
