# 05 · RAG 核心链路设计

> 本文档定义系统最核心的算法链路：**从用户提问到带溯源的答案**。
> 所有 Prompt、阈值、权重在此冻结，代码改动必须同步更新本文档的版本号。

## 1. 链路总览

```
                        ┌──────────────────────────────────────┐
  用户提问 ────────────▶│ ① 查询理解 Query Understanding        │
                        │   清洗 / 关键词抽取 / 多轮指代改写(P1) │
                        └───────────────┬──────────────────────┘
                                        ▼
                        ┌──────────────────────────────────────┐
                        │ ② 查询向量化 Embedder（同一模型）      │
                        └───────────────┬──────────────────────┘
                                        ▼
        ┌───────────────────────────────┴───────────────────────────────┐
        ▼                                                               ▼
┌──────────────────┐                                          ┌──────────────────┐
│ ③a 向量检索       │  Milvus HNSW/COSINE  top_k=20            │ ③b 关键词检索     │
│    source_type ∈  │                                          │  MySQL ngram     │
│    {chunk, kp}    │                                          │  FULLTEXT  top=20│
└────────┬─────────┘                                          └────────┬─────────┘
         └───────────────────────┬─────────────────────────────────────┘
                                 ▼
                 ┌──────────────────────────────────┐
                 │ ④ RRF 融合 + 去重 + 时效加权      │
                 └───────────────┬──────────────────┘
                                 ▼
                 ┌──────────────────────────────────┐
                 │ ⑤ 重排 Reranker（一期为按分截断） │
                 │    → 最终证据 Top-5               │
                 └───────────────┬──────────────────┘
                                 ▼
                 ┌──────────────────────────────────┐
                 │ ⑥ 拒答判定（证据不足则拒答）      │
                 └───────────────┬──────────────────┘
                                 ▼
                 ┌──────────────────────────────────┐
                 │ ⑦ Prompt 组装（编号上下文）       │
                 └───────────────┬──────────────────┘
                                 ▼
                 ┌──────────────────────────────────┐
                 │ ⑧ LLM 流式生成（SSE）             │
                 └───────────────┬──────────────────┘
                                 ▼
                 ┌──────────────────────────────────┐
                 │ ⑨ 溯源解析 + 可信度评分           │
                 └───────────────┬──────────────────┘
                                 ▼
                 ┌──────────────────────────────────┐
                 │ ⑩ 落库（消息/引用/耗时/用量）     │
                 └──────────────────────────────────┘
```

## 2. 查询理解

### 2.1 基础清洗（一期必做）

| 步骤 | 规则 |
| --- | --- |
| 去首尾空白、统一全半角 | `str.strip()` + `unicodedata.normalize("NFKC", q)` |
| 长度限制 | 1 ≤ len ≤ 500，超长截断并提示 |
| 敏感/无关输入 | 空白或纯符号 → 直接返回 `40020` 参数错误 |
| 抽取结构化线索 | 文号（`…〔2018〕12号`）、条号（`第25条`/`第二十五条`）、年份、机构名 |

**结构化线索是关键词检索的强特征**：若用户提问中出现 `第X条` 或具体文号，
关键词通道必须**优先精确匹配**该条号/文号（`WHERE article_no = ? OR doc_no = ?`），
命中结果直接置顶（权重 × 1.5）。这是「精确找条文」场景的关键优化。

### 2.2 关键词抽取（用于③b通道）

```
1. jieba.cut_for_search(question) 分词
2. 去停用词（内置中文停用词表 + 金融领域停用词：请问/如何/是否/规定/要求/标准…）
3. 加权重：
   - 金融术语词典命中（LCR、净资本、偿付能力充足率、投资者适当性…）  × 2.0
   - 文号 / 条号 / 数字 + 单位（100%、30日、5000万元）              × 2.0
   - 普通名词                                                       × 1.0
4. 取权重最高的 8 个词，用空格拼接为 MySQL FULLTEXT 查询串
   （ngram 解析器下用 OR 语义，`+词` 表示必须包含）
```

### 2.3 多轮指代改写（P1，默认开启）

**触发条件**：会话内存在历史且当前提问长度 < 25 字，或包含指代词
（`它 / 这个 / 该 / 上述 / 这条 / 那` 等）。

```
Prompt（改写专用，temperature=0，max_tokens=100）：
─────────────────────────────────────────────
下面是用户与助手的对话历史，以及用户的最新提问。
若最新提问包含指代或省略，请改写为一个不依赖上下文、可独立用于检索的完整问题；
若已经是完整问题，原样返回。只输出问题本身，不要任何解释。

【历史】
用户：{hist_q1}
助手：{hist_a1_digest}
...

【最新提问】{question}
─────────────────────────────────────────────
```

**降级**：改写调用超时（> 800ms）或失败 → 直接用原始问题检索，不阻塞主链路。

### 2.4 检索式扩展（口语化问题兜底，默认开启）

