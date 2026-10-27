# 基于 RAG 的金融制度类知识问答系统

> 校企合作项目 · 人工智能应用方向 · **初步方案设计交付物**

面向**银行监管政策、证券行业规范、保险制度**等金融制度材料，提供文档解析与知识库构建、关键词检索、
自然语言问答、条文关联查询与**答案溯源**能力的 RAG 应用系统。

---

## 一、验收指标（来自课题要求）

| 指标 | 目标值 | 设计中的落地方式 |
| --- | --- | --- |
| 核心知识点覆盖 | **≥ 1000 条** | `knowledge_point` 表 + Excel/CSV 批量导入通道 + 入库校验脚本 |
| 系统响应时间 | **≤ 2 秒** | 「检索 ≤ 500ms + 首字/首 token ≤ 2s」双阈值，SSE 流式输出，见 `docs/09` |
| 人工校验准确率 | **≥ 85%** | 100+ 题人工标注评测集 + `qa_review` 表逐条判分，见 `docs/09` |

## 二、技术栈（一期全部选用最经典、社区最成熟的方案）

| 层次 | 选型 | 说明 |
| --- | --- | --- |
| 后端语言 | Python 3.11 | |
| Web 框架 | FastAPI 0.115 + Uvicorn | 课题指定 |
| RAG 编排 | LangChain 0.3 | 课题指定 |
| LLM | OpenAI 兼容接口（DeepSeek / 通义千问，可切换） | 通过 `.env` 切换，不改代码 |
| 向量化模型 | BGE-M3 或 bge-large-zh-v1.5（1024 维） | 中文金融语料表现稳定，本地部署无调用成本 |
| 重排模型 | bge-reranker-base | 二期启用，一期预留接口 |
| 向量库 | **Milvus 2.4**（standalone，Docker） | 课题指定 |
| 关系库 | **MySQL 8.0** | 课题指定 |
| OCR | **Tesseract 5**（chi_sim + eng）+ pytesseract | 课题指定 |
| 文档解析 | PyMuPDF / pdfplumber / python-docx | PDF、Word、Markdown、TXT、图片 |
| 前端 | Vue 3.4 + Vite 5 + TypeScript + Element Plus + Pinia | 课题允许 Vue 或 React，本项目选 Vue |
| 容器化 | Docker 24 + Docker Compose v2 | 课题指定 |
| 测试 | pytest 8 + httpx + **Apifox**（接口调试/自动化测试） | 课题指定接口测试环节，选用 Apifox |

## 三、系统服务与端口

| 服务 | 容器名 | 端口 | 说明 |
| --- | --- | --- | --- |
| 前端 | `finrag-frontend` | `8080:80` | Nginx 托管 Vue 构建产物，反代 `/api` |
| 后端 | `finrag-backend` | `8000:8000` | FastAPI，提供 `/api/v1/**` |
| MySQL | `finrag-mysql` | `3306:3306` | 结构化数据 |
| Milvus | `finrag-milvus` | `19530:19530` | 向量检索 |
| etcd | `finrag-etcd` | 内部 | Milvus 依赖 |
| MinIO | `finrag-minio` | `9000-9001` | Milvus 对象存储 |
| Attu（可选） | `finrag-attu` | `3000:3000` | Milvus 可视化运维 |

## 四、设计文档导航

| 编号 | 文档 | 内容 |
| --- | --- | --- |
| 00 | [设计文档索引与关键决策](docs/00-设计文档索引与关键决策.md) | 阅读顺序、术语表、ADR 决策记录 |
| 01 | [需求分析与项目范围说明书](docs/01-需求分析与项目范围说明书.md) | 功能/非功能需求、用例、验收标准、范围边界 |
| 02 | [系统总体架构设计](docs/02-系统总体架构设计.md) | 分层架构、模块划分、时序图、目录结构 |
| 03 | [数据模型与知识库设计](docs/03-数据模型与知识库设计.md) | MySQL 表结构、Milvus 集合、知识点规范 |
| 04 | [文档解析与 OCR 设计](docs/04-文档解析与OCR设计.md) | 解析流水线、OCR 策略、条文切分 |
| 05 | [RAG 核心链路设计](docs/05-RAG核心链路设计.md) | 检索、融合、重排、Prompt、溯源、可信度 |
| 06 | [后端接口设计](docs/06-后端接口设计.md) | 全部 REST 接口、统一响应、错误码 |
| 07 | [前端设计](docs/07-前端设计.md) | 页面结构、组件、状态管理、交互 |
| 08 | [部署与运维设计](docs/08-部署与运维设计.md) | Docker 编排、环境变量、备份、排障 |
| 09 | [测试方案设计](docs/09-测试方案设计.md) | pytest、Apifox、性能与准确率评测 |
| 10 | [开发计划与里程碑](docs/10-开发计划与里程碑.md) | 周计划、任务拆分、风险应对 |
| 11 | [后端与 RAG 代码实现说明](docs/11-后端与RAG代码实现说明.md) | 设计→代码映射、RAG 算法要点、验收指标对照 |
| 12 | [本地前后端联调环境说明](docs/12-本地联调环境说明.md) | 联调端口、一键启停、已验证接口、修复记录与排障 |

## 五、可执行交付物（设计规格的落地形式）

