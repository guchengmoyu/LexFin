# scripts/ · 测试与评测脚本

本目录存放**纯 HTTP 客户端**形式的测试脚本：只依赖 Python 3.11+ 标准库 + `httpx` + `openpyxl`，
不 import 本项目 `app` 包，可对任意已部署实例（本地 Docker / 服务器）直接执行。

```bash
pip install httpx openpyxl
```

对应设计文档：

| 脚本 | 文档依据 | 用途 |
| --- | --- | --- |
| `eval_rag.py` | `docs/09-测试方案设计.md` §6.1/§6.2/§6.3、`docs/05-RAG核心链路设计.md` §13 | RAG 准确率评测（批量问答评测） |
| `bench_api.py` | `docs/09-测试方案设计.md` §5.1/§5.2/§5.3 | API 时延压测（T1/T2 分位数统计） |

两个脚本共用同一套接口约定（`docs/06-后端接口设计.md`）：

- 接口基地址 `{base_url}` 指 **`http://localhost:8000/api/v1`**（已含 `/api/v1` 前缀）；
- 登录 `POST /auth/login`（请求 `{username,password}`，响应 `data.access_token`），
  其余请求带 `Authorization: Bearer <token>`；
- 统一响应 `{code,message,data,request_id}`，`code != 0` 或 HTTP ≥ 400 均按失败处理并打印中文提示；
- SSE 事件流（`/qa/ask/stream`）自行解析：按空行切事件块、解析 `event:` / `data:` 行、
  `data` 为 JSON；`ping` 心跳忽略，`done` 结束，`error` 报错。

---

## 1. `eval_rag.py` — RAG 准确率评测

逐题调用 `POST /qa/ask`（加 `--stream` 走 SSE 并统计 TTFT），
自动计算 Hit@1/Hit@3/Hit@5、MRR@5、refusal_accuracy（拒答正确率）、
citation_rate（引用覆盖率）、latency_p50/p95（首 token 时延），
输出 JSON 报告（含每题明细）与可人工判分回填的 answers xlsx。

### 参数

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--dataset` | ✅ | 评测集 xlsx（`data/eval/eval_set.xlsx`），列：`qid/category/question/question_type/difficulty/expected_doc_no/expected_article_no/expected_key_points(\|分隔)/expected_answer_type` |
| `--base-url` | ✅ | 接口基地址，如 `http://localhost:8000/api/v1` |
| `--username` / `--password` | ✅* | 登录账号（*与 `--token` 二选一） |
| `--token` | | 直接提供 access_token，跳过登录 |
| `--mode` | | `keyword` / `vector` / `hybrid`（默认 `hybrid`） |
| `--rerank` | | 重排开关，如 `--rerank false`；不传则由服务端默认配置决定 |
| `--top-k` | | 问答检索 Top-K（1~10，默认 5） |
| `--batch-no` | | 评测批次号（默认自动生成 `EVAL-<时间戳>`） |
| `--out` | | JSON 报告路径（默认 `reports/eval_<batch>.json`） |
| `--export-answers` | | 导出 answers xlsx（人工判分回填用） |
| `--stream` | | 走 `/qa/ask/stream`（SSE），统计真实 TTFT |
| `--import-scores` | | 读取判分回填后的 answers xlsx，汇总 accuracy / Cohen's Kappa / 错误分布 |
| `--baseline` | | 历史评测 JSON，打印「与基线对比」 |
| `--no-retrieve` | | 跳过 `POST /retrieve`（不计算 Hit@N / MRR@5） |
| `--limit` / `--qid` | | 只评测部分题目（调试用） |
| `--kb-ids` / `--delay` / `--timeout` | | 知识库过滤 / 请求间隔 / 超时秒数 |

### 示例

```bash
python scripts/eval_rag.py \
  --dataset data/eval/eval_set.xlsx \
  --base-url http://localhost:8000/api/v1 \
  --username admin --password Admin@123 \
  --mode hybrid --rerank false --top-k 5 \
  --batch-no EVAL-20250601 \
  --out reports/eval_20250601.json \
  --export-answers reports/answers_20250601.xlsx
```

### 输出文件

| 文件 | 内容 | 对应交付物（docs/09 §10） |
| --- | --- | --- |
| `reports/eval_<batch>.json` | 汇总指标 + 每题明细（检索 Top-N、答案、引用、时延、自动指标、人工判分占位） | 评测报告 `reports/eval_*.json`（85% 准确率证据） |
| `reports/answers_<batch>.xlsx` | 答案明细：`question/answer/citations/doc_no/article_no` + 检索/时延列 + `review_*` 判分列 | 评测答案明细 `reports/answers_*.xlsx`（人工判分原始记录） |

### 指标口径（docs/09 §6.3）

- `hit@1/3/5`：`expected_doc_no + expected_article_no` 出现在 `POST /retrieve` Top-N 结果中；
  两者均未标注的题不计入该分母；
- `mrr@5`：正确条文排名倒数（≤5）的均值；
- `refusal_accuracy`：`expected_answer_type=refused` 的题被判为拒答的比例；
- `citation_rate`：`answer_type=answered` 的题中「答案含 `[n]` 角标且返回 ≥1 条引用」的比例；
- `latency_p50/p95`：首 token 时延——`--stream` 时为实测 TTFT，非流式时由
  `latency_detail`（rewrite+retrieve+rerank+llm_ttft）估算。