**遇到的问题**：联调时用户用口语提问，例如「证券的定义是什么？」「如果我没有获得营业执照，
还能继续营业嘛」，系统稳定返回「知识库未命中，已拒答」。定位到两个原因：

1. **关键词通道被泛词带偏**：MySQL ngram FULLTEXT 是 NATURAL LANGUAGE MODE（OR 语义），
   口语词「定义 / 没有 / 继续 / 获得」在制度语料里极其罕见，IDF 极高，直接压过「证券」
   这类领域词，召回一堆无关的百分比表格切片。
2. **向量通道对「泛问」不敏感**：BGE 对「X 的定义是什么」这类元问题给出的近邻是法条的
   相邻条款，真正的定义条款（如《证券法》第二条）排不进 Top-20。

**方案**：先用 LLM 把口语问题改写成 2~3 条**制度原文口吻**的检索式，再对每条检索式分别走
双通道检索，最后按变体权重做**加权 RRF** 融合。

```
Prompt（扩展专用，temperature=0，max_tokens=160，超时 query_expansion_timeout_ms）：
─────────────────────────────────────────────
你是金融制度检索助手。用户会用口语提一个问题，请把它改写成 2~3 条
「制度原文口吻」的检索式，用于全文检索与语义检索。
要求：使用法规常用表述（如「未经批准擅自设立」「予以取缔」「适用本法」），
每条 10~30 字，不要解释，只输出 JSON 字符串数组。

【用户问题】{question}
─────────────────────────────────────────────
示例：「如果我没有获得营业执照，还能继续营业嘛」
→ ["未取得营业执照从事经营活动", "未依法登记擅自从事经营予以取缔", "无照经营查处取缔"]
```

**融合权重**：原始问题 1.0，第 i 条扩展式 `max(0.3, QUERY_EXPANSION_WEIGHT - 0.15 × (i-1))`
（默认 `QUERY_EXPANSION_WEIGHT=0.8` → 0.8 / 0.65 / 0.5），避免扩展式喧宾夺主。

**降级**：扩展开关关闭、问题过长（> `QUERY_EXPANSION_MAX_CHARS`，默认 80 字）、
LLM 超时或解析失败 → 只用原始问题检索（单查询走原 `retrieve()`，行为与改造前完全一致）。
结果按问题文本做 256 条 LRU 缓存，同一问题的追问不重复付费。

**实测**（8080 全栈，admin）：

| 问题 | 改造前 | 改造后 |
| --- | --- | --- |
| 证券的定义是什么？ | refused，0 分，7.7s | partial，0.71，2.1s，引用《证券法》第二条/第一百二十条 |
| 如果我没有获得营业执照，还能继续营业嘛 | refused，0 分，4.0s | partial，0.91，4.8s，引用《保险法》等 3 条 |
| 银行最少要留多少本钱才够 | refused | answered，0.91，5.7s，引用资本管理办法 5%/6%/8% |
| 核心一级资本充足率的最低要求是多少？（对照） | answered，1.0 | answered，1.0，2.8s（无回归） |

### 2.5 口语化检索评测与「零成本三件套」（量化）

§2.4 是定性修复。为了知道「还差多少、下一步该先做哪一项」，补了一套可复跑的评测：

- **评测集**：`backend/scripts/build_eval_set.py` 从 1225 条知识点里按库分层抽样 60 条
  （banking/securities/insurance 各 20），用 LLM 把每条条文改写成「普通人会怎么问」的口语问题，
  标准答案 = `(doc_title, article_no)`，落在 `backend/tests/data/eval_colloquial.jsonl`。
  优点：不需要人工写 60 题，问题里也不会混进法条原文。
- **评测脚本**：`backend/scripts/eval_retrieval.py`，逐条走真实检索链路，判定 Top-k 里是否命中
  同一条号，输出 `hit@1/@3/@5/@10、doc_hit@5、MRR、empty_rate、avg_ms`；开关可单独 A/B
  `--instruction / --synonyms / --expand / --rerank`。

**实测（60 题，CPU，单条不含 LLM 生成答案的时延）**：

| 配置 | hit@1 | hit@3 | hit@5 | MRR | 平均耗时 |
| --- | --- | --- | --- | --- | --- |
| 基线（无三件套） | 0.633 | 0.817 | 0.900 | 0.736 | 0.71s |
| + 查询指令前缀 | **0.717** | 0.883 | 0.933 | 0.808 | 0.75s |
| + 同义词归一（追加术语） | 0.617 | 0.767 | 0.883 | 0.715 | 0.72s |
| + 同义词归一（仅替换） | 0.633 | 0.817 | 0.900 | 0.736 | 0.70s |
| + 检索式扩展（§2.4） | 0.683 | 0.917 | 0.933 | 0.789 | 3.06s |
| + bge-reranker-base 重排 | 0.700 | 0.867 | 0.900 | 0.793 | 2.76s |
| 指令 + 扩展 + 同义替换（**推荐**） | **0.767** | **0.933** | **0.983** | **0.853** | 3.20s |
| 再加 rerank（全开） | 0.733 | 0.933 | 0.950 | 0.842 | 5.12s |

