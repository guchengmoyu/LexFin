# FinRAG 后端（FastAPI + RAG 核心链路）

> 对应设计文档：`docs/02` 总体架构、`docs/03` 数据模型、`docs/04` 解析与 OCR、
> `docs/05` RAG 核心链路、`docs/06` 后端接口、`docs/09` 测试方案。
> 本文是**代码实现说明**；模块与文档的逐条对应关系另见 [docs/11](../docs/11-后端与RAG代码实现说明.md)。

## 一、职责范围

本目录覆盖课题中「**RAG / 后端 / AI**」三块内容：

| 块 | 内容 | 主要位置 |
| --- | --- | --- |
| 后端 | REST API、鉴权、统一响应、入库任务、知识点管理、问答/会话/收藏/反馈 | `app/api/v1/`、`app/services/`、`app/models/` |
| RAG | 文档解析、OCR、清洗、条文感知切分、向量化、混合检索（RRF）、重排 | `app/rag/parser/`、`app/rag/chunker.py`、`app/rag/retriever/` |
| AI | 查询理解与多轮改写、Prompt 工程（v1.2）、LLM 流式调用与降级、答案溯源、可信度评分 | `app/rag/query_rewriter.py`、`app/rag/prompt.py`、`app/rag/llm.py`、`app/rag/citation.py`、`app/rag/scorer.py` |

## 二、目录结构

```
backend/
├── app/
│   ├── main.py                 # FastAPI 实例、中间件链、启动钩子（seed + Milvus 初始化）
│   ├── core/                   # 配置 / 枚举 / 安全 / 日志 / 异常 / 统一响应 / 依赖注入
│   │   ├── config.py           #   pydantic-settings 单例，全部参数来自 .env
│   │   ├── constants.py        #   错误码（docs/06 §3）、业务字典（docs/03 §4.2）
│   │   ├── security.py         #   bcrypt(cost=12) + JWT HS256
│   │   ├── exceptions.py       #   BizError + 全局异常渲染（中文 message）
│   │   ├── response.py         #   {code, message, data, request_id} + 分页结构
│   │   └── deps.py             #   get_db / get_current_user / require_role / 限流
│   ├── api/v1/                 # 路由层：只做参数校验 + 调 Service + 包装响应
│   ├── models/                 # SQLAlchemy 2.0 ORM，与 deploy/mysql/init/01-schema.sql 一致
│   ├── schemas/                # Pydantic v2 请求模型（字段校验规则与 docs/06 一致）
│   ├── services/               # 业务编排：事务、状态机、级联删除、QA/入库链编排
│   ├── rag/                    # RAG 能力层（纯算法，不感知 HTTP）
│   │   ├── parser/             #   pdf/docx/text/image + ocr_engine + meta 抽取 + registry
│   │   ├── cleaner.py          #   页眉页脚/断行/乱码清洗（docs/04 §5）
│   │   ├── chunker.py          #   条文感知切分 ★（docs/04 §6）
│   │   ├── embedder.py         #   向量化工厂：local bge / cloud / fake（ADR-02）
│   │   ├── indexer.py          #   Milvus 读写 + build_filter（docs/03 §3）
│   │   ├── retriever/          #   vector / keyword(MySQL ngram) / hybrid(RRF) / reranker
│   │   ├── query_rewriter.py   #   清洗、线索抽取、关键词加权、多轮改写（docs/05 §2）
│   │   ├── prompt.py           #   Prompt v1.2 + 上下文裁剪 + 拒答话术（docs/05 §6）
│   │   ├── llm.py              #   ChatOpenAI 流式 + 备用渠道降级（docs/05 §7）
│   │   ├── citation.py         #   [n] 角标解析与越界过滤（docs/05 §8）
│   │   ├── scorer.py           #   可信度四因子评分（docs/05 §9）
│   │   └── types.py            #   ParsedDocument / RawChunk / RetrievedItem / Citation
│   ├── db/                     # Session、Milvus 初始化、种子数据（admin/知识库/配置）
│   └── utils/                  # 文件安全（魔数/MD5/安全文件名）、文本、时间
├── scripts/                    # 运维脚本（导入 app 包，与根目录 scripts/ 的 HTTP 脚本不同）
│   ├── reindex_all.py          #   从 MySQL 重建 Milvus（一致性恢复）
│   ├── check_consistency.py    #   MySQL ↔ Milvus 一致性巡检（--fix 自动修复）
│   ├── build_relations.py      #   same_topic 关联离线重建（每日）
│   └── refresh_timeliness.py   #   时效状态批量刷新（docs/03 §4.4）
├── tests/                      # pytest（unit / integration，docs/09 §3/§4）
├── requirements.txt            # 运行依赖（Python 3.11）
├── requirements-dev.txt        # 测试依赖
├── pytest.ini                  # 测试标记与选项
└── Dockerfile                  # python:3.11-slim + Tesseract5(chi_sim/eng)
```

## 三、快速开始

### 3.1 本地开发

```bash
# 1) 启动基础设施（MySQL + Milvus）
cd deploy
cp .env.example .env            # 至少填 MYSQL_ROOT_PASSWORD / MYSQL_PASSWORD / LLM_API_KEY
docker compose -f docker-compose.infra.yml up -d

# 2) 安装后端依赖（建议 Python 3.11 虚拟环境）
cd ../backend
pip install -r requirements.txt -r requirements-dev.txt

# 3) 配置环境变量（本地直跑把 deploy/.env 复制为 backend/.env，
#    并将 MYSQL_HOST / MILVUS_HOST 改为 127.0.0.1）
cp ../deploy/.env.example .env

# 4) 启动（启动时自动 seed 管理员与 Milvus 集合）
uvicorn app.main:app --reload --port 8000
```

