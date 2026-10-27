# Apifox 接口调试与自动化测试指南

> 本项目使用 **Apifox** 作为接口调试、Mock 与自动化测试工具（课题要求的接口测试环节）。
> 本文档说明如何把 `docs/06` 的接口契约导入 Apifox，以及如何跑通自动化测试与 CLI。
>
> 配套设计文档：[docs/06 后端接口设计](../docs/06-后端接口设计.md)、[docs/09 测试方案设计](../docs/09-测试方案设计.md)

---

## 1. 为什么这个项目选 Apifox

| 能力 | 对本项目的价值 |
| --- | --- |
| **原生导入 Postman Collection v2.1** | 已有的接口契约文件可直接导入：**54 个接口 / 63 个请求**零手工录入 |
| **完全兼容 Postman `pm.*` 脚本 API** | 集合里已有的断言脚本（含 `pm.response.responseTime` 时延断言）**无需改写** |
| **从 OpenAPI 自动同步** | FastAPI 自动生成 `/openapi.json`，配好定时同步后接口文档零维护 |
| **内置 Mock 服务** | 前端不必等后端写完即可联调（`docs/10` 阶段 3 的关键依赖） |
| **测试场景 + CLI** | 一个场景串起「登录 → 上传 → 轮询任务 → 检索 → 问答 → 校验」全链路并断言 |
| 中文界面与中文文档 | 校企合作交付与答辩演示更顺畅 |

---

## 2. 第一步：导入接口集合与环境

### 2.1 导入接口

1. 在 Apifox 中新建项目，命名 `FinRAG`（团队/个人项目均可）；
2. 打开 **项目设置 → 导入数据（手动导入）**；
3. 选择 **Postman** 类型，上传 `apifox/FinRAG-collection.json`；
4. 导入完成后，接口会按 11 个目录组织：

```
00 Health & Config      04 Tasks                 08 Sessions
01 Auth                 05 Knowledge Points      09 Favorites
02 Knowledge Base       06 Retrieve              10 Feedback & Review
03 Documents            07 QA
```

> **权限提示**：`导入数据` 是项目管理员权限的设置项。若是团队项目且你不是管理员，请让管理员导入，或改用个人项目。

### 2.2 导入环境

两种方式，任选其一：

**方式 A（推荐）**：导入 `apifox/FinRAG-environment.json`
→ **环境管理 → 导入** → 选择该文件，得到环境 `FinRAG Local`。

**方式 B**：**环境管理 → 新建环境** `FinRAG Local`，手工添加下列变量：

| 变量名 | 初始值 | 说明 |
| --- | --- | --- |
| `base_url` | `http://localhost:8000/api/v1` | 服务地址（生产改为 `http://<host>:8080/api/v1`） |
| `token` | 空 | 登录后由脚本自动写入，建议设为**私有变量** |
| `kb_id` | `1` | 知识库列表接口自动写入 |
| `document_id` | 空 | 上传接口自动写入 |
| `task_no` | 空 | 上传接口自动写入 |
| `knowledge_point_id` | 空 | 新建知识点接口自动写入 |
| `message_id` | 空 | 问答接口自动写入 |
| `session_no` | 空 | 问答接口自动写入 |
| `batch_no` | `EVAL-20250601` | 准确率评测批次号 |
| `admin_username` | `admin` | |
| `admin_password` | `Admin@123` | 建议设为**私有变量**，避免泄露 |

> `token` 与 `admin_password` 请在 Apifox 中勾选「私有变量」（仅本地保存、不同步给协作者）。

### 2.3 按顺序跑通

```
1. 00 Health & Config / 健康检查          → 确认五个依赖全 ok
2. 01 Auth / 登录（自动写入 token）        → 必须先跑，其余接口依赖它
3. 02 Knowledge Base / 知识库列表          → 自动写入 kb_id
4. 03 Documents / 上传文档                 → 自动写入 document_id / task_no（需手动选文件）
5. 04 Tasks / 任务详情                     → 轮询直到 status=success
6. 05 Knowledge Points / 批量导入 · 预校验  → 需手动选 Excel 文件
7. 06 Retrieve / 混合检索
8. 07 QA / 问答（非流式）                  → 自动写入 message_id / session_no
9. 07 QA / SSE 流式问答
10. 10 Feedback & Review / 准确率统计      → 验收指标证据
```

**带文件上传的 3 个接口需要手动选文件**：`上传文档`、`解析预览`、`批量导入`、`图片 OCR 试跑`。
在 Apifox 的 Body → form-data 中把对应字段的类型改为 `File` 再选择本地文件。

---

## 3. 第二步（后端就绪后，推荐长期方案）：改为 OpenAPI 自动同步