```
backend/                  # 后端 + RAG + AI（FastAPI / LangChain / Milvus，已交付）
  app/                    #   core / api / models / schemas / services / rag / db / utils
  scripts/                #   运维脚本（向量重建、一致性巡检、关联重建、时效刷新）
  tests/                  #   pytest 单元与接口测试
  README.md               #   后端实现说明（运行、配置、测试、运维）
deploy/
  docker-compose.yml          # 一键编排全部服务
  docker-compose.infra.yml    # 只起 MySQL + Milvus（立即可用）
  .env.example                # 环境变量模板
  mysql/init/01-schema.sql    # MySQL 建库建表 DDL（与 docs/03 一致）
scripts/                  # 评测与压测脚本（HTTP 客户端）
  eval_rag.py                 # 110 题评测集：Hit@k / MRR / 拒答正确率 / 准确率报告
  bench_api.py                # T1 检索 / T2 问答首 token 分位数压测
  smoke.sh                    # 发版前 30 秒冒烟
  dev-start.ps1               # 本地联调一键启动（基础设施 + 后端 8002 + 前端 5173）
  dev-stop.ps1                # 本地联调一键停止
apifox/
  README.md                   # Apifox 使用指南（导入 / 自动同步 / 测试场景 / CLI）
  FinRAG-collection.json      # 接口集合（Postman v2.1 格式，Apifox 直接导入，与 docs/06 一致）
  FinRAG-environment.json     # 环境变量（Apifox 可直接导入）
```

## 六、快速开始

> **后端与 RAG/AI 代码已交付**（`backend/`，说明见 [backend/README.md](backend/README.md)）；
> **前端 Vue 3 工程已交付**（`frontend/`，Vite 6）。下面三条路按需选择：
> **① 本地前后端联调（开发模式，推荐）**、② 只起基础设施、③ 容器全栈部署。

### 第零步（开发联调）：一条命令起前后端

```powershell
pwsh -File scripts/dev-start.ps1     # 基础设施 + 后端(8002) + 前端(5173)
# 浏览器打开 http://localhost:5173   （默认 admin / Admin@123）
pwsh -File scripts/dev-stop.ps1      # 结束应用进程（Docker 容器保留）
```

| 入口 | 地址 | 说明 |
| --- | --- | --- |
| 前端（开发） | <http://localhost:5173> | Vite dev，`/api` 代理到后端 |
| 后端 Swagger | <http://127.0.0.1:8002/docs> | 联调端口 8002 |
| 健康检查 | <http://127.0.0.1:8002/api/v1/health> | 含 MySQL / Milvus / OCR / LLM 探测 |
| MySQL | `127.0.0.1:3307` | 3306 被本机 MySQL80 服务占用，故映射 3307 |

完整说明（依赖安装、已验证接口清单、本次修复项、排障）见
[docs/12-本地联调环境说明](docs/12-本地联调环境说明.md)。

### 第一步（现在可用）：只启动基础设施，验证环境

```bash
cd deploy
cp .env.example .env          # 至少填 MYSQL_ROOT_PASSWORD、MYSQL_PASSWORD
docker compose -f docker-compose.infra.yml up -d
docker compose -f docker-compose.infra.yml ps      # 等到 mysql / milvus 均为 healthy
```

这一步会完成：建库建表（16 张表 + 3 个知识库）、启动 Milvus 并开放 19530、
验证 MySQL 的 **ngram 中文全文索引**可用，并提供 Attu 可视化控制台。

```bash
# 验证建表与初始化数据
docker exec -it finrag-mysql mysql -ufinrag -p -e "USE finrag; SHOW TABLES; SELECT code,name FROM knowledge_base;"
# Milvus 可视化
# 浏览器打开 http://localhost:3000
```

### 第二步（后端就绪）：全栈一键部署

```bash
cd deploy
# 【必须修改】.env 中的 SECRET_KEY、MYSQL_*、LLM_API_KEY
docker compose up -d --build
docker compose logs -f backend
```

> 前端 `frontend/` 尚未创建时，`docker compose up -d --build backend` 只构建部署后端，
> 接口联调可直接使用 Swagger（http://localhost:8000/docs）或 Apifox。

| 入口 | 地址 |
| --- | --- |
| 系统界面 | http://localhost:8080 |
| 接口文档（Swagger） | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/api/v1/health |
| Milvus 控制台 | http://localhost:3000 |

默认管理员 `admin / Admin@123`（由 `.env` 的 `SEED_ADMIN_PASSWORD` 决定，创建于后端首次启动）。

**首次部署耗时**：拉镜像 5~15 分钟 + 构建 3~5 分钟 + 下载嵌入模型 1~3 分钟 ≈ **15~25 分钟**。
完整部署说明与排障手册见 [docs/08](docs/08-部署与运维设计.md)。

## 七、目录规划（开发时目标结构）

```
创新实践3/
├── backend/          # FastAPI 应用（app/ tests/ scripts/ Dockerfile）✅ 已交付
├── frontend/         # Vue 3 应用（src/ Dockerfile nginx.conf）· 待开发
├── deploy/           # Docker 编排、初始化 SQL、环境变量
├── apifox/           # Apifox 接口集合、环境与使用指南
├── scripts/          # 评测与压测脚本（eval_rag / bench_api / smoke）
├── docs/             # 本套设计文档
└── data/             # 原始文档、OCR 中间产物（运行期挂载卷，不入 Git）
```

> 后端与 RAG/AI 代码已完成（对照说明见 [docs/11](docs/11-后端与RAG代码实现说明.md)）；
> `frontend/` 按 `docs/10` 的计划创建。