- Swagger 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/v1/health>
- 默认管理员：`admin / Admin@123`（由 `.env` 的 `SEED_ADMIN_*` 决定，`app/db/seed.py` 创建）

### 3.2 Docker 部署

```bash
cd deploy
docker compose up -d --build
docker compose logs -f backend
```

镜像内已安装 Tesseract 5 + `chi_sim/eng`；需要解析 `.doc` 时置 `WITH_LIBREOFFICE=true`。

## 四、核心链路速查（问答一次发生了什么）

```
POST /api/v1/qa/ask/stream
  ① 参数校验（question 1~500 字）+ JWT 鉴权 + 限流 20 次/分钟
  ② 会话加载/新建 → 落库 user 消息
  ③ 查询理解：NFKC 清洗、条号/文号线索、jieba 关键词加权
  ④ 多轮指代改写（短问句/含指代词时触发，800ms 超时降级）
  ⑤ 检索：向量(Milvus top20) ∥ 关键词(MySQL ngram top20) → 加权 RRF 融合
     → 时效加权 + 条号/文号 ×1.5 + 知识点 ×1.15 → 去重 → Top-5
  ⑥ 拒答判定：无结果或 Top-1 融合分 < 0.30 → 标准拒答话术（不调 LLM）
  ⑦ SSE meta 事件：立即下发引用列表（用户先看到"正在参考以下条文"）
  ⑧ Prompt v1.2 组装（编号上下文，预算 4000 字）→ LLM 流式生成（token 事件）
  ⑨ 溯源解析（过滤越界 [n]）+ 可信度评分（0.4s1+0.25s2+0.2s3+0.15s4）
  ⑩ 落库 qa_message / qa_citation / latency_detail / token_usage → done 事件
```

时延预算与性能红线见 `docs/05 §10`；两路检索用 `asyncio.gather` 并发（`asyncio.to_thread`）。

## 五、配置

所有可变项来自 `.env`（模板：[deploy/.env.example](../deploy/.env.example)），
代码中不得出现裸常量（`docs/00 §6` 变更管理约定）。常用开关：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | deepseek-chat | OpenAI 兼容协议，切换厂商不改代码（ADR-03） |
| `EMBEDDING_PROVIDER` | local | `local`(bge) / `cloud` / `fake`（测试用） |
| `RERANK_ENABLED` | false | 一期关闭重排（ADR-05），开启后自动加载 bge-reranker |
| `RRF_W_VECTOR` / `RRF_W_KEYWORD` | 0.6 / 0.4 | 融合权重，用 `eval_rag.py` 网格搜索调优 |
| `RETRIEVAL_MIN_SCORE` | 0.30 | Top-1 低于此分直接拒答 |
| `PROMPT_VERSION` | v1.2 | Prompt 变更必须同步 docs/05 §6 版本号并回归评测 |
| `CHUNK_SIZE/OVERLAP/MAX/MIN_MERGE` | 500/80/800/120 | 切分参数（docs/04 §6.3） |

## 六、测试

```bash
cd backend
pytest -m unit -q                                  # L1 单元（无外部依赖，秒级）
pytest -m integration -q                           # L2 接口（需 MySQL/Milvus 就绪）
pytest -m unit --cov=app --cov-report=html         # 覆盖率（整体目标 ≥70%）
```

评测与压测脚本（纯 HTTP 客户端，位于仓库根 `scripts/`）：

```bash
python ../scripts/eval_rag.py  --dataset data/eval/eval_set.xlsx --base-url http://localhost:8000/api/v1 \
    --username admin --password Admin@123 --mode hybrid --batch-no EVAL-20250601
python ../scripts/bench_api.py --base-url http://localhost:8000/api/v1 --username admin --password Admin@123 \
    --questions data/eval/questions.txt --repeat 100
```

接口自动化测试用 **Apifox**（导入 `apifox/FinRAG-collection.json`，见 `apifox/README.md`）。

## 七、运维脚本

```bash
cd backend
python scripts/check_consistency.py --fix    # MySQL↔Milvus 巡检并修复
python scripts/reindex_all.py                # 全量重建向量（换嵌入模型后执行）
python scripts/build_relations.py            # same_topic 关联重建（每日）
python scripts/refresh_timeliness.py --dry-run
bash ../scripts/smoke.sh                     # 发版前 30 秒冒烟
```

## 八、代码约定（与 docs/02 §3 分层一致）

1. **路由层**只做参数校验、鉴权依赖、调 Service、包装响应；不写 SQL、不写 Prompt。
2. **Service 层**负责事务边界、状态机流转、级联删除编排；不直接拼 SQL 字符串。
3. **RAG 层**是纯算法：不访问业务表（检索 SQL 由 Service 注入的 Session 执行）、不感知 HTTP。
4. **数据访问**全部走 SQLAlchemy 2.0 表达式，禁止 f-string 拼接 SQL（NFR-07）。
5. 错误一律抛 `BizError(code, 中文 message)`，错误码只用 `docs/06 §3` 已登记的值。
6. 时间统一 `Asia/Shanghai` 本地时间；响应字段 `snake_case`；可空字段返回 `null` 不省略键。
