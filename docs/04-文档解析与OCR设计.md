# 04 · 文档解析与 OCR 设计

> 解析质量是整个 RAG 系统的**天花板**：切片切错了，再好的模型也检索不出来。
> 本文档定义从「上传一个文件」到「产出可向量化切片」的完整规则。

## 1. 目标与支持格式

| 目标 | 说明 |
| --- | --- |
| 支持格式 | `.pdf` `.docx` `.doc` `.txt` `.md` `.png` `.jpg` `.jpeg` `.tiff` |
| 单文件上限 | 50 MB（`MAX_FILE_SIZE_MB`） |
| 输出 | 结构化切片列表（含章、条、页码、正文），可直接入库 MySQL 与 Milvus |
| 质量底线 | 每条切片**必须可溯源到具体页码**；解析失败必须明确报错而非静默产出垃圾 |

## 2. 解析流水线

```
  上传文件
     │
     ▼
┌─────────────────┐
│ 1. 类型与安全校验 │  扩展名白名单 + MIME 嗅探 + 大小 + MD5 去重
└────────┬────────┘
         ▼
┌─────────────────┐
│ 2. 解析路由      │  按扩展名选择 Parser
└────────┬────────┘
         │
   ┌─────┼──────────────┬────────────────┐
   ▼     ▼              ▼                ▼
 PDF    Word         纯文本          图片
   │     │              │                │
   │     │              │                ▼
   │     │              │        ┌──────────────┐
   │     │              │        │ OCR 引擎      │
   │     │              │        │ Tesseract 5   │
   │     │              │        └──────┬───────┘
   ▼     ▼              ▼               ▼
┌──────────────────────────────────────────────┐
│ 3. 统一中间表示 ParsedDocument                 │
│    pages: [{page_no, blocks:[{type,text,bbox}]}]│
│    meta : {title, doc_no, authority, dates}    │
└───────────────────┬──────────────────────────┘
                    ▼
┌──────────────────────────────────────────────┐
│ 4. Cleaner 清洗（页眉页脚/空白/乱码/断行）      │
└───────────────────┬──────────────────────────┘
                    ▼
┌──────────────────────────────────────────────┐
│ 5. Chunker 条文感知切分（§6）                  │
└───────────────────┬──────────────────────────┘
                    ▼
┌──────────────────────────────────────────────┐
│ 6. 元数据抽取（文号/机构/日期，§7）             │
└───────────────────┬──────────────────────────┘
                    ▼
        切片列表 → MySQL → Embedder → Milvus
```

**统一中间表示 `ParsedDocument`**（所有 Parser 必须返回该结构）：

```python
@dataclass
class TextBlock:
    type: Literal["text", "table", "image_caption", "title"]
    text: str
    page_no: int
    bbox: tuple[float, float, float, float] | None = None   # 用于高亮定位（二期）
    level: int | None = None                                 # 标题层级

@dataclass
class PageContent:
    page_no: int
    blocks: list[TextBlock]
    char_count: int
    used_ocr: bool

@dataclass
class ParsedDocument:
    file_name: str
    file_ext: str
    pages: list[PageContent]
    parse_method: Literal["text", "ocr", "mixed"]
    meta: dict          # title / doc_no / issuing_authority / publish_date / effective_date
    warnings: list[str]
```

## 3. 解析路由与 PDF 策略

### 3.1 路由表

| 扩展名 | Parser | 主库 | 说明 |
| --- | --- | --- | --- |
| `.pdf` | `PdfParser` | **PyMuPDF (fitz)** | 抽取快、能拿字号与坐标；`pdfplumber` 作为表格兜底 |
| `.docx` `.doc` | `DocxParser` | `python-docx` | `.doc` 先用 LibreOffice 转 `.docx`（容器内预装），失败则报错提示用户另存 |
| `.txt` `.md` | `TextParser` | 内置 | 按空行分段，Markdown 保留标题层级 |
| `.png` `.jpg` `.jpeg` `.tiff` | `ImageParser` | PyMuPDF + Tesseract | 直接 OCR |

