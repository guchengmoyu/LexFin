<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { retrieveApi, feedbackApi } from '../api'

/**
 * 测评（原「人工校验」页改造）：
 * 选择评测题文件（.jsonl / .json，字段 question/doc_title/article_no）→ 逐题调用 /retrieve
 * → 右侧实时返回结果，含 hit@1/3/5/10 柱状图、MRR、空召回率与逐题明细。
 * 命中判定口径与后端 scripts/eval_retrieval.py 一致：同一制度(doc_title) + 同一条号(去空白)。
 */
interface EvalRow {
  id?: string
  question: string
  doc_title: string
  article_no: string
  kb_id?: number
}

interface RowResult {
  row: EvalRow
  rank: number // 首个命中名次（1 起），0=未命中，-1=请求失败
  docRank: number
  latency: number
  empty: boolean
  top1?: { doc_title?: string; article_no?: string }
  error?: string
}

const tab = ref<'run' | 'report'>('run')

// ---------------------------------------------------------------- 文件选择与解析
const fileName = ref('')
const rows = ref<EvalRow[]>([])
const invalidRows = ref(0)
const parseError = ref('')

function normArticle(v?: string): string {
  return (v || '').replace(/\s+/g, '')
}

function collect(r: any, out: EvalRow[]) {
  if (r && r.question && r.doc_title && r.article_no) {
    out.push({
      id: r.id == null ? undefined : String(r.id),
      question: String(r.question),
      doc_title: String(r.doc_title),
      article_no: String(r.article_no),
      kb_id: r.kb_id == null ? undefined : Number(r.kb_id),
    })
  } else {
    invalidRows.value++
  }
}

function parseRows(text: string, name: string) {
  parseError.value = ''
  invalidRows.value = 0
  const out: EvalRow[] = []
  try {
    if (name.toLowerCase().endsWith('.json')) {
      const arr = JSON.parse(text)
      if (!Array.isArray(arr)) throw new Error('JSON 文件须为题目数组')
      arr.forEach((r: any) => collect(r, out))
    } else {
      text.split(/\r?\n/).forEach((line) => {
        const s = line.trim()
        if (!s) return
        try {
          collect(JSON.parse(s), out)
        } catch {
          invalidRows.value++
        }
      })
    }
  } catch (e: any) {
    parseError.value = e?.message || '文件解析失败'
    rows.value = []
    return
  }
  rows.value = out
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  fileName.value = file.name
  const reader = new FileReader()
  reader.onload = () => {
    parseRows(String(reader.result || ''), file.name)
    resetRun()
  }
  reader.onerror = () => {
    parseError.value = '文件读取失败'
  }
  reader.readAsText(file, 'utf-8')
}

const previewRows = computed(() => rows.value.slice(0, 3))

// ---------------------------------------------------------------- 测评执行
const running = ref(false)
const aborted = ref(false)
const doneCount = ref(0)
const results = ref<RowResult[]>([])
const mode = ref<'hybrid' | 'keyword' | 'vector'>('hybrid')
const TOP_K = 10

function resetRun() {
  results.value = []
  doneCount.value = 0
  aborted.value = false
}

const progressPct = computed(() =>
  rows.value.length ? Math.round((doneCount.value / rows.value.length) * 100) : 0,
)

const metrics = computed(() => {
  const rs = results.value.filter((r) => r.rank !== -1)
  const total = rs.length
  if (!total) return null
  const at = (k: number) => rs.filter((r) => r.rank > 0 && r.rank <= k).length / total
  return {
    total,
    errCount: results.value.length - total,
    hit1: at(1),
    hit3: at(3),
    hit5: at(5),
    hit10: at(10),
    mrr: rs.reduce((s, r) => s + (r.rank > 0 ? 1 / r.rank : 0), 0) / total,
    docHit5: rs.filter((r) => r.docRank > 0 && r.docRank <= 5).length / total,
    emptyRate: rs.filter((r) => r.empty).length / total,
    avgMs: rs.reduce((s, r) => s + r.latency, 0) / total,
  }
})

const hitBars = computed(() => {
  const m = metrics.value
  if (!m) return []
  return [
    { label: 'hit@1', value: m.hit1 },
    { label: 'hit@3', value: m.hit3 },
    { label: 'hit@5', value: m.hit5 },
    { label: 'hit@10', value: m.hit10 },
  ]
})

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

