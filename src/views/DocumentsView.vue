<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { documentApi, taskApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { useKbStore } from '../stores/kb'

const auth = useAuthStore()
const kbStore = useKbStore()

// ---------------------------------------------------------------- 列表与筛选
const list = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const listLoading = ref(false)
const filters = reactive({ kbId: '', status: '', keyword: '' })

const DOC_STATUS = {
  pending: { label: '待处理', cls: 'gray' },
  parsing: { label: '解析中', cls: 'blue' },
  embedding: { label: '向量化中', cls: 'purple' },
  ready: { label: '已就绪', cls: 'green' },
  error: { label: '失败', cls: 'red' },
}

const TIMELINESS = {
  effective: { label: '现行有效', cls: 'green' },
  amended: { label: '已修订', cls: 'yellow' },
  unknown: { label: '时效未知', cls: 'gray' },
  repealed: { label: '已废止', cls: 'red' },
}

const DOC_TYPES = ['办法', '通知', '规定', '细则', '指引', '公告', '其他']

const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

async function loadList() {
  listLoading.value = true
  try {
    const data = await documentApi.list({
      kb_id: filters.kbId,
      status: filters.status,
      keyword: filters.keyword,
      page: page.value,
      size: size.value,
    })
    list.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    alert(e.message || '加载文档列表失败')
  } finally {
    listLoading.value = false
  }
}

function doSearch() {
  page.value = 1
  loadList()
}

function goPage(p) {
  page.value = Math.min(Math.max(1, p), pages.value)
  loadList()
}

function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// ---------------------------------------------------------------- 上传
const uploadVisible = ref(false)
const uploadForm = reactive({
  files: [],
  kb_id: '',
  title: '',
  doc_no: '',
  doc_type: '',
  issuing_authority: '',
  publish_date: '',
  effective_date: '',
  expiry_date: '',
  timeliness: '',
  keywords: '',
})
const uploading = ref(false)
const uploadError = ref('')
const uploadResults = ref([])
const fileInput = ref(null)

const runningTasks = ref([]) // {task_no, document_id, name, progress, stage_message, status}
let pollTimer = null

function openUpload() {
  if (!kbStore.list.length) {
    alert('未加载到可用知识库，请先确认后端已初始化种子数据')
    return
  }
  Object.assign(uploadForm, {
    files: [],
    kb_id: kbStore.list[0]?.id ?? '',
    title: '', doc_no: '', doc_type: '', issuing_authority: '',
    publish_date: '', effective_date: '', expiry_date: '', timeliness: '', keywords: '',
  })
  uploadError.value = ''
  uploadResults.value = []
  uploadVisible.value = true
}

function onFileChange(e) {
  uploadForm.files = Array.from(e.target.files || [])
}

async function submitUpload() {
  uploadError.value = ''
  if (!uploadForm.files.length) return (uploadError.value = '请选择文件')
  if (!uploadForm.kb_id) return (uploadError.value = '请选择知识库')
  uploading.value = true
  try {
    const fd = new FormData()
    uploadForm.files.forEach((f) => fd.append('files', f))
    fd.append('kb_id', String(uploadForm.kb_id))
    const opt = (k) => (uploadForm[k] ? String(uploadForm[k]) : '')
    fd.append('title', opt('title'))
    fd.append('doc_no', opt('doc_no'))
    fd.append('doc_type', opt('doc_type'))
    fd.append('issuing_authority', opt('issuing_authority'))
    fd.append('publish_date', opt('publish_date'))
    fd.append('effective_date', opt('effective_date'))
    fd.append('expiry_date', opt('expiry_date'))
    fd.append('timeliness', opt('timeliness'))
    fd.append('keywords', opt('keywords'))

    const data = await documentApi.upload(fd)
    uploadResults.value = data.results || []
    // 启动任务进度轮询（docs/06：前端按 1.5 秒轮询 /tasks/{task_no}）
    for (const r of uploadResults.value) {
      if (r?.task_no) {
        runningTasks.value.push({
          task_no: r.task_no,
          name: r.file_name || '文档',
          progress: 0,
          stage_message: '排队中',
          status: 'queued',
        })
      }
    }
    startPolling()
    loadList()
  } catch (e) {
    uploadError.value = e.message || '上传失败'
  } finally {
    uploading.value = false
  }
}

// ---------------------------------------------------------------- 任务轮询
function startPolling() {
  stopPolling()
  pollTimer = setInterval(pollTasks, 1500)
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

async function pollTasks() {
  if (!runningTasks.value.length) {
    stopPolling()
    return
  }
  let changed = false
  await Promise.all(
    runningTasks.value.map(async (t) => {
      if (['success', 'failed'].includes(t.status)) return
      try {
        const d = await taskApi.detail(t.task_no)
        Object.assign(t, {
          progress: d.progress ?? 0,
          stage_message: d.stage_message || t.stage_message,
          status: d.status,
          error_message: d.error_message,
        })
        changed = true
      } catch {
        /* 单次失败忽略 */
      }
    }),
  )
  if (changed && runningTasks.value.every((t) => ['success', 'failed'].includes(t.status))) {
    stopPolling()
    setTimeout(() => {
      runningTasks.value = []
      uploadVisible.value = false
      loadList()
    }, 1800)
  } else if (changed) {
    loadList()
  }
}

// ---------------------------------------------------------------- 操作
async function reparse(row) {
  if (!confirm(`重新解析「${row.title}」？将重建切片与向量。`)) return
  try {
    const data = await documentApi.reparse(row.id)
    runningTasks.value.push({
      task_no: data.task_no,
      name: row.title,
      progress: 0,
      stage_message: '排队中',
      status: 'queued',
    })
    startPolling()
  } catch (e) {
    alert(e.message || '重新解析失败')
  }
}

async function removeDoc(row) {
  const hard = auth.role === 'admin' && confirm('是否物理删除（含向量与文件，不可恢复）？\n确定=物理删除 / 取消=仅归档')
  if (!hard && !confirm(`删除「${row.title}」？`)) return
  try {
    await documentApi.remove(row.id, hard)
    loadList()
  } catch (e) {
    alert(e.message || '删除失败')
  }
}

async function downloadDoc(row) {
  try {
    await documentApi.download(row.id, row.file_name || `${row.title}.pdf`)
  } catch (e) {
    alert(e.message || '下载失败')
  }
}

// ---------------------------------------------------------------- 切片预览
const chunksVisible = ref(false)
const chunksDoc = ref(null)
const chunks = ref([])
const chunksLoading = ref(false)
const chunksPage = ref(1)
const chunksTotal = ref(0)

async function openChunks(row) {
  chunksDoc.value = row
  chunksVisible.value = true
  chunksPage.value = 1
  await loadChunks()
}

async function loadChunks() {
  chunksLoading.value = true
  try {
    const data = await documentApi.chunks(chunksDoc.value.id, chunksPage.value, 20)
    chunks.value = data.items || []
    chunksTotal.value = data.total || 0
  } catch (e) {
    alert(e.message || '加载切片失败')
  } finally {
    chunksLoading.value = false
  }
}

onMounted(() => {
  loadList()
  kbStore.ensureLoaded()
})

onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="doc-page">
    <!-- 顶栏 -->
    <header class="doc-header">
      <div>
        <h1>文档管理</h1>
        <p>上传、解析与入库管理（入库任务按 1.5s 轮询进度）</p>
      </div>
      <button v-if="auth.canManage" class="btn" @click="openUpload">＋ 上传文档</button>
    </header>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <select v-model="filters.kbId" class="select filter-item" @change="doSearch">
        <option value="">全部知识库</option>
        <option v-for="kb in kbStore.list" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
      </select>
      <select v-model="filters.status" class="select filter-item" @change="doSearch">
        <option value="">全部状态</option>
        <option v-for="(v, k) in DOC_STATUS" :key="k" :value="k">{{ v.label }}</option>
      </select>
      <input
        v-model="filters.keyword"
        class="input filter-item grow"
        placeholder="按标题 / 文号搜索"
        @keyup.enter="doSearch"
      />
      <button class="btn outline" @click="doSearch">查询</button>
    </div>

    <!-- 列表 -->
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>标题 / 文号</th>
            <th>知识库</th>
            <th>时效</th>
            <th>状态</th>
            <th>切片</th>
            <th>页数</th>
            <th>大小</th>
            <th>解析方式</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="listLoading">
            <td colspan="9" class="empty-tip">加载中…</td>
          </tr>
          <tr v-else-if="!list.length">
            <td colspan="9" class="empty-tip">暂无文档，点击右上角「上传文档」开始</td>
          </tr>
          <tr v-for="row in list" v-else :key="row.id">
            <td>
              <div class="doc-title" :title="row.title">{{ row.title }}</div>
              <div v-if="row.doc_no" class="doc-no">{{ row.doc_no }}</div>
            </td>
            <td>{{ kbStore.kbName(row.kb_id) }}</td>
            <td>
              <span v-if="row.timeliness" class="tag" :class="TIMELINESS[row.timeliness]?.cls || 'gray'">
                {{ TIMELINESS[row.timeliness]?.label || row.timeliness }}
              </span>
              <span v-else class="tag gray">-</span>
            </td>
            <td>
              <span class="tag" :class="DOC_STATUS[row.status]?.cls || 'gray'">
                {{ DOC_STATUS[row.status]?.label || row.status }}
              </span>
              <div v-if="row.status === 'error' && row.error_message" class="err-line" :title="row.error_message">
                {{ row.error_message }}
              </div>
            </td>
            <td>{{ row.chunk_count ?? '-' }}</td>
            <td>{{ row.page_count ?? '-' }}</td>
            <td>{{ fmtSize(row.file_size) }}</td>
            <td>
              <span v-if="row.parse_method" class="tag blue">{{ row.parse_method.toUpperCase() }}</span>
              <span v-else>-</span>
            </td>
            <td>
              <div class="ops">
                <button class="btn-ghost op" @click="openChunks(row)">切片</button>
                <button class="btn-ghost op" @click="downloadDoc(row)">下载</button>
                <template v-if="auth.canManage">
                  <button class="btn-ghost op" @click="reparse(row)">重解析</button>
                  <button class="btn-ghost op danger" @click="removeDoc(row)">删除</button>
                </template>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分页 -->
    <div class="pagination">
      <span>共 {{ total }} 条</span>
      <button class="page-btn" :disabled="page <= 1" @click="goPage(page - 1)">‹</button>
      <button
        v-for="p in pages"
        :key="p"
        class="page-btn"
        :class="{ active: p === page }"
        @click="goPage(p)"
      >{{ p }}</button>
      <button class="page-btn" :disabled="page >= pages" @click="goPage(page + 1)">›</button>
    </div>

    <!-- ============ 上传弹窗 ============ -->
    <div v-if="uploadVisible" class="modal-mask" @click.self="uploadVisible = false">
      <div class="modal">
        <div class="modal-head">
          <div class="modal-title">上传文档</div>
          <button class="modal-close" @click="uploadVisible = false">×</button>
        </div>
        <div class="modal-body">
          <div class="field" style="margin-bottom: 14px">
            <label class="field-label">文件<span class="req">*</span>（可多选，元数据应用到全部文件）</label>
            <input ref="fileInput" type="file" multiple accept=".pdf,.docx,.doc,.txt,.md,.png,.jpg,.jpeg,.tiff" @change="onFileChange" />
            <div v-if="uploadForm.files.length" class="files-preview">
              <span v-for="f in uploadForm.files" :key="f.name" class="tag gray">{{ f.name }}</span>
            </div>
          </div>

          <div class="field" style="margin-bottom: 14px">
            <label class="field-label">知识库<span class="req">*</span></label>
            <select v-model="uploadForm.kb_id" class="select">
              <option v-for="kb in kbStore.list" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
            </select>
          </div>

          <div class="form-grid">
            <div class="field">
              <label class="field-label">标题</label>
              <input v-model="uploadForm.title" class="input" placeholder="留空自动抽取" />
            </div>
            <div class="field">
              <label class="field-label">文号</label>
              <input v-model="uploadForm.doc_no" class="input" placeholder="如 银保监会令2018年第3号" />
            </div>
            <div class="field">
              <label class="field-label">文档类型</label>
              <select v-model="uploadForm.doc_type" class="select">
                <option value="">自动抽取</option>
                <option v-for="t in DOC_TYPES" :key="t" :value="t">{{ t }}</option>
              </select>
            </div>
            <div class="field">
              <label class="field-label">发布机构</label>
              <input v-model="uploadForm.issuing_authority" class="input" placeholder="留空自动抽取" />
            </div>
            <div class="field">
              <label class="field-label">发布日期</label>
              <input v-model="uploadForm.publish_date" type="date" class="input" />
            </div>
            <div class="field">
              <label class="field-label">生效日期</label>
              <input v-model="uploadForm.effective_date" type="date" class="input" />
            </div>
            <div class="field">
              <label class="field-label">失效日期</label>
              <input v-model="uploadForm.expiry_date" type="date" class="input" />
            </div>
            <div class="field">
              <label class="field-label">时效性</label>
              <select v-model="uploadForm.timeliness" class="select">
                <option value="">自动判定</option>
                <option value="effective">现行有效</option>
                <option value="amended">已修订</option>
                <option value="repealed">已废止</option>
                <option value="unknown">未知</option>
              </select>
            </div>
          </div>
          <div class="field" style="margin-top: 14px">
            <label class="field-label">关键词</label>
            <input v-model="uploadForm.keywords" class="input" placeholder="逗号分隔，选填" />
          </div>

          <!-- 上传结果与任务进度 -->
          <div v-if="uploadResults.length" class="upload-results">
            <div
              v-for="r in uploadResults"
              :key="r.task_no || r.file_name"
              class="upload-row"
            >
              <span class="file-name">{{ r.file_name || r.filename }}</span>
              <span v-if="r.success === false" class="error-text">{{ r.message || '被拒绝' }}</span>
              <template v-else>
                <div class="progress-track">
                  <div
                    class="progress-bar"
                    :class="{ done: runningTasks.find((t) => t.task_no === r.task_no)?.status === 'success', fail: runningTasks.find((t) => t.task_no === r.task_no)?.status === 'failed' }"
                    :style="{ width: (runningTasks.find((t) => t.task_no === r.task_no)?.progress || 0) + '%' }"
                  />
                </div>
                <span class="stage">
                  {{ runningTasks.find((t) => t.task_no === r.task_no)?.stage_message || '排队中' }}
                </span>
              </template>
            </div>
          </div>
          <div v-if="uploadError" class="error-text" style="margin-top: 8px">{{ uploadError }}</div>
        </div>
        <div class="modal-foot">
          <button class="btn outline" @click="uploadVisible = false">关闭</button>
          <button class="btn" :disabled="uploading" @click="submitUpload">
            <span v-if="uploading" class="spin" />{{ uploading ? '上传中…' : '开始上传' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ============ 切片预览弹窗 ============ -->
    <div v-if="chunksVisible" class="modal-mask" @click.self="chunksVisible = false">
      <div class="modal wide">
        <div class="modal-head">
          <div class="modal-title">切片预览 · {{ chunksDoc?.title }}</div>
          <button class="modal-close" @click="chunksVisible = false">×</button>
        </div>
        <div class="modal-body">
          <div v-if="chunksLoading" class="empty-tip">加载中…</div>
          <div v-else-if="!chunks.length" class="empty-tip">暂无切片</div>
          <div v-for="c in chunks" :key="c.id" class="chunk-card">
            <div class="chunk-meta">
              <span class="tag blue">#{{ c.chunk_index ?? c.id }}</span>
              <span v-if="c.source_type" class="tag purple">{{ c.source_type === 'knowledge_point' ? '知识点' : '切片' }}</span>
              <span v-if="c.article_no" class="tag purple">{{ c.article_no }}</span>
              <span v-if="c.page_start != null" class="tag gray">
                第 {{ c.page_start }}{{ c.page_end && c.page_end !== c.page_start ? `~${c.page_end}` : '' }} 页
              </span>
              <span v-if="c.embedding_status === 1" class="tag green">已向量化</span>
              <span class="tag gray">{{ c.char_count ?? '-' }} 字</span>
            </div>
            <div class="chunk-content">{{ c.raw_content }}</div>
          </div>
          <div v-if="chunksTotal > 20" class="pagination" style="justify-content: center">
            <button class="page-btn" :disabled="chunksPage <= 1" @click="chunksPage--; loadChunks()">‹</button>
            <span>第 {{ chunksPage }} / {{ Math.ceil(chunksTotal / 20) }} 页 · 共 {{ chunksTotal }} 片</span>
            <button class="page-btn" :disabled="chunksPage >= Math.ceil(chunksTotal / 20)" @click="chunksPage++; loadChunks()">›</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.doc-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 22px 28px;
  overflow-y: auto;
}

.doc-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 16px;
}

.doc-header h1 {
  margin: 0;
  font-size: 20px;
}

.doc-header p {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--text-3);
}

.filter-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
  align-items: center;
}