**结论（已落到默认配置）**：

1. **查询指令前缀**是该配置默认值（`EMBEDDING_QUERY_INSTRUCTION`），只加在 `encode_query` 侧，
   入库向量不变，hit@1 +8.4pt，几乎没有额外耗时。
2. **检索式扩展**是提升最大的一项（hit@3 +10pt），代价是每问多一次 LLM 调用（≈2.3s），
   因此只在问题较短且没有条号/文号线索时触发。
3. **同义词归一**只保留「替换」，「追加同义术语」实测反而掉 5pt（OR 语义引入噪声），
   默认 `SYNONYM_APPEND_TERMS=false`。
4. **rerank 默认仍关闭**：单独开启能把 hit@1 从 0.633 提到 0.700，但与扩展叠加后不升反降
   （0.767 → 0.733）且多 2s；bge-reranker-base 在这批短查询上不如「扩展 + RRF」有效。
   若要用，建议 `RERANK_TOP_N ≥ 10`，避免重排后的截断把正确条文挤出去。
5. 剩余空间：hit@10 已达 1.0，说明**召回不是瓶颈、排序才是**；下一步优先换 bge-m3 或
   Milvus 2.5 原生 BM25，而不是继续加改写环节。

## 3. 检索通道

### 3.1 通道 A · 向量语义检索

```python
results = client.search(
    collection_name="finrag_embedding",          # 别名，非物理集合名
    data=[query_vector],                          # 1024 维，已 L2 归一化
    anns_field="embedding",
    search_params={"metric_type": "COSINE", "params": {"ef": 64}},
    limit=VECTOR_TOP_K,                           # 默认 20
    expr=build_filter(kb_ids, categories, timeliness, source_types),
    output_fields=["source_type", "source_id", "document_id", "article_no",
                   "page_no", "chunk_index", "content", "timeliness"],
)
```

> **维度约束**：查询向量与写入向量必须同模型、同维度（**1024**）、同归一化方式。
> 更换嵌入模型属于破坏性变更，必须走 §14 的 reindex 流程（新建 `_v2` 集合并切换别名），
> 否则 Milvus 会直接报维度不匹配。

**过滤表达式构造**：

```python
def build_filter(kb_ids, categories, timeliness, source_types) -> str:
    parts = []
    if kb_ids:        parts.append(f"kb_id in [{','.join(map(str, kb_ids))}]")
    if categories:    parts.append("category in [" + ",".join(f'"{c}"' for c in categories) + "]")
    if timeliness:    parts.append("timeliness in [" + ",".join(f'"{t}"' for t in timeliness) + "]")
    parts.append("source_type in [" + ",".join(f'"{s}"' for s in source_types) + "]")
    return " and ".join(parts)
```

**默认过滤**：`source_types=["chunk", "knowledge_point"]`（两类都召回，见 ADR-09）；
用户未指定时效时**不过滤已废止条文**，而是靠 §4 的加权降权 + §6 的提示，
因为「某规定已废止，替代规定是什么」本身就是高频业务问题。

### 3.2 通道 B · 关键词检索（Milvus 2.5 BM25 为主，MySQL ngram 保留可回切）

```sql
-- 切片通道
SELECT c.id, c.document_id, c.article_no, c.page_start, c.content,
       MATCH(c.content) AGAINST (:q IN NATURAL LANGUAGE MODE) AS score
FROM document_chunk c
WHERE MATCH(c.content) AGAINST (:q IN NATURAL LANGUAGE MODE)
  AND c.kb_id IN (:kb_ids)
ORDER BY score DESC
LIMIT 20;

-- 知识点通道（title + content + keywords 权重更高）
SELECT k.id, k.title, k.content,
       MATCH(k.title, k.content, k.keywords) AGAINST (:q IN NATURAL LANGUAGE MODE)
       + IF(k.title LIKE CONCAT('%', :raw, '%'), 5, 0) AS score
FROM knowledge_point k
WHERE k.status = 'published'
  AND MATCH(k.title, k.content, k.keywords) AGAINST (:q IN NATURAL LANGUAGE MODE)
ORDER BY score DESC
LIMIT 20;
```

**兜底**：ngram 分词对 < 2 字的查询词或含特殊符号的查询可能零命中，
此时降级为 `LIKE '%词%'` 逐词 OR 查询（同样限制 LIMIT 20），并记录日志统计降级比例。
若降级比例 > 30%，说明分词策略需要调整。

#### 3.2.1 Milvus 2.5 原生 BM25（当前默认）

**为什么换**：MySQL ngram FULLTEXT 的 `NATURAL LANGUAGE MODE` 是 **OR 语义**，
口语问题里多出来的泛词（「定义」「没有」「继续」）IDF 高、又一定命中，
会把真正的领域条文挤出前 20。BM25 是带饱和与长度归一的概率排序，
「命中越多、越罕见」才排得越高，正好补上这个缺口。