### 3.2 PDF 文本层判定（决定是否走 OCR）

对 PDF **逐页**判定，而非整份判定（混合型文档很常见）：

```
page_char_count = 该页通过 fitz 抽取到的可见字符数（去空白）
若 page_char_count < PDF_TEXT_MIN_CHARS(20)  → 该页标记为 needs_ocr = True
整份文档：
  全部页 needs_ocr          → parse_method = "ocr"
  部分页 needs_ocr          → parse_method = "mixed"
  无页 needs_ocr            → parse_method = "text"
```

另设整体兜底：若 `总字符数 / 页数 < PDF_TEXT_MIN_CHARS_PER_PAGE(50)`，
则强制整份走 OCR（防止 PDF 里嵌了极少文字的水印层导致误判）。

### 3.3 PDF 解析步骤（PyMuPDF）

```python
import fitz

doc = fitz.open(path)
for page in doc:
    text = page.get_text("text")           # 或 "blocks" 保留段落边界
    # 表格探测：查找 page.find_tables()（PyMuPDF ≥ 1.23）
    # 缺字号信息用于标题识别时用 page.get_text("dict") 取 span["size"]
```

**表格处理**：

1. 优先 `page.find_tables()`（PyMuPDF 内置）→ 转 Markdown；
2. 未识别到时用 `pdfplumber.extract_tables()` 兜底；
3. 仍失败则把表格区域文本按行拼接为 `type="table"` 的块，并在 `warnings` 中记录。

**注意**：表格文本必须**加表头前缀**再成块，否则「100%」这类单元格脱离表头后毫无检索意义。
示例格式化结果：

```
【表：流动性覆盖率计算口径】
| 项目 | 权重 | 说明 |
| --- | --- | --- |
| 一级资产 | 100% | ... |
```

## 4. OCR 设计

### 4.1 引擎与依赖

| 项 | 选型 |
| --- | --- |
| 引擎 | **Tesseract 5.x**（课题指定） |
| 调用 | `pytesseract` |
| 语言包 | `chi_sim` + `eng`（Dockerfile 中 `apt-get install tesseract-ocr tesseract-ocr-chi-sim`） |
| PDF 转图 | **PyMuPDF `page.get_pixmap(dpi=300)`**（避免额外引入 poppler 依赖） |
| 图像处理 | Pillow + OpenCV（可选，用于倾斜校正） |

### 4.2 预处理链

```
原始页图
   │
   ▼ 灰度化 (Pillow .convert("L"))
   ▼ 自适应放大：若 DPI < 300 且短边 < 2000px，等比放大到长边 ≈ 2500px
      （Tesseract 对小字号中文识别率随分辨率显著提升）
   ▼ OTSU 二值化 (OpenCV threshold + THRESH_OTSU)
   ▼ 去噪：中值滤波 3×3
   ▼ 倾斜校正：霍夫变换检测文本行角度，|angle| > 0.5° 时旋转（P1，可关闭）
   ▼ 边框裁剪：去除扫描黑边
   ▼
输出 PNG（内存 BytesIO，不落盘）
```

### 4.3 Tesseract 参数

| 参数 | 值 | 说明 |
| --- | --- | --- |
| `lang` | `chi_sim+eng` | 中英混排 |
| `--oem` | `1` | 仅 LSTM 引擎，精度更高 |
| `--psm` | `6` | 假定为统一的文本块（制度文档正文最常用） |
| `-c preserve_interword_spaces` | `1` | 保留空格，避免数字与单位粘连 |
| `-c chinese_cht` | 不使用 | 一期不涉及繁体 |

**分块 OCR**：整页直接 OCR 时，段落间距可被 Tesseract 的换行信息还原；
调用 `pytesseract.image_to_data()` 获取每个词的 `block_num/par_num/line_num`，
按 `block → par → line` 聚合还原段落（比 `image_to_string` 的裸文本质量高得多）。