.filter-item {
  width: 170px;
}

.filter-item.grow {
  flex: 1;
  width: auto;
}

.doc-title {
  font-weight: 500;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-no {
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: 2px;
}

.err-line {
  font-size: 11px;
  color: var(--danger);
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 3px;
}

.ops {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
}

.op {
  font-size: 12px;
  color: var(--primary);
  padding: 3px 6px;
}

.op.danger {
  color: var(--danger);
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.files-preview {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.upload-results {
  margin-top: 16px;
  border-top: 1px dashed var(--border);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.upload-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.file-name {
  width: 160px;
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex-shrink: 0;
}

.progress-track {
  flex: 1;
  height: 6px;
  background: var(--surface-2);
  border-radius: 999px;
  overflow: hidden;
  border: 1px solid var(--border);
}

.progress-bar {
  height: 100%;
  background: var(--primary);
  border-radius: 999px;
  transition: width 0.5s;
}

.progress-bar.done {
  background: var(--success);
}

.progress-bar.fail {
  background: var(--danger);
}

.stage {
  width: 150px;
  font-size: 12px;
  color: var(--text-3);
  flex-shrink: 0;
}

.modal.wide {
  width: 760px;
}

.chunk-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  margin-bottom: 10px;
}

.chunk-meta {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.chunk-content {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow-y: auto;
}
</style>