**实现**（`backend/app/db/milvus_bm25.py`）：

| 项 | 取值 |
| --- | --- |
| 集合 | `finrag_bm25_v1`（与向量集合 `finrag_embedding_v1` 分离，独立建/删） |
| 主键 | 与向量集合一致：`chunk_{id}` / `kp_{id}` |
| 全文字段 | `text`（= 切片 content；KP 为「标题
正文」），`enable_analyzer=True` |
| 分词器 | `analyzer_params={"type": "chinese"}`（jieba + 中文标点过滤），由 `BM25_ANALYZER` 覆盖 |
| 稀疏字段 | `sparse` + `Function(FunctionType.BM25)`，服务端自动生成 |
| 索引 | `SPARSE_INVERTED_INDEX`，`metric_type=BM25`；`kb_id/source_type/document_id` 建 INVERTED |
| 写入 | `upsert_rows`，100 条一批；`text` 截断 8192 字 |
| 可选字段 | `category/timeliness/article_no/page_no/chunk_index/publish_year/doc_title/doc_no/issuing_authority/document_id` 均 `nullable=True`（知识点可能没有文号、页码或主文档，缺字段时不能整行插入失败） |

**开关与排列组合**（`backend/app/core/config.py`）：

```ini
KEYWORD_BACKEND=bm25      # mysql = ngram FULLTEXT（旧） / bm25 = Milvus 原生 / both = 两路按秩融合
BM25_COLLECTION=finrag_bm25_v1
BM25_ANALYZER=chinese     # 可切 standard 做对照
BM25_DUAL_WRITE=true      # 入库时同步写 BM25 集合，切换后端不需要重建
```

- 检索分流在 `hybrid_retriever._keyword_channel`：单点决定走哪一路，`retrieve` 与 `retrieve_multi` 共用；
- `bm25_retriever.search_bm25` 与 `keyword_retriever.search_keyword` 同签名（`QueryInfo → List[RetrievedItem]`），
  条号/文号线索先用标量过滤精确取行置顶（对齐 MySQL 版 `_clue_search`），再去重合并；
- 索引构建：`python scripts/build_bm25_index.py [--drop] [--dry-run] [--analyzer standard]`，
  从 MySQL 灌 950 切片 + 1225 知识点（当前 2175 条与向量集合一一对应）；
- 入库双写：`VectorIndexer.upsert` 成功后同步写 BM25（失败只告警，不影响主链路），删除同步 `delete`。

**60 题口语评测**（`scripts/eval_retrieval.py --keyword mysql|bm25|both`，同一批问题、同一份数据）：

| 关键词通道 | 检索配置 | hit@1 | hit@3 | hit@5 | hit@10 | MRR | avg |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MySQL ngram | 裸 | 0.633 | 0.817 | 0.900 | 0.917 | 0.736 | 0.76s |
| MySQL ngram | +指令前缀 | 0.717 | 0.883 | 0.933 | 0.967 | 0.808 | 0.76s |
| MySQL ngram | +指令+扩展 | 0.767 | **0.933** | **0.983** | — | 0.853 | 3.2s |
| Milvus BM25 | +指令前缀 | 0.750 | 0.867 | 0.917 | 0.967 | 0.818 | 0.68s |
| **Milvus BM25** | **+指令+扩展** | **0.833** | 0.883 | 0.950 | **1.000** | **0.880** | 3.0s |
| both（两路融合） | +指令+扩展 | 0.800 | 0.917 | 0.983 | 1.000 | 0.870 | 3.4s |

**结论**：

1. 只开指令前缀时，BM25 略优于 ngram（hit@1 0.750 vs 0.717），差距来自短语匹配；
2. 叠加检索式扩展后差距拉开：**BM25 hit@1 0.833 vs MySQL 0.767（+6.6pt）、MRR 0.880 vs 0.853、
   hit@10 1.000（60 题全量召回）**——扩展出来的检索式是「短语型」的，
   BM25 对短语命中更敏感，ngram 的 OR 语义则会把短语拆成噪声；
3. MySQL ngram 仍在 hit@3/hit@5 上领先 3~5pt（0.933/0.983 vs 0.883/0.950），
   即「正确答案在前五」的比例更高，但「第一名就是正确答案」的比例更低——这正是排序质量差异；
4. `both`（两路按秩融合）把 hit@5 追平 ngram（0.983）、hit@10 保持 1.000，
   hit@1 仍比纯 BM25 低 3.3pt（两路第一名互相挤位），额外耗时约 0.4s；
5. 因此默认 `KEYWORD_BACKEND=bm25`（首位命中与全量召回最好），
   追求「Top-5 里尽量不漏」可切 `both`，排查历史问题时可用 `mysql` 回切旧实现。