### 4.4 缓存与性能

| 项 | 设计 |
| --- | --- |
| 缓存路径 | `/data/ocr_cache/{file_md5}/p{page_no}.json` |
| 缓存内容 | 还原后的段落列表 + 平均置信度 |
| 命中条件 | 文件 MD5 与页号一致，且 `TESSERACT_VERSION` 与缓存中记录一致 |
| 单页耗时 | 300 DPI 中文页 CPU 约 **1.5~3 秒** |
| 100 页扫描件 | 约 3~5 分钟 → **必须后台任务 + 进度上报** |
| 加速手段 | 目标机多核时用 `ProcessPoolExecutor(max_workers=min(4, cpu_count))` 并行页 |

### 4.5 OCR 质量兜底

```
avg_conf = 所有词的 conf 均值（Tesseract 输出 0~100）
cn_ratio = 中文字符数 / 非空白字符数

若 avg_conf < 60 或 cn_ratio < 0.30：
    document.parse_method = "mixed"
    document.error_message = "OCR 识别质量偏低（置信度 xx），建议人工校对关键条文"
    ingest_task 状态仍为 success，但前端展示黄色告警
```

**不因 OCR 质量差而中断入库**——宁可入库后人工校对知识点，也不要让整批文档卡在失败态。

## 5. 清洗规则（Cleaner）

| 规则 | 做法 | 备注 |
| --- | --- | --- |
| 去除页眉页脚 | 统计出现在 ≥ 60% 页面的首行/末行文本，若长度 < 40 字则删除 | 页码单独用正则 `^[-—\s]*\d+[-—\s]*$` 删除 |
| 合并断行 | 中文行尾非标点且下一行首非标点时，直接拼接（不加空格） | 英文行尾为连字符 `-` 时去掉连字符 |
| 全角转半角 | 数字、字母、括号、百分号统一半角 | 保留中文标点 |
| 空白归一 | 连续空格/Tab → 单空格；连续 ≥ 2 换行 → 1 换行 | |
| 乱码与不可见字符 | 删除 `\x00-\x08\x0b-\x1f` 与常见 OCR 噪声字符 | |
| 空章节清理 | 清洗后长度 < 10 的块直接丢弃 | |
| 去除重复行 | 同一页内完全相同的行只保留一次（应对水印/骑缝章） | |

**必须保留**：`（一）（二）`、`1.`、`①` 等编号标记；`第X条` 原文；
页码标记（用于 offset→page 映射，清洗时保留为占位符，切分完成后再去掉）。

## 6. 条文感知切分算法（Chunker）★核心

### 6.1 切分单元识别正则

| 单元 | 正则 | 示例 |
| --- | --- | --- |
| 章 | `^第[一二三四五六七八九十百零〇\d]+章` | `第三章 流动性风险管理` |
| 节 | `^第[一二三四五六七八九十百零〇\d]+节` | `第二节 流动性风险监管指标` |
| **条** | `^第[一二三四五六七八九十百零〇\d]+条` | `第二十五条 商业银行的流动性覆盖率…` |
| 款 | `^[（(][一二三四五六七八九十\d]+[）)]` | `（一）一级资产…` |
| 数字编号（部分规范） | `^\d+(\.\d+){0,3}\s+\S` | `3.1.2 信息披露要求` |
| 附件/附则 | `^附\s*(则|件|表)` | `附则` |

### 6.2 算法流程