async function start() {
  if (!rows.value.length) {
    ElMessage.warning('请先选择有效的测评文件')
    return
  }
  running.value = true
  resetRun()
  for (const row of rows.value) {
    if (aborted.value) break
    try {
      const res: any = await retrieveApi.retrieve({
        query: row.question,
        mode: mode.value,
        top_k: TOP_K,
        ...(row.kb_id ? { kb_ids: [row.kb_id] } : {}),
      })
      const items: any[] = res.items || []
      const rank =
        items.findIndex(
          (it) =>
            (it.doc_title || '') === row.doc_title &&
            normArticle(it.article_no) === normArticle(row.article_no),
        ) + 1
      const docRank = items.findIndex((it) => (it.doc_title || '') === row.doc_title) + 1
      results.value.push({
        row,
        rank,
        docRank,
        latency: Number(res.latency_ms) || 0,
        empty: items.length === 0,
        top1: items[0]
          ? { doc_title: items[0].doc_title, article_no: items[0].article_no }
          : undefined,
      })
    } catch (e: any) {
      results.value.push({ row, rank: -1, docRank: 0, latency: 0, empty: false, error: e?.message || '请求失败' })
    }
    doneCount.value++
  }
  running.value = false
  if (aborted.value) ElMessage.info(`已中止，完成 ${doneCount.value}/${rows.value.length} 题`)
  else ElMessage.success('测评完成')
}

function stop() {
  aborted.value = true
}