**查询串怎么喂给 BM25**（`bm25_retriever.search_bm25`）：整句与关键词串两路都检索、按秩融合。
单用整句在无扩展时更好（hit@1 0.733 vs 0.667），单用关键词串在有扩展时更好（0.850 vs 0.800），
两路融合后取二者之间的稳定值（+扩展 0.833 / 无扩展 0.750），避免依赖「扩展是否成功」。

### 3.3 混合融合 · 加权 RRF（核心）

**Reciprocal Rank Fusion** 不依赖两路分数的量纲，是工程上最稳健的融合方式：

```python
K = 60                      # RRF 平滑常数
W_VECTOR = 0.6              # 向量通道权重
W_KEYWORD = 0.4             # 关键词通道权重

score = {}
for rank, item in enumerate(vector_results, start=1):
    score[item.key] += W_VECTOR / (K + rank)
for rank, item in enumerate(keyword_results, start=1):
    score[item.key] += W_KEYWORD / (K + rank)

# 时效加权（docs/03 §4.4）
TIMELINESS_WEIGHT = {"effective": 1.00, "amended": 0.90,
                     "unknown": 0.80, "repealed": 0.50}
final = score[key] * TIMELINESS_WEIGHT[item.timeliness]

# 结构化线索加分（§2.1）
if item.article_no and item.article_no in query_article_nos:   final *= 1.5
if item.doc_no     and item.doc_no     in query_doc_nos:       final *= 1.5

# 知识点优先（知识点是人工校验过的高质量资产）
if item.source_type == "knowledge_point":                      final *= 1.15
```

**权重调优依据**：`W_VECTOR / W_KEYWORD` 由 `scripts/eval_rag.py` 在评测集上网格搜索
（0.5/0.5、0.6/0.4、0.7/0.3、0.8/0.2），取 Hit@5 最优组合写入默认配置。

### 3.4 去重规则（ADR-09 的落地）

| 规则 | 处理 |
| --- | --- |
| 同一实体出现在两路 | RRF 天然合并（key 相同），分数累加 |
| 知识点与其 `primary_chunk` 同时命中 | 保留**知识点**，丢弃该切片（内容重复，节省上下文） |
| 同 `document_id + article_no` 的多个滑窗块 | 最多保留 2 个，且必须 `chunk_index` 相邻 |
| 内容相似度 > 0.95 的两块 | 保留分数高者（用 3-gram Jaccard 快速判定，避免重复引用同一段话） |

**实体唯一键**：`f"{source_type}_{source_id}"`，与 Milvus 主键完全一致，便于贯穿排查。

## 4. 重排 Reranker

| 阶段 | 实现 | 配置 |
| --- | --- | --- |
| **一期** | `PassthroughReranker`：按融合分排序，直接截断 Top-5 | `RERANK_ENABLED=false` |
| **二期** | `BgeReranker`：`BAAI/bge-reranker-base` CrossEncoder 精排 | `RERANK_ENABLED=true` |

```python
# 二期实现（接口已冻结，一期即可写好，只等开关）
class BgeReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        self.model = CrossEncoder(model_name, max_length=512)

    def rerank(self, query: str, items: list[RetrievedItem], top_n: int = 5):
        pairs = [(query, it.content_for_rerank) for it in items]   # 截断到 512 token
        scores = self.model.predict(pairs)                          # 原始 logits
        probs = 1 / (1 + np.exp(-scores))                           # sigmoid 归一化
        ranked = sorted(zip(items, probs), key=lambda x: -x[1])
        return [(it, float(p)) for it, p in ranked[:top_n]
                if p >= RERANK_MIN_SCORE]      # 默认 0.35，低于阈值丢弃
```

**决策依据**：一期关闭重排的理由见 ADR-05 —— 优先保证 2 秒时延。
`scripts/eval_rag.py` 必须同时输出「关/开重排」的准确率与延迟对比，
若准确率提升 ≥ 5 个百分点且 P95 仍 ≤ 2s，则在二期默认开启。

## 5. 拒答判定

**拒答是正确行为，不是失败**（AC-06 要求 10 个知识库外问题全部拒答）。

| 判定点 | 条件 | 动作 |
| --- | --- | --- |
| 前置 | 两路检索均无结果 | 直接返回 `answer_type=refused`，不给 LLM |
| 前置 | Top-1 融合分 < `RETRIEVAL_MIN_SCORE`（默认 0.30） | 直接拒答，附「建议检索词」与相关知识库提示 |
| 前置 | 重排开启时，重排后无一条 ≥ `RERANK_MIN_SCORE` | 直接拒答 |
| 后置 | LLM 输出中不含任何 `[n]` 角标，且检索结果为空 | `answer_type=refused`，丢弃 LLM 生成内容，改用模板话术 |
| 后置 | LLM 输出中不含 `[n]` 角标，但检索确有结果 | `answer_type=partial`，保留 LLM 的说明文字，追加上「最相关依据」清单（Top-3 条文 + `[n]` 角标），前端标签「已检索到相关条文，证据不足以直接作答」 |

