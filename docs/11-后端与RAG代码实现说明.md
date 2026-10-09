# 11 · 后端与 RAG 代码实现说明

> 本文是 `docs/02`~`docs/06`、`docs/09` 的**代码落地对照表**与实现要点说明，
> 面向后端 / RAG / AI 方向的开发与答辩讲解。运行与目录说明见 [backend/README.md](../backend/README.md)。
>
> 代码位置：`backend/`。所有设计文档中的常量、接口契约、错误码均已在代码中逐项落实。

## 1. 设计文档 → 代码映射

| 设计文档 | 关键约束 | 代码落点 |
| --- | --- | --- |
| docs/02 §3 分层职责 | 路由不写 SQL、RAG 不感知 HTTP | `app/api/v1/`（薄路由）→ `app/services/`（编排）→ `app/rag/`（纯算法） |
| docs/02 §7.2 统一响应 | `{code, message, data, request_id}` | `app/core/response.py`、`app/core/exceptions.py`（BizError 全局渲染） |
| docs/02 §7.3 request_id | 生成/透传 + 日志注入 | `app/main.py` 中间件 + `app/core/logging.py`（ContextVar） |
| docs/02 §7.6 幂等并发 | 同文档同时只允许一个入库任务 | `app/services/ingest.py::start` 拦截（错误码 40902） |
| docs/03 §2 16 张表 | 字段名与 DDL 一致 | `app/models/*`（SQLAlchemy 2.0），DDL 见 `deploy/mysql/init/01-schema.sql` |
| docs/03 §2.4 content 前缀 | 【标题｜文号｜章 条】格式影响召回 | `app/rag/chunker.py::Chunker.build_prefix` |
| docs/03 §2.5 code 生成 | KP-{CAT}-{4位序号}，先插后回填 | `app/services/knowledge_point.py::create`（flush 取 id 再回填） |
| docs/03 §3 Milvus schema | pk=`chunk_{id}`/`kp_{id}`、dim=1024、content 冗余 | `app/rag/indexer.py` + `app/db/init_milvus.py`（集合 + HNSW/COSINE + 别名） |
| docs/03 §3.4 写入顺序 | 先 MySQL 拿 id → 再写 Milvus | `app/services/ingest.py::_run_pipeline` ④⑤⑥ 步 |
| docs/03 §6.4 级联删除 | 删文档清切片/向量/来源关联 + 知识点置疑 | `app/services/document.py::delete` |
| docs/04 §2 ParsedDocument | 统一中间表示 | `app/rag/types.py`（TextBlock/PageContent/ParsedDocument） |
| docs/04 §3 PDF 逐页判定 | <20 字页走 OCR，全/半混合型 | `app/rag/parser/pdf_parser.py` |
| docs/04 §4 OCR | Tesseract5 预处理链 + 结果缓存 + 质量兜底 | `app/rag/parser/ocr_engine.py`（缓存 `/data/ocr_cache/{md5}/p{n}.json`） |
| docs/04 §5 清洗规则 | 页眉页脚/断行/去重/乱码 | `app/rag/cleaner.py` |
| docs/04 §6 条文感知切分 | 正则识别章/条、长度规则、短条合并、页码映射 | `app/rag/chunker.py`（★ 核心） |
| docs/04 §7 元数据抽取 | 文号/机构/日期/标题（仅预填） | `app/rag/parser/meta.py` + `POST /documents/extract-meta` |
| docs/05 §2 查询理解 | NFKC、线索抽取、关键词加权、多轮改写 | `app/rag/query_rewriter.py` |
| docs/05 §3 检索通道 | 向量 top20 ∥ 关键词 top20 → 加权 RRF | `app/rag/retriever/{vector,keyword,hybrid}_retriever.py` |
| docs/05 §3.4 去重 | 知识点优先/同条限 2 块/相似度 0.95 | `hybrid_retriever.py::dedup_items` |
| docs/05 §4 Reranker | 一期 Passthrough，二期 bge-reranker（接口冻结） | `app/rag/retriever/reranker.py`（`RERANK_ENABLED` 开关） |
| docs/05 §5 拒答判定 | 前置（无结果/低分）+ 后置（无角标） | `app/services/qa.py::_pre_refuse` / `_is_refusal_text` |
| docs/05 §6 Prompt v1.2 | 系统提示逐字一致、编号上下文、4000 字裁剪 | `app/rag/prompt.py`（`PROMPT_VERSION="v1.2"`） |
| docs/05 §7 LLM 降级 | 失败切备用渠道，再失败返回证据列表 | `app/rag/llm.py::LLMClient.astream/ainvoke` |
| docs/05 §8 溯源 | [n] 解析、越界过滤、检索完成即下发 | `app/rag/citation.py` + `qa.py` meta 事件 |
| docs/05 §9 可信度 | 0.4s1+0.25s2+0.2s3+0.15s4 | `app/rag/scorer.py` |
| docs/05 §11 条文关联 | context/same_topic/supersede | `app/services/knowledge_point.py::related` + `backend/scripts/build_relations.py` |
| docs/06 §3 错误码 | 40001~50050 全量登记 | `app/core/constants.py::ErrorCode` + `ERROR_HTTP_STATUS` |
| docs/06 §5 全部接口 | 63 个请求契约 | `app/api/v1/*.py`（与 `apifox/FinRAG-collection.json` 目录一一对应） |
| docs/06 §5.8 SSE | meta→token*→ping→done/error，X-Accel-Buffering: no | `app/api/v1/qa.py::ask_stream` |
| docs/06 §6 安全 | bcrypt12、限流、魔数校验、HTML 转义、路径来自 DB | `app/core/security.py`、`app/core/deps.py`、`app/utils/file.py`、`retrieval.py::highlight_text` |
| docs/09 §3 单元测试 | chunker/citation/rrf/prompt/scorer 重点用例 | `backend/tests/unit/` |
| docs/09 §5/§6 评测压测 | T1/T2 分位数、Hit@k、拒答正确率 | `scripts/bench_api.py`、`scripts/eval_rag.py` |