FastAPI 会自动在 `/openapi.json` 暴露完整的 OpenAPI 3.0 描述。配好自动同步后，
以后改代码只需改 Pydantic 模型与路由，接口文档自动更新，**不再需要手工维护集合**。

### 3.1 配置步骤

1. **项目设置 → 导入数据（自动同步）**；
2. 新建数据源，类型选 **OpenAPI/Swagger**，地址填：

   ```
   http://localhost:8000/openapi.json
   ```

   > 注意：填 **JSON 直链**，不是 Swagger UI 页面地址（`/docs`）。
   > 若 Apifox 运行在另一台机器，把 `localhost` 换成后端所在主机 IP 或容器可达地址。
3. **匹配相同接口时选择「智能合并」** —— 这是关键一步：
   它会保留你在 Apifox 中已维护的中文名、参数说明、返回示例与断言脚本，
   只更新接口结构本身，避免自动同步把你写的脚本覆盖掉。
4. 设置同步周期（如每天一次），或需要时点「立即同步」。

### 3.2 双轨制说明

| 阶段 | 接口定义来源 | 说明 |
| --- | --- | --- |
| 后端未就绪（当前） | `apifox/FinRAG-collection.json` | 手工维护的契约文件，与 `docs/06` 严格一致 |
| 后端就绪后 | `/openapi.json` 自动同步 | 契约的唯一来源变成代码，`docs/06` 转为设计说明 |

**建议**：后端就绪后**保留** `FinRAG-collection.json` 作为历史归档与"从零重建环境"的备份，
但日常不再手工改它。

---

## 4. 脚本兼容性说明（无需改写）

Apifox 完全兼容 Postman 的脚本 API。本集合用到的 `pm.*` 能力对照如下：

| 本集合用到 | 用途 | Apifox 支持 |
| --- | --- | --- |
| `pm.test(name, fn)` | 定义断言 | ✅ |
| `pm.expect(x).to.eql / above / include / oneOf` | 基于 ChaiJS 的断言 | ✅ |
| `pm.response.code` / `.json()` / `.text()` / `.headers.get()` | 读取响应 | ✅ |
| `pm.response.responseTime` | **单请求时延断言**（本项目 2 秒指标的辅助验证） | ✅ |
| `pm.response.to.have.status` / `to.be.success` | 状态码快捷断言 | ✅ |
| `pm.environment.get / set` | 环境变量读写（token 与各 id 的串联） | ✅ |
| `pm.request.headers.upsert` | 前置脚本自动附加 `Authorization` 与 `X-Request-ID` | ✅ |
| 集合级 `prerequest` / `test` 事件 | 全局统一鉴权与通用断言 | ✅ |

**一个行为差异要注意**：`pm.environment.set` 写入的是**本地值**，
需要在 Apifox 的环境管理里手动「保存」才会同步到团队环境，否则只在本机生效。
本项目的变量串联（token → kb_id → document_id …）都在同一台机器上跑，不受影响。

**集合级断言的一个约束**：集合级后置脚本里对 JSON 结构的断言做了内容类型判断
（`Content-Type` 含 `application/json` 才校验），因此
「下载原文」「批量导出」这类二进制响应，以及 SSE 响应不会被误判 —— 它们由各自的请求脚本断言。

---

## 5. 自动化测试：测试场景

Apifox 的「测试场景」由多个**测试步骤**组成，可引用接口或接口用例，支持测试数据、循环与条件分支。
本项目建议建 **3 个测试场景**：

### 场景 1：`SMOKE-核心链路冒烟`（每次发版前跑）

| 步骤 | 接口 | 关键断言 |
| --- | --- | --- |
| 1 | `GET /health` | `status` ∈ {ok, degraded}；五依赖均被探测 |
| 2 | `POST /auth/login` | 返回 token；响应体不含 `password_hash` |
| 3 | `GET /kb` | 内置 3 个知识库 |
| 4 | `POST /retrieve`（hybrid） | items 非空；score 降序 |
| 5 | `POST /qa/ask` | `answer_type` 合法；answered 时引用角标可在答案中找回 |
| 6 | `POST /qa/ask`（知识库外问题） | `answer_type = refused`（反幻觉证据） |

### 场景 2：`E2E-文档入库全流程`

`上传 → 轮询任务（循环 + 等待）→ 查文档详情 → 查切片列表 → 检索命中该文档`

轮询用 Apifox 的**条件分支 + 循环**实现：任务详情断言 `status != 'failed'`，
用等待时间（如 3 秒）重复直到 `status == 'success'`，或设置最大轮询次数兜底。

### 场景 3：`ACCEPT-验收指标取证`