**为什么要有 partial**：制度库里很多问题（如「证券的定义是什么」）本身就没有直接定义条款，
旧逻辑会把已经正确召回的《证券法》第二条连同 LLM 的回答一起丢掉，换成「未命中」模板，
既不诚实也浪费了召回结果。partial 只改「呈现方式」，不放松拒答边界：知识库外的问题仍然
两路检索皆空，直接 refused。

**标准拒答话术**：

```
根据现有知识库，暂未检索到与「{question}」直接相关的制度规定。

建议您可以：
1. 换用制度原文中的表述重新提问，例如「{suggested_query}」；
2. 在「关键词检索」中直接搜索：{top_keywords}；
3. 确认该问题是否属于当前知识库范围（银行监管 / 证券行业 / 保险制度）。
```

## 6. Prompt 设计

**版本号：`v1.2`**（变更必须同步更新此号与 `qa_message.prompt_version`）

### 6.1 系统提示（System）

```text
你是金融制度领域的专业问答助手，服务于银行、证券、保险行业的合规与业务人员。
你的回答必须严格基于下面给出的【参考条文】，不得使用参考条文之外的任何知识。

【回答规则】
1. 只依据【参考条文】作答，禁止凭常识、经验或训练记忆推测和编造。
2. 每一句结论后面必须标注来源编号，格式为 [1]、[2]；多个来源写作 [1][3]。
3. 若【参考条文】不足以回答问题，必须直接回答："根据现有知识库，暂未检索到相关规定"，
   并说明缺少哪方面的信息；严禁给出没有来源标注的答案。
4. 引用数值、比例、金额、期限、日期时必须与原文完全一致，不得改写、换算或四舍五入。
5. 若引用的制度标注为「已废止」或「已修订」，必须明确指出，并优先采用标注为「现行有效」的条文。
6. 回答结构：先给结论，再给依据与适用条件。用语规范、简洁，不寒暄、不复述本规则。
7. 若多条【参考条文】之间存在冲突，需指出冲突并说明各自的适用范围与时效。
```

### 6.2 用户提示（User，由模板拼装）

```text
【参考条文】
[1] 《{doc_title}》（{doc_no}，{timeliness_label}）{chapter_no} {article_no}  第{page}页
{content}

[2] 《{doc_title}》（{doc_no}，{timeliness_label}）{article_no}  第{page}页
{content}

...

【用户问题】
{question}

【回答要求】
请基于上述参考条文回答问题，并在结论后标注来源编号。若参考条文不足，请直接说明。
```

其中 `{timeliness_label}` ∈ {现行有效, 已修订, 已废止, 时效未知}。

### 6.3 Prompt 工程要点

| 要点 | 原因 |
| --- | --- |
| 上下文**必须编号** `[1][2]` | 编号是溯源的锚点，也是 LLM 引用行为的触发器 |
| 编号顺序 = 相关性降序 | LLM 存在位置偏好，最重要的证据放最前 |
| 每条附**完整出处头**（标题/文号/条号/页码/时效） | 让 LLM 在正文里能自然带出出处，且便于校验时效 |
| 上下文总长上限 **4000 字**（约 2500 token） | 控制首 token 延迟；超限时按分数从低到高丢弃 |
| 规则编号化、禁用项显式化 | 比自然语言描述更能约束模型行为 |
| 明确「不确定就拒答」 | 抑制幻觉的最有效单一手段 |

### 6.4 上下文裁剪规则

```
预算：MAX_CONTEXT_CHARS = 4000

1. 按融合分降序累加 context 文本长度
2. 累加超过预算时，停止加入后续条目，并**重新编号**（保持 [1..n] 连续）
3. 若 Top-1 单独就超过预算（超长条文），按 1500 字截断并保留其条号前缀
4. 保证至少 2 条证据进入上下文（除非只有 1 条通过阈值）
```

## 7. LLM 调用与降级

```python
llm = ChatOpenAI(
    model=settings.LLM_MODEL,                    # 如 deepseek-chat
    base_url=settings.LLM_BASE_URL,
    api_key=settings.LLM_API_KEY,
    temperature=0.1,        # 制度问答要求稳定、可复现
    max_tokens=800,         # 控制延迟与成本（答案长度约 400~600 字）
    timeout=20,
    streaming=True,
)
```

| 场景 | 降级策略 |
| --- | --- |
| 主渠道请求失败 / 超时（> 20s） | 自动切 `LLM_FALLBACK_MODEL` 重试 1 次 |
| 备用渠道也失败 | 返回 `answer_type=error` + **检索证据列表**（用户仍能看到条文），提示稍后重试 |
| 首 token 超过 `LLM_TTFT_TIMEOUT`（5s） | 前端展示「正在生成…」骨架屏 + 已下发的引用列表，不判失败 |
| 内容被安全策略拦截 | 返回标准提示，落库 `answer_type=error` |