## 2. RAG 核心算法实现要点

### 2.1 条文感知切分（chunker.py）

```
输入 ParsedDocument.pages
  → 逐行扫描识别「章/节/条」（正则见 docs/04 §6.1，含中文数字条号「第一百零二条」）
  → 产出 ArticleUnit 列表（表格块单独成 unit，保留表头前缀）
  → 长度规则：
      >800 字        → RecursiveCharacterTextSplitter(500/80) 条内滑窗，继承同一 article_no
      120~800 字     → 独立成块
      <120 字        → 同章相邻短条合并至 ≥120，article_no 记「第一条~第三条」，不跨章
  → 无「条」结构文档 → 整段递归切分，article_no=None（表格保留原位）
  → 页码映射：块内行 offset → 页号二分查找（支持跨页条 page_start≠page_end）
  → 拼接 content 前缀：【{title}｜{doc_no}｜{章} {条}】
```

入库后自动执行**切分自检**（docs/04 §6.5），告警写入 `document.error_message`（黄色提示，不阻断）。

### 2.2 混合检索与加权 RRF（hybrid_retriever.py）

```python
score(key) = Σ_channel W_channel / (K + rank)      # K=60, W_vector=0.6, W_keyword=0.4
final      = score × TIMELINESS_WEIGHT[timeliness]  # 1.0/0.9/0.8/0.5
             × 1.5  (条号或文号命中结构化线索)
             × 1.15 (source_type == knowledge_point)
```

- 两通道**并发执行**（`asyncio.to_thread`），取慢者而非相加（docs/05 §10 节省 60ms）；
- `rrf_fuse` / `dedup_items` 为**纯函数**，便于单元测试与网格调参；
- `vector_rank`/`keyword_rank` 在响应中保留，是调试与评测的关键信息（docs/06 §5.7）；
- 关键词通道零命中自动降级 LIKE，进程内统计降级比例（>30% 需调分词策略）；
- **拒答阈值口径（ADR-10）**：RRF 融合分为 `W/(K+rank)` 量纲（约 0.01~0.05），
  拒答判定将 `top1 / RRF_REF` 与 `RETRIEVAL_MIN_SCORE=0.30` 比较；`/retrieve` 响应中的
  `score` 仍返回原始 RRF 分（仅用于排序，不可解释为概率）。

### 2.3 查询理解（query_rewriter.py）

- 结构化线索（`第X条`、`文号`）优先精确匹配并置顶（×1.5）——「精确找条文」场景的关键优化；
  文号正则会贪婪吸入前导汉字，抽取后按机构词典**裁剪**，融合阶段对文号做**双向包含匹配**，
  确保「银保监会令2018年第3号」类精确命中能稳定触发加权；
- 关键词加权：金融术语/数字单位/条号文号 ×2.0，取 Top-8 拼 FULLTEXT 查询串；
- 多轮指代改写：短问句（<25 字）或含指代词时触发，temperature=0，
  **800ms 超时或失败自动降级为原始问题检索**，不阻塞主链路。

### 2.4 Prompt v1.2 与上下文裁剪（prompt.py）

- 系统提示与 `docs/05 §6.1` **逐字一致**，`PROMPT_VERSION` 落库到 `qa_message.prompt_version`；
- 上下文编号 `[1]..[n]` 是溯源锚点；按融合分降序累加，超 4000 字停止并**重新编号保持连续**；
- Top-1 单块超预算 → 1500 字截断并保留条号前缀；至少保证 2 条证据；
- Prompt 变更流程：改代码 → 升版本号（docs/05 §6）→ `eval_rag.py` 回归（准确率不得下降 >2%）。