### 人工判分回填流程（docs/09 §6.2）

1. `--export-answers` 导出 answers xlsx；
2. 两名标注人独立填写 `review_a_correct` / `review_b_correct`（1/0 或 正确/错误）；
3. 分歧项由第三人裁决，填写 `review_final_correct` 与 `review_final_error_type`
   （`retrieval_miss` / `hallucination` / `citation_wrong` / `outdated` / `incomplete`）；
4. 加 `--import-scores reports/answers_xxx.xlsx` 重跑（或复用同一批次），控制台即输出
   「人工判分（已回填）：accuracy = … / Cohen's Kappa = … / 错误分布」；
   准确率分母不含拒答题。

---

## 2. `bench_api.py` — API 时延压测

预热 `--warmup`（默认 5）次后，对问题列表连续测量 `--repeat` 次（默认串行），
分别统计 T1 与 T2 的 P50/P90/P95/P99/max，输出控制台表格（含 ✅/❌ 达标判定）与 JSON 报告。

### 时延口径（docs/09 §5.1）

| 编号 | 口径 | 目标 |
| --- | --- | --- |
| T1 | `POST /retrieve`（或 `--t1-endpoint search` 走 `GET /search`）到完整接收响应体 | **P95 ≤ 500 ms** |
| T2 | `POST /qa/ask/stream` 到第一个 SSE 事件（忽略 `ping`；`meta` 或首个 `token` 取先到者） | **P95 ≤ 2000 ms** |
| T3 | 到 `done` 事件的完整回答时间（参考值，非硬性验收指标） | P95 ≤ 8 s |

### 参数

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--base-url` | ✅ | 接口基地址 |
| `--username` / `--password` | ✅* | 登录账号（*与 `--token` 二选一） |
| `--questions` | ✅* | 问题列表文件：`.txt` 一行一题（`#` 注释）或 `.xlsx` 的 `question` 列（*与 `--question` 至少一个） |
| `--question` | | 直接追加单个问题（可重复） |
| `--repeat` | | 每阶段测量次数（默认 **总采样数**，问题按列表轮询；`--per-question` 时为每题次数），默认 100 |
| `--out` | | JSON 报告路径（默认 `reports/bench_<时间戳>.json`） |
| `--warmup` | | 预热次数（默认 5，不计入统计） |
| `--concurrency` | | 并发数（asyncio + `httpx.AsyncClient`），默认 1 = 串行 |
| `--phase` | | `both` / `t1` / `t2`，默认 `both` |
| `--t1-endpoint` | | `retrieve`（POST /retrieve）或 `search`（GET /search） |
| `--per-question` | | 每题各测 `--repeat` 次 |
| `--mode` / `--top-k` / `--rerank` / `--kb-ids` | | 检索与问答参数 |
| `--interval` / `--timeout` | | 样本间隔秒 / 单请求超时秒 |
| `--t1-target-ms` / `--t2-target-ms` | | 达标阈值（默认 500 / 2000） |

### 示例

```bash
python scripts/bench_api.py \
  --base-url http://localhost:8000/api/v1 \
  --username admin --password Admin@123 \
  --questions data/eval/questions.txt \
  --repeat 100 \
  --out reports/bench_20250601.json

# 并发压测（docs/09 §5.3 NFR-04）
python scripts/bench_api.py --base-url http://localhost:8000/api/v1 \
  --username admin --password Admin@123 \
  --questions data/eval/questions.txt --repeat 200 --concurrency 20 \
  --out reports/bench_conc20.json
```

### 输出文件

| 文件 | 内容 | 对应交付物（docs/09 §10） |
| --- | --- | --- |
| `reports/bench_*.json` | T1/T2/T3 分位数、每次样本明细、`latency_detail` 分阶段耗时均值（rewrite/retrieve/rerank/llm_ttft/total + total_ttft）、回答质量抽样、失败样本 | 性能基准报告 `reports/bench_*.json`（NFR-01/02 证据） |

控制台输出对齐 docs/09 §5.2 示例格式：T1/T2 分位数表格 + 达标判定（✅/❌）、
「分阶段耗时均值」、「回答质量抽样」（样本数 / answered / refused / 带引用率）与「达标结论」。

---

## 3. 常见问题

- **登录失败**：确认后端已启动、账号密码正确（默认 `admin / Admin@123`），
  错误信息会带统一响应的 `code` 与 `request_id`，可据此查后端日志；
- **全部超时**：先用 `--phase t1 --limit`/小 `--repeat` 小样本试跑；
  SSE 被代理攒批时，确认 Nginx 已按 docs/06 §5.8 关闭缓冲（`X-Accel-Buffering: no`）；
- **T2 抖动大**：T2 包含外部 LLM 真实首 token 时间（docs/09 §5.1 测量条件 3），
  建议在同一时段、同机（localhost）下测量并保留 100 次以上样本；
- **评测集列名不符**：脚本按首行表头匹配列名，`qid`/`question` 为必需列，其余缺失按空处理。