**计费与配额保护**：`token_usage` 全量落库；单用户限流 20 次/分钟；
当日累计 token 超过 `LLM_DAILY_TOKEN_BUDGET` 时，前端提示并自动降级为「仅检索模式」。

## 8. 答案溯源（CitationResolver）★核心差异化

### 8.1 引用下发的时机

**检索完成立即下发引用列表**（SSE `meta` 事件），不等 LLM 生成完：

```
event: meta
data: {"message_id": 10231, "citations": [ {cite_index:1, doc_title:"...", article_no:"第二十五条", ...}, ... ]}

event: token
data: {"delta": "商业银行的流动性覆盖率"}

event: token
data: {"delta": "应当不低于100%"}

event: done
data: {"confidence": 0.87, "latency_ms": {...}, "answer_type": "answered", "used_citations": [1]}
```

用户在看到答案前就能看到「正在参考以下 3 条制度」，**主观等待大幅缩短**（NFR-02 的实现基础）。

### 8.2 角标解析与校验

```python
CITE_PATTERN = re.compile(r"\[(\d{1,2})\]")

def resolve(answer: str, citations: list[Citation]) -> list[Citation]:
    used = {int(m) for m in CITE_PATTERN.findall(answer)}
    valid = {c.cite_index for c in citations}
    # 1) 过滤越界角标（LLM 编造了不存在的 [9]）
    invalid = used - valid
    if invalid:
        logger.warning(f"LLM 输出越界引用 {invalid}，已过滤")
    # 2) 只落库真正被使用的引用，并标记
    return [c for c in citations if c.cite_index in (used & valid)]
```

**越界角标必须记录日志并计入质量指标**——若发生率 > 5%，说明 Prompt 需要调整
（通常是上下文编号不连续或截断破坏了编号）。

### 8.3 引用卡片数据结构

见 `docs/06` §5.2 的 `Citation` 结构，包含：
`cite_index / chunk_id / knowledge_point_id / document_id / doc_title / doc_no /
issuing_authority / article_no / page_no / snippet / score / timeliness`。

前端点击卡片 → 打开原文预览抽屉，滚动定位到 `page_no`，高亮 `snippet`
（本期用「跳转页码 + 文本高亮」实现；精确 bbox 高亮列为 P2，需解析时保存坐标）。

## 9. 可信度评分（ConfidenceScorer）

```
confidence = 0.40 × s1 + 0.25 × s2 + 0.20 × s3 + 0.15 × s4

s1 = 归一化 Top-1 融合分
     = min(1.0, rrf_top1 / RRF_REF)          RRF_REF = 0.03（经验标定值）
s2 = 引用覆盖率 = 含角标的句子数 / 答案总句子数
s3 = Top-5 平均融合分归一化 = min(1.0, mean(rrf_top5) / RRF_REF)
s4 = 时效因子 = 被引用条目中 effective 的占比
     （若无任何引用，s2/s3/s4 记 0，整体 confidence 直接判为 0）
```

| 区间 | 等级 | 前端表现 |
| --- | --- | --- |
| ≥ 0.80 | 高 | 绿色徽标「可信度高」 |
| 0.60 ~ 0.80 | 中 | 蓝色徽标「可信度中」，正常展示 |
| < 0.60 | 低 | 橙色徽标「可信度低，建议核对原文」+ 展开原文卡片 |

**注意**：`confidence` 是**工程启发式指标**，用于引导用户复核，不得对外宣称是「准确率」。
85% 准确率指标由人工评测（`docs/09` §6）独立得出，二者口径不同，不可混淆。

## 10. 时延预算与优化（NFR-01 / NFR-02）

| 阶段 | 预算 | 优化手段 |
| --- | --- | --- |
| 鉴权 + 参数校验 | 10 ms | JWT 无状态校验，不查库（用户信息随 token 携带最小集） |
| 会话加载 | 20 ms | `qa_session` 按 `session_no` 唯一索引命中 |
| 查询改写（P1） | 0~400 ms | 仅多轮时触发；超时 800ms 即降级放行 |
| 查询向量化 | **40 ms** | 模型常驻内存；LRU 缓存最近 500 条查询向量 |
| 向量检索 | **60 ms** | HNSW(ef=64)，5 万条数据实测 &lt; 30ms；`content` 冗余免回表 |
| 关键词检索 | **80 ms** | MySQL ngram 全文索引；限制 LIMIT 20 |
| RRF 融合 + 去重 | 10 ms | 纯内存，两路各 20 条 |
| 重排（一期关闭） | 0 ms | 开启后 +150~300 ms，需重新评估预算 |
| Prompt 组装 | 10 ms | |
| **LLM 首 token** | **1200 ms** | 主渠道实测 400~900ms；`max_tokens` 与上下文长度直接相关 |
| 网络 + SSE 序列化 | 70 ms | 同机部署，Nginx 反代 |
| **合计（首 token）** | **≈ 1500 ms** | **预算 2000 ms，余量 500 ms** |