### 2.5 溯源与可信度（citation.py / scorer.py）

- `CITE_PATTERN = \[(\d{1,2})\]`：只认半角；`[01]`→1；全角【1】不匹配；
- **越界角标**（LLM 编造 [9]）过滤并记 warning，`out_of_range_ratio()` > 5% 说明 Prompt 需调整；
- 可信度 `0.40·s1 + 0.25·s2 + 0.20·s3 + 0.15·s4`（s2 为引用覆盖率，s4 为 effective 占比）；
  分级 high≥0.80 / medium≥0.60 / low<0.60；**无引用直接判 0**；
  注意口径：confidence 是工程启发式指标，85% 准确率由人工评测独立得出，不可混淆。

### 2.6 SSE 时序与断连处理（qa.py + api/v1/qa.py）

```
检索完成 ──▶ meta（引用列表，不等 LLM 首 token） ──▶ token* ──▶ ping(15s) ──▶ done
```

- `meta` 先于任何 `token` 下发，是「2 秒体感」指标的实现基础（NFR-02）；
- assistant 消息在检索完成后**先占位落库**（meta 需要 message_id），生成结束回填全文；
- 客户端断开（关页面/停止生成）时取消 LLM 请求，但 `_finalize` 仍把**已生成内容落库**（docs/06 §5.8 规则 4）；
- 主渠道 LLM 失败自动切 `LLM_FALLBACK_MODEL`，备用也失败发 `error` 事件并展示检索证据。

## 3. 与验收指标的对应

| 指标 | 代码支撑 | 取证方式 |
| --- | --- | --- |
| 知识点 ≥ 1000 条 | `knowledge_point` 表 + `/knowledge-points/import`（Excel/CSV dry_run 校验）+ `code` 自动编号 | `GET /knowledge-points/stats` 的 `published`；验收 SQL 见 docs/03 §2.5 |
| 响应时间 ≤ 2 秒 | SSE 首 token 链路（docs/05 §10 时延预算）+ meta 提前下发 + 查询向量 LRU 缓存 | `scripts/bench_api.py` T2 P95≤2000ms（T1 检索 P95≤500ms 为补充证据） |
| 人工校验准确率 ≥ 85% | `qa_review` 表 + `/qa/reviews`、`/qa/reviews/stats`（含 `pass` 阈值与 Cohen's Kappa） | `scripts/eval_rag.py` 评测报告 + answers.xlsx 双人标注 |
| 条文关联查询 | `related` 三类关联（context/same_topic/supersede） | `GET /knowledge-points/{id}/related` |
| 答案溯源 | `qa_citation` 弱引用快照 + 角标解析 + `source_url#page=n` | 抽样核对条号与页码 |

## 4. 已知边界与二期扩展点

| 项 | 现状 | 二期位置 |
| --- | --- | --- |
| 重排 | PassthroughReranker（按分截断） | `reranker.py::BgeReranker`，开 `RERANK_ENABLED` |
| 关键词检索 | MySQL ngram FULLTEXT（ADR-04） | ES / Milvus BM25 稀疏向量，`RetrievalService` 按配置选择 |
| 入库任务 | FastAPI BackgroundTasks + DB 状态（ADR-06，单实例） | 消息队列（并发 >5 份文档或单文档 >5 分钟时升级） |
| 增量更新 | `document.superseded_by` 字段与 supersede 关联已就绪 | `parser/meta.py` + 定时任务自动标注时效 |
| 精确 bbox 高亮 | 页码跳转 + 文本高亮 | 解析时保存 `TextBlock.bbox`（字段已预留） |
| 答案缓存 | 无 | 高频 Top-100 问题 Redis 缓存（性能红线第 ⑤ 步） |

## 5. 联调与自检清单（后端开发完成口径）

- [ ] `pytest -m unit` 全绿，核心模块覆盖率 ≥ 85%（chunker/citation/scorer）
- [ ] `pytest -m integration` 全绿（MySQL + Milvus 就绪）
- [ ] Apifox 集合 `00~10` 目录全绿，错误码与 docs/06 §3 一致
- [ ] `scripts/bench_api.py`：T1 P95 ≤ 500ms、T2 P95 ≤ 2000ms
- [ ] `scripts/eval_rag.py`：Hit@5 ≥ 0.80、拒答正确率 ≥ 0.90、引用覆盖率 ≥ 0.95
- [ ] `backend/scripts/check_consistency.py` 无差异
- [ ] `scripts/smoke.sh` 退出码 0