按顺序跑：`知识点统计`（读 `published`，对照 ≥1000）、
`准确率统计`（读 `accuracy` 与 `pass`）、`健康检查`（读 Milvus 实体数）。
在 Apifox 的测试报告里，这三步的响应与断言就是验收证据的一部分。

> 脚本里的 `console.log` 会输出关键指标（如「当前已发布知识点数量：1042（验收目标 ≥ 1000）」），
> 在测试报告的执行日志里可见，方便截图取证。

---

## 6. 命令行运行（CLI，用于 CI 与本机快速回归）

```bash
# 安装（也可直接用 npx，无需全局安装）
npm install -g apifox-cli

# 运行测试场景
npx apifox-cli run \
  --access-token <你的 Apifox 访问令牌> \
  --api-scene <测试场景ID> \
  --environment "FinRAG Local" \
  -r cli,html,junit \
  --out-file reports/apifox-report.html
```

**参数名以本机版本为准**：不同 Apifox 版本对"测试场景"的参数名有
`--api-scene` 与 `-t/--test-scenario` 两种写法，执行前先跑一次
`npx apifox-cli run --help` 确认。

**退出码语义**（可直接用于阻断发版）：

| 退出码 | 含义 |
| --- | --- |
| `0` | 全部断言通过 |
| `1` | 存在断言失败 —— 在 CI 中应阻断后续步骤 |

**访问令牌获取**：Apifox 头像 → 账号设置 → API 访问令牌。

---

## 7. Mock 服务（前端联调用）

后端接口未就绪时，前端（`docs/10` 阶段 3）可先用 Apifox Mock：

1. 在接口的「返回响应」中定义**期望**，把 `docs/06` 里的示例 JSON 粘进去作为「成功(200)」；
2. 打开 Mock 开关，Apifox 会给出形如 `https://mock.apifox.com/m1/<项目ID>/...` 的地址；
3. 前端把 `VITE_API_BASE_URL` 指向该 Mock 地址，或在 `vite.config.ts` 的 proxy 里改 target。

**注意**：Mock 只解决"接口不存在"的问题，不替代真实联调。
`docs/10` 阶段 3 的 T3-7（权限控制）与 T3-9（原文查看抽屉）依赖真实后端。

---

## 8. 交付与备份

| 目的 | 操作 | 是否入 Git |
| --- | --- | --- |
| 接口契约源文件（与 `docs/06` 一致） | 本目录的 `FinRAG-collection.json`，手工维护 | ✅ 入 Git |
| 环境变量模板 | 本目录的 `FinRAG-environment.json`（不含真实密钥） | ✅ 入 Git |
| **完整项目备份**（含中文名、断言、测试场景） | 项目设置 → **导出数据** → 选 Apifox 格式，另存为 `apifox/FinRAG-apifox-export.json` | ✅ 入 Git |
| 交接给他人 | 对方在 Apifox 中导入上面的导出文件，断言与测试场景一并恢复 | — |
| 与 `docs/06` 对齐检查 | 导出 OpenAPI 格式，与 `/openapi.json` 做 diff | — |

> **提交导出文件前务必检查**：Apifox 导出文件可能包含环境变量与内部 ID。
> 请确认其中的 `token`、`admin_password` 等**私有变量为空或已替换为占位值**再提交。
> 真实密钥只放在 `deploy/.env`（已在 `.gitignore` 中）。

---

## 9. 常见问题

| 问题 | 原因与解决 |
| --- | --- |
| 导入后目录乱序 / 层级不对 | Postman 的文件夹映射为 Apifox 目录，导入时选「同步更新所在目录」；乱序可手动拖拽整理 |
| 断言脚本没生效 | 检查是否导入到了「后置脚本」而非「前置脚本」；集合级脚本在**目录/项目**层级设置 |
| `{{token}}` 一直是空 | 先单独跑一次 `01 Auth / 登录`，再检查环境是否选中为 `FinRAG Local` |
| 自动同步后中文名和脚本没了 | 导入时未选「智能合并」，选成了「同 URL 覆盖」；从导出备份恢复后重新同步 |
| 上传接口报 400（缺少文件） | form-data 中 `files` 字段类型需为 `File` 并实际选择文件 |
| SSE 接口看不到逐字效果 | Apifox 调试面板等流结束后整体展示，属正常；真实流式效果看前端页面，逐事件时延看 `scripts/bench_api.py` |
| CLI 报「场景不存在」 | 参数名或场景 ID 不对，先 `npx apifox-cli run --help` 确认；场景 ID 在测试场景 URL 中 |
| Mock 返回的数据结构与前端类型不符 | Mock 的「返回响应」需按 `docs/06` 的示例逐字段维护，或从 OpenAPI 的数据模型自动生成 |