```
输入：清洗后的全文 + offset→page 映射表

① 逐行扫描，标记每个「条」的起止 offset，产出一级单元 ArticleBlock：
     { chapter_no, section_no, article_no, start_off, end_off }

② 对每个 ArticleBlock 做长度判定（长度 = end_off - start_off）：
     ├─ length > CHUNK_MAX(800)
     │     → 用 RecursiveCharacterTextSplitter(
     │           chunk_size=CHUNK_SIZE(500), chunk_overlap=CHUNK_OVERLAP(80),
     │           separators=["\n", "。", "；", "，", ""] )
     │       条内滑窗切分；每块继承同一 article_no，chunk_index 递增
     ├─ CHUNK_MIN_MERGE(120) ≤ length ≤ CHUNK_MAX
     │     → 独立成块
     └─ length < CHUNK_MIN_MERGE
           → 与「同章、相邻」的短条合并，直到合并长度 ≥ CHUNK_MIN_MERGE
             合并块 article_no 记为区间（如 "第一条~第三条"），
             块内保留每条开头的“第X条”标记以保证可读性与可溯源
             **不跨章合并**

③ 未识别到任何「条」结构的文档（通知、指引、公告）：
     → 直接对整个正文用 RecursiveCharacterTextSplitter 切分，article_no = None

④ 表格块以其所在位置插入序列，整表成一块，不受①②③的长度规则限制

⑤ 计算每块的 page_start / page_end：用块的 start_off/end_off 在 offset→page 映射表上二分查找

⑥ 拼接 content 前缀（格式见 docs/03 §2.4），raw_content 保存无前缀原文

⑦ 按顺序赋 chunk_index（0 起）
```

### 6.3 关键参数

| 参数 | 默认值 | 依据 |
| --- | --- | --- |
| `CHUNK_SIZE` | 500 字 | bge 模型最佳输入区间（256~512 token）；制度条文平均 200~400 字，500 能容下一个完整条 |
| `CHUNK_OVERLAP` | 80 字 | 约 16%，保证跨块句子与条号不丢 |
| `CHUNK_MAX` | 800 字 | 超过就切，避免单块语义过载、向量被稀释 |
| `CHUNK_MIN_MERGE` | 120 字 | 低于此值碎片化严重，召回噪声大 |
| `SEPARATORS` | `["\n", "。", "；", "，", ""]` | 中文语义层级，优先在段落/句号处断开 |

### 6.4 为什么必须做「条文感知」而不是无脑定长切分

1. **溯源要求**：答案要能标注「第二十五条」，无脑切分会把一条拆到两块，条号丢失。
2. **检索精度**：一条一议的制度文本，按条切分天然对齐语义边界，向量表达更聚焦。
3. **条文关联查询**：`article_no` 是关联「上下文条」的唯一依据（FR-32）。
4. **人工校对**：知识点校验界面需要「知识点 ↔ 原文条」并排展示。

### 6.5 切分自检（入库后自动执行）

```
若 单块长度 > 2 × CHUNK_MAX             → 记 warning
若 平均块长 < 100 字                     → 记 warning（可能正则未命中，切碎了）
若 article_no 非空的块占比 < 30%（且文档含“第X条”） → 记 warning，提示检查正则
若 块数 > 页数 × 40                      → 记 warning（可能重复内容）
```

warning 写入 `document.error_message`（截断 500 字），前端黄色提示，不阻断入库。

## 7. 元数据抽取（P1，为时效标注 FR-44 预留）

| 字段 | 抽取规则 |
| --- | --- |
| `doc_no`（文号） | 正则：`[\u4e00-\u9fa5]{2,8}(?:令\|公告\|通知\|发\|字)?\s*[〔\[（(]\s*\d{4}\s*[〕\]）)]\s*第?\s*\d+\s*号` <br>兼容两种写法：`银保监会令2018年第3号`、`证监发〔2018〕12号` |
| `issuing_authority` | 由 `doc_no` 前缀匹配机构别名字典（人行/银保监会/金融监管总局/证监会/交易所/协会…）；未命中则取首页前 5 行中包含「银行」「证券」「保险」「监督管理」的最短行 |
| `publish_date` | 首页 1000 字内匹配 `\d{4}年\d{1,2}月\d{1,2}日`；取最后一个（通常是落款） |
| `effective_date` | 匹配 `自\d{4}年\d{1,2}月\d{1,2}日起施行` / `自…起生效` |
| `title` | 首页第一个非空且长度 6~60 的行；若 PDF 含字号信息，取首页字号最大的文本行 |

