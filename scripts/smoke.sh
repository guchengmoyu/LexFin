#!/usr/bin/env bash
# =============================================================================
#  冒烟测试（docs/09 §8）：发版前 30 秒快速确认核心链路可用。
#  顺序：健康检查 → 登录 → 建知识点 → 检索 → 问答 → 校验响应码，
#  任一步失败即退出非零。
#
#  用法：BASE_URL=http://localhost:8000/api/v1 ./scripts/smoke.sh [admin_password]
# =============================================================================
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000/api/v1}"
USERNAME="${USERNAME:-admin}"
PASSWORD="${1:-Admin@123}"

say() { printf '\n== %s ==\n' "$1"; }
fail() { printf '❌ %s\n' "$1"; exit 1; }

say "1/6 健康检查"
STATUS=$(curl -fsS "$BASE_URL/health" | grep -o '"status":"[a-z]*"' | head -1 || true)
[ -n "$STATUS" ] || fail "健康检查无响应"
echo "  $STATUS"

say "2/6 登录"
TOKEN=$(curl -fsS -X POST "$BASE_URL/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" \
  | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
[ -n "$TOKEN" ] || fail "登录失败"
echo "  token 获取成功"

AUTH="Authorization: Bearer $TOKEN"

say "3/6 知识库列表"
curl -fsS -H "$AUTH" "$BASE_URL/kb" | grep -q '"code":0' || fail "知识库列表异常"
echo "  ok"

say "4/6 新建知识点"
KP_RESP=$(curl -fsS -X POST "$BASE_URL/knowledge-points" -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{"kb_id":1,"title":"冒烟测试：流动性覆盖率最低监管要求","content":"商业银行的流动性覆盖率应当不低于100%，该结论仅用于冒烟测试。","category":"banking","sub_category":"流动性风险","status":"draft"}')
echo "$KP_RESP" | grep -q '"code":0' || fail "新建知识点失败"
KP_ID=$(echo "$KP_RESP" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
echo "  知识点 id=$KP_ID"

say "5/6 混合检索"
curl -fsS -X POST "$BASE_URL/retrieve" -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{"query":"流动性覆盖率最低要求","mode":"hybrid","top_k":5}' | grep -q '"code":0' \
  || fail "检索失败"
echo "  ok"

say "6/6 问答（非流式）"
curl -fsS -X POST "$BASE_URL/qa/ask" -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{"question":"商业银行流动性覆盖率的最低要求是多少？","stream":false}' | grep -q '"code":0' \
  || fail "问答失败"
echo "  ok"

say "✅ 冒烟测试全部通过"