function downloadResults() {
  const blob = new Blob(
    [
      JSON.stringify(
        { file: fileName.value, mode: mode.value, top_k: TOP_K, metrics: metrics.value, results: results.value },
        null,
        2,
      ),
    ],
    { type: 'application/json' },
  )
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `eval_results_${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

// ---------------------------------------------------------------- Tab2：准确率报告（沿用原人工校验统计，对照 85% 验收阈值）
const statQuery = reactive({ batch_no: 'EVAL-20250601', target_type: 'answer' })
const stats = ref<any>(null)
const statsLoading = ref(false)

const ERROR_TYPES: Record<string, string> = {
  retrieval_miss: '检索未命中',
  hallucination: '内容编造',
  citation_wrong: '引用错误',
  outdated: '条文过时',
  incomplete: '答案不完整',
}
const TARGET_TYPES: Record<string, string> = { answer: '答案', knowledge_point: '知识点' }

const accuracyPct = computed(() =>
  stats.value ? `${(Number(stats.value.accuracy) * 100).toFixed(1)}%` : '—',
)
const maxErrorCount = computed(() => {
  const list = stats.value?.error_type_distribution || []
  return Math.max(1, ...list.map((e: any) => Number(e.count) || 0))
})

async function loadStats() {
  if (!statQuery.batch_no.trim()) {
    ElMessage.warning('请填写评测批次号')
    return
  }
  statsLoading.value = true
  try {
    stats.value = await feedbackApi.reviewStats(statQuery.batch_no.trim(), statQuery.target_type)
  } catch (e: any) {
    ElMessage.error(e?.message || '统计加载失败')
  } finally {
    statsLoading.value = false
  }
}

onBeforeUnmount(() => {
  aborted.value = true
})
</script>

<template>
  <section class="doc-page">
    <div class="doc-header">
      <div>
        <h1>测评</h1>
        <p>选择评测题文件开始检索测评，右侧实时返回 hit@k 等指标；准确率报告对照 ≥ 85% 验收阈值</p>
      </div>
    </div>

    <div class="tabs">
      <button class="tab" :class="{ active: tab === 'run' }" @click="tab = 'run'">检索测评</button>
      <button class="tab" :class="{ active: tab === 'report' }" @click="tab = 'report'">准确率报告</button>
    </div>

    <!-- ==================== 检索测评 ==================== -->
    <div v-if="tab === 'run'" class="split-layout">
      <!-- 左：文件与配置 -->
      <div class="panel">
        <h3 class="panel-title">测评文件</h3>
        <input
          type="file"
          accept=".jsonl,.json,application/json"
          class="file-input"
          @change="onFileChange"
        />
        <p class="hint">
          支持 .jsonl（每行一题）或 .json（数组），字段：
          <code>question</code>、<code>doc_title</code>、<code>article_no</code>（可选 <code>id</code>、<code>kb_id</code>）。
        </p>

        <el-alert v-if="parseError" :title="parseError" type="error" :closable="false" show-icon />
        <template v-else-if="rows.length">
          <div class="file-summary">
            <el-tag type="success">{{ fileName }}</el-tag>
            <span>有效 {{ rows.length }} 题</span>
            <span v-if="invalidRows" class="warn-text">，跳过无效 {{ invalidRows }} 行</span>
          </div>
          <div class="preview-box">
            <div v-for="(r, i) in previewRows" :key="i" class="preview-row">
              <div class="preview-q">{{ r.id || `#${i + 1}` }} · {{ r.question }}</div>
              <div class="doc-no">{{ r.doc_title }} · {{ r.article_no }}</div>
            </div>
            <div v-if="rows.length > 3" class="doc-no" style="text-align:center">… 共 {{ rows.length }} 题</div>
          </div>
        </template>

        <h3 class="panel-title" style="margin-top: 18px">测评配置</h3>
        <label class="form-label">检索模式</label>
        <el-select v-model="mode" style="width: 100%" :disabled="running">
          <el-option value="hybrid" label="混合检索（默认）" />
          <el-option value="keyword" label="关键词检索" />
          <el-option value="vector" label="语义检索" />
        </el-select>
        <label class="form-label">截断深度</label>
        <el-input :model-value="`Top-${TOP_K}（报告 hit@1/3/5/10）`" disabled />

        <div style="margin-top: 18px; display: flex; gap: 10px">
          <el-button
            type="primary"
            :loading="running"
            :disabled="!rows.length"
            @click="start"
          >
            {{ running ? '测评中…' : '开始测评' }}
          </el-button>
          <el-button v-if="running" type="danger" plain @click="stop">中止</el-button>
        </div>
      </div>

      <!-- 右：结果 -->
      <div class="panel">
        <h3 class="panel-title">
          <span>测评结果</span>
          <el-button v-if="metrics && !running" link type="primary" @click="downloadResults">下载 JSON</el-button>
        </h3>

        <el-empty v-if="!results.length && !running" description="选择文件并点击「开始测评」后，此处返回结果" />

        <template v-else>
          <div class="run-status">
            <div class="progress-track" style="flex: 1">
              <div class="progress-bar" :class="{ done: !running && !aborted }" :style="{ width: `${progressPct}%` }"></div>
            </div>
            <span class="doc-no">{{ doneCount }}/{{ rows.length }} 题{{ running ? '，测评中…' : aborted ? '，已中止' : '，已完成' }}</span>
          </div>

          <template v-if="metrics">
            <div class="metric-grid" style="margin-top: 14px">
              <div class="metric-card highlight"><div class="metric-num">{{ pct(metrics.hit1) }}</div><div class="metric-label">hit@1</div></div>
              <div class="metric-card"><div class="metric-num">{{ pct(metrics.hit5) }}</div><div class="metric-label">hit@5</div></div>
              <div class="metric-card"><div class="metric-num">{{ metrics.mrr.toFixed(3) }}</div><div class="metric-label">MRR</div></div>
              <div class="metric-card"><div class="metric-num">{{ metrics.avgMs.toFixed(0) }}ms</div><div class="metric-label">平均耗时</div></div>
            </div>

            <h3 class="panel-title" style="margin-top: 18px">hit@k 命中率</h3>
            <div class="hit-chart">
              <div v-for="b in hitBars" :key="b.label" class="bar-row">
                <span class="bar-label">{{ b.label }}</span>
                <span class="bar-track">
                  <span class="bar-fill hit-fill" :style="{ width: `${b.value * 100}%` }"></span>
                </span>
                <span class="hit-val">{{ pct(b.value) }}</span>
              </div>
            </div>

            <div class="sub-metrics">
              <span>doc hit@5：{{ pct(metrics.docHit5) }}</span>
              <span>空召回率：{{ pct(metrics.emptyRate) }}</span>
              <span>已测评：{{ metrics.total }} 题</span>
              <span v-if="metrics.errCount" class="warn-text">失败 {{ metrics.errCount }} 题</span>
            </div>

            <h3 class="panel-title" style="margin-top: 18px">逐题明细</h3>
            <el-table :data="results" max-height="380" size="small">
              <el-table-column label="#" width="56">
                <template #default="{ $index }">{{ $index + 1 }}</template>
              </el-table-column>
              <el-table-column label="问题" min-width="220">
                <template #default="{ row }">
                  <div class="q-cell">{{ row.row.question }}</div>
                  <div class="doc-no">{{ row.row.doc_title }} · {{ row.row.article_no }}</div>
                </template>
              </el-table-column>
              <el-table-column label="命中" width="80">
                <template #default="{ row }">
                  <el-tag v-if="row.rank === -1" size="small" type="info">失败</el-tag>
                  <el-tag v-else-if="row.rank === 0" size="small" type="danger">未命中</el-tag>
                  <el-tag v-else size="small" :type="row.rank <= 3 ? 'success' : 'warning'">#{{ row.rank }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="Top-1 结果" min-width="180">
                <template #default="{ row }">
                  <div v-if="row.top1" class="doc-no">{{ row.top1.doc_title }} · {{ row.top1.article_no }}</div>
                  <div v-else class="doc-no">{{ row.error || '（空召回）' }}</div>
                </template>
              </el-table-column>
              <el-table-column label="耗时" width="80">
                <template #default="{ row }">{{ row.latency ? `${row.latency}ms` : '—' }}</template>
              </el-table-column>
            </el-table>
          </template>
        </template>
      </div>
    </div>

    <!-- ==================== 准确率报告 ==================== -->
    <template v-else>
      <div class="page-toolbar">
        <el-input v-model="statQuery.batch_no" class="filter-item" style="width:200px" placeholder="评测批次号" />
        <el-select v-model="statQuery.target_type" class="filter-item" style="width:140px">
          <el-option v-for="(label, k) in TARGET_TYPES" :key="k" :value="k" :label="label" />
        </el-select>
        <el-button type="primary" :loading="statsLoading" @click="loadStats">
          {{ statsLoading ? '查询中…' : '查询报告' }}
        </el-button>
      </div>

      <el-empty v-if="!stats" description="填写批次号后查询准确率报告" />

      <template v-else>
        <div class="report-hero panel">
          <div>
            <div class="metric-label">答案准确率</div>
            <div class="big-accuracy" :class="stats.pass ? 'pass' : 'fail'">{{ accuracyPct }}</div>
            <div class="metric-label">
              阈值 {{ (stats.threshold * 100).toFixed(0) }}% ·
              <span :class="stats.pass ? 'pass-text' : 'fail-text'">{{ stats.pass ? '通过 ✅' : '未通过 ❌' }}</span>
            </div>
          </div>
          <div class="metric-grid" style="margin: 0; flex: 1; max-width: 620px">
            <div class="metric-card"><div class="metric-num">{{ stats.total }}</div><div class="metric-label">评测总数</div></div>
            <div class="metric-card"><div class="metric-num">{{ stats.correct }}</div><div class="metric-label">正确</div></div>
            <div class="metric-card"><div class="metric-num">{{ stats.incorrect }}</div><div class="metric-label">错误</div></div>
            <div class="metric-card"><div class="metric-num">{{ stats.reviewer_count }}</div><div class="metric-label">评测人数</div></div>
            <div class="metric-card highlight">
              <div class="metric-num">{{ stats.cohen_kappa == null ? '—' : stats.cohen_kappa }}</div>
              <div class="metric-label">Cohen's Kappa</div>
            </div>
          </div>
        </div>

        <div class="panel" style="margin-top: 16px">
          <h3 class="panel-title">错误类型分布</h3>
          <el-empty v-if="!stats.error_type_distribution?.length" description="本批次无错误记录" :image-size="60" />
          <div v-for="e in stats.error_type_distribution" :key="e.error_type" class="bar-row">
            <span class="bar-label">{{ ERROR_TYPES[e.error_type] || e.error_type }}</span>
            <span class="bar-track">
              <span class="bar-fill" :style="{ width: `${(e.count / maxErrorCount) * 100}%` }"></span>
            </span>
            <span>{{ e.count }}</span>
          </div>
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
.form-label {
  display: block;
  font-size: 13px;
  color: var(--text-2);
  margin: 12px 0 6px;
}

.hint {
  margin: 10px 0 14px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.7;
}

.hint code {
  background: var(--surface-2, #f3f4f6);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 11.5px;
}

.file-input {
  width: 100%;
  font-size: 13px;
  color: var(--text-2);
}

.file-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0;
  font-size: 13px;
  color: var(--text-2);
}

.warn-text {
  color: #b45309;
}

.preview-box {
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.preview-q {
  font-size: 12.5px;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-status {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hit-chart {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hit-fill {
  background: linear-gradient(90deg, #4f7cff, #21a366);
}

.hit-val {
  min-width: 52px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.sub-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 12px;
  font-size: 12.5px;
  color: var(--text-2);
}

.q-cell {
  font-size: 12.5px;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.report-hero {
  display: flex;
  align-items: center;
  gap: 32px;
  flex-wrap: wrap;
}

.pass-text {
  color: #21a366;
}

.fail-text {
  color: #e5484d;
}
</style>