**抽取结果只作为「预填值」返回给前端表单**，由上传人确认后再落库 —— 避免错误元数据污染检索过滤。

## 8. 错误处理与降级

| 场景 | 处理 |
| --- | --- |
| 不支持的类型 | 上传阶段即拒绝，400 + `40010` |
| 文件损坏 / 加密 PDF | 捕获异常 → `document.status='error'`，`error_message="文件已加密或损坏，无法解析"` |
| `.doc` 转换失败 | 返回明确提示：请另存为 `.docx` 或 `.pdf` |
| Tesseract 未安装 / 语言包缺失 | 启动时健康检查 `GET /health` 返回 `ocr: unavailable`；入库报错提示 |
| OCR 全部页失败 | 任务 `failed`，保留原始文件供重试 |
| 清洗后正文为空 | 任务 `failed`，`error_message="未能从文件中提取到有效文本"` |
| 单页 OCR 超时（> 30s） | 跳过该页，`warnings` 记录页号，继续处理后续页 |
| 大文件（> 100 页） | 允许，但任务降级为「低优先级」，前端提示预计耗时 |

**重试幂等**：`POST /documents/{id}/reparse` 会先删除该文档已有切片
（MySQL `DELETE ... WHERE document_id=?` 与 Milvus `delete(document_id==?)`），再重新走全流程，
`chunk_index` 重新从 0 开始，保证不产生重复切片。

## 9. 参数配置汇总（全部来自 `.env`）

```ini
MAX_FILE_SIZE_MB=50
ALLOWED_EXTENSIONS=.pdf,.docx,.doc,.txt,.md,.png,.jpg,.jpeg,.tiff

PDF_TEXT_MIN_CHARS=20              # 单页判定为扫描件的字符数下限
PDF_TEXT_MIN_CHARS_PER_PAGE=50     # 整份文档判定为扫描件的均值下限

OCR_LANG=chi_sim+eng
OCR_DPI=300
OCR_PSM=6
OCR_OEM=1
OCR_MAX_WORKERS=4
OCR_MIN_CONFIDENCE=60
OCR_CACHE_DIR=/data/ocr_cache

CHUNK_SIZE=500
CHUNK_OVERLAP=80
CHUNK_MAX=800
CHUNK_MIN_MERGE=120
```

## 10. 测试要点（对应 `docs/09`）

| 用例 | 输入 | 期望 |
| --- | --- | --- |
| 文本型 PDF | 30 页《管理办法》 | `parse_method=text`，条号识别率 ≥ 90%，页码正确 |
| 扫描件 PDF | 无文本层 PDF | `parse_method=ocr`，能提取到正文，`page_no` 正确 |
| 混合型 PDF | 前 2 页扫描 + 后 10 页文本 | `parse_method=mixed`，两段都有内容 |
| 图片制度 | PNG 截图 | `parse_method=ocr`，正文非空 |
| 带表格 PDF | 含监管指标表 | 表格转 Markdown 且保留表头，`source_type=table` |
| 超长条 | 单条 2000 字 | 切为多块，`article_no` 全部相同，`chunk_index` 连续 |
| 极短条 | 连续 5 条各 30 字 | 合并为 1~2 块，`article_no` 为区间 |
| 无条结构文档 | 一则通知 | 正常切分，`article_no` 为空但内容完整 |
| 加密 PDF | 带密码 PDF | 任务 `failed` 且错误信息可读 |
| 重复上传 | 相同 MD5 | 返回 409 + 已存在文档 id |
| 幂等重解析 | 同一文档 reparse | 切片总数不变，无重复 `chunk_index` |