**必须并行执行的环节**：向量检索与关键词检索用 `asyncio.gather` 并发，二者取慢者
（80ms）而非相加（140ms），节省 60ms。

**性能红线**：若实测首 token P95 > 2s，按以下顺序优化：
① 关多轮改写 → ② 缩小 `VECTOR_TOP_K` 到 10 → ③ 缩短 `MAX_CONTEXT_CHARS` 到 2500 →
④ 换更快的 LLM 渠道（如 `qwen-turbo`）→ ⑤ 对高频 Top-100 问题启用答案缓存（Redis，P2）。

## 11. 条文关联查询（FR-32）

`GET /api/v1/knowledge-points/{id}/related` 返回三类关联：

| 类型 | 实现 | 默认条数 |
| --- | --- | --- |
| `context` 同制度上下文 | 取主来源切片所在文档的 `chunk_index ± 2` 的切片，排除自身 | 4 |
| `same_topic` 同主题跨制度 | 用该知识点的向量在 Milvus 中检索，`COSINE ≥ 0.75`，排除自身与同文档 | 5 |
| `supersede` 替代关系 | 沿 `document.superseded_by` 链向上向下各一层 + `knowledge_point_relation.relation_type='supersede'` | 3 |

**缓存**：`same_topic` 结果落 `knowledge_point_relation` 表，由离线任务
`scripts/build_relations.py` 每日重建；接口优先读表，表内无数据时实时计算并回填。

## 12. 检索模式与前端映射

| 前端选项 | `retrieval_mode` | 行为 |
| --- | --- | --- |
| 智能问答（默认） | `hybrid` | ③a + ③b + RRF → 生成答案 |
| 精确查条文 | `keyword` | 仅 ③b，返回条文列表，**不调用 LLM** |
| 语义找规定 | `vector` | 仅 ③a，返回条文列表，**不调用 LLM** |

「关键词检索」页面的两种非 LLM 模式响应时间目标 **P95 ≤ 500ms**（NFR-01）。

## 13. 调优方法论

**调参优先级（严格按序，一次只动一个变量）**：

```
1. Chunker 参数（CHUNK_SIZE / OVERLAP / 条文正则）
   ← 影响最大，先确认「该召回的条文进了候选集」
2. 检索模式与权重（W_VECTOR / W_KEYWORD）
   ← 用评测集网格搜索
3. Top-K（VECTOR_TOP_K / FINAL_TOP_N / RETRIEVAL_MIN_SCORE）
4. Prompt 版本（编号方式、规则措辞、上下文长度）
5. Reranker 开关与阈值
```

**评测闭环**：

```
scripts/eval_rag.py --dataset data/eval/eval_set.xlsx --mode hybrid --rerank false
  → 输出：Hit@5 / MRR@5 / 准确率 / 拒答正确率 / 时延 P50,P95
  → 落 results/eval_YYYYMMDD_HHMM.json，支持多版本对比
```

**回归要求**：任何 Prompt 或检索参数变更，必须在同一评测集上复跑，
准确率相对基线下降 > 2 个百分点则回滚。

## 14. 配置参数汇总

```ini
# 向量化（维度必须与 Milvus 集合的 embedding 字段 dim 一致 = 1024）
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DIM=1024
EMBEDDING_BATCH_SIZE=32
EMBEDDING_MAX_LENGTH=512
EMBEDDING_NORMALIZE=true

# 关键词通道（docs/05 §3.2.1）
KEYWORD_BACKEND=bm25          # mysql / bm25 / both
BM25_COLLECTION=finrag_bm25_v1
BM25_ANALYZER=chinese
BM25_DUAL_WRITE=true

# 检索
VECTOR_TOP_K=20
KEYWORD_TOP_K=20
FINAL_TOP_N=5
RRF_K=60
RRF_W_VECTOR=0.6
RRF_W_KEYWORD=0.4
RRF_REF=0.03
RETRIEVAL_MIN_SCORE=0.30
RERANK_ENABLED=false
RERANK_MODEL=BAAI/bge-reranker-base
RERANK_MIN_SCORE=0.35

# 时效权重
TIMELINESS_WEIGHT_EFFECTIVE=1.00
TIMELINESS_WEIGHT_AMENDED=0.90
TIMELINESS_WEIGHT_UNKNOWN=0.80
TIMELINESS_WEIGHT_REPEALED=0.50

# Prompt 与生成
PROMPT_VERSION=v1.2
MAX_CONTEXT_CHARS=4000
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=800
LLM_TIMEOUT=20
LLM_TTFT_TIMEOUT=5

# 多轮
MULTI_TURN_ENABLED=true
MULTI_TURN_HISTORY_SIZE=3
QUERY_REWRITE_TIMEOUT_MS=800

# 缓存（P2）
QUERY_VECTOR_CACHE_SIZE=500
```
