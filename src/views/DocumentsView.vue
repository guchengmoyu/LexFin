<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Upload } from '@element-plus/icons-vue'
import { documentApi, taskApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { useKbStore } from '../stores/kb'
import type { DocItem } from '../types'

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const auth = useAuthStore()
const kbStore = useKbStore()
const router = useRouter()

// ---------------------------------------------------------------- 列表与筛选
const list = ref<DocItem[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const listLoading = ref(false)
const filters = reactive({ kbId: '', status: '', keyword: '' })

const DOC_STATUS: Record<string, { label: string; type: TagType }> = {
  pending: { label: '待处理', type: 'info' },
  parsing: { label: '解析中', type: 'warning' },
  embedding: { label: '向量化中', type: 'warning' },
  ready: { label: '已就绪', type: 'success' },
  error: { label: '失败', type: 'danger' },
}

const TIMELINESS: Record<string, { label: string; type: TagType }> = {
  effective: { label: '现行有效', type: 'success' },
  amended: { label: '已修订', type: 'warning' },
  unknown: { label: '时效未知', type: 'info' },
  repealed: { label: '已废止', type: 'danger' },
}

const DOC_TYPES = ['办法', '通知', '规定', '细则', '指引', '公告', '其他']

const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

async function loadList() {
  listLoading.value = true
  try {
    const data: any = await documentApi.list({
      kb_id: filters.kbId,
      status: filters.status,
      keyword: filters.keyword,
      page: page.value,
      size: size.value,
    })
    list.value = data.items || []
    total.value = data.total || 0
  } catch (e: any) {
    ElMessage.error(e.message || '加载文档列表失败')
  } finally {
    listLoading.value = false
  }
}

function doSearch() {
  page.value = 1
  loadList()
}

function goPage(p: number) {
  page.value = Math.min(Math.max(1, p), pages.value)
  loadList()
}

function onSizeChange() {
  page.value = 1
  loadList()
}

function fmtSize(bytes: any) {
  if (!bytes && bytes !== 0) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// ---------------------------------------------------------------- 上传
const uploadVisible = ref(false)
const uploadForm = reactive({
  files: [] as File[],
  kb_id: '' as any,
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
const uploadResults = ref<any[]>([])
const fileInput = ref<HTMLInputElement | null>(null)

const runningTasks = ref<any[]>([]) // {task_no, document_id, name, progress, stage_message, status}
let pollTimer: ReturnType<typeof setInterval> | null = null

function openUpload() {
  if (!kbStore.list.length) {
    ElMessage.warning('未加载到可用知识库，请先确认后端已初始化种子数据')
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

function onFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  uploadForm.files = Array.from(target.files || [])
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
    const opt = (k: string): string => ((uploadForm as any)[k] ? String((uploadForm as any)[k]) : '')
    fd.append('title', opt('title'))
    fd.append('doc_no', opt('doc_no'))
    fd.append('doc_type', opt('doc_type'))
    fd.append('issuing_authority', opt('issuing_authority'))
    fd.append('publish_date', opt('publish_date'))
    fd.append('effective_date', opt('effective_date'))
    fd.append('expiry_date', opt('expiry_date'))
    fd.append('timeliness', opt('timeliness'))
    fd.append('keywords', opt('keywords'))

    const data: any = await documentApi.upload(fd)
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
  } catch (e: any) {
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
async function reparse(row: any) {
  const ok = await ElMessageBox.confirm(`重新解析「${row.title}」？将重建切片与向量。`, '提示', { type: 'warning' })
    .then(() => true)
    .catch(() => false)
  if (!ok) return
  try {
    const data: any = await documentApi.reparse(row.id)
    runningTasks.value.push({
      task_no: data.task_no,
      name: row.title,
      progress: 0,
      stage_message: '排队中',
      status: 'queued',
    })
    startPolling()
  } catch (e: any) {
    ElMessage.error(e.message || '重新解析失败')
  }
}

async function removeDoc(row: any) {
  let hard = false
  if (auth.role === 'admin') {
    hard = await ElMessageBox.confirm('是否物理删除（含向量与文件，不可恢复）？\n确定=物理删除 / 取消=仅归档', '提示', { type: 'warning' })
      .then(() => true)
      .catch(() => false)
  }
  if (!hard) {
    const ok = await ElMessageBox.confirm(`删除「${row.title}」？`, '提示', { type: 'warning' })
      .then(() => true)
      .catch(() => false)
    if (!ok) return
  }
  try {
    await documentApi.remove(row.id, hard)
    loadList()
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}

async function downloadDoc(row: any) {
  try {
    await documentApi.download(row.id, row.file_name || `${row.title}.pdf`)
  } catch (e: any) {
    ElMessage.error(e.message || '下载失败')
  }
}

// ---------------------------------------------------------------- 切片预览
const chunksVisible = ref(false)
const chunksDoc = ref<any>(null)
const chunks = ref<any[]>([])
const chunksLoading = ref(false)
const chunksPage = ref(1)
const chunksTotal = ref(0)

async function openChunks(row: any) {
  chunksDoc.value = row
  chunksVisible.value = true
  chunksPage.value = 1
  await loadChunks()
}

async function loadChunks() {
  chunksLoading.value = true
  try {
    const data: any = await documentApi.chunks(chunksDoc.value.id, chunksPage.value, 20)
    chunks.value = data.items || []
    chunksTotal.value = data.total || 0
  } catch (e: any) {
    ElMessage.error(e.message || '加载切片失败')
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
      <el-button v-if="auth.canManage" type="primary" :icon="Upload" @click="openUpload">上传文档</el-button>
    </header>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="filters.kbId" class="filter-item" @change="doSearch">
        <el-option label="全部知识库" value="" />
        <el-option v-for="kb in kbStore.list" :key="kb.id" :label="kb.name" :value="kb.id" />
      </el-select>
      <el-select v-model="filters.status" class="filter-item" @change="doSearch">
        <el-option label="全部状态" value="" />
        <el-option v-for="(v, k) in DOC_STATUS" :key="k" :label="v.label" :value="k" />
      </el-select>
      <el-input
        v-model="filters.keyword"
        class="filter-item grow"
        placeholder="按标题 / 文号搜索"
        clearable
        @keyup.enter="doSearch"
      />
      <el-button :icon="Search" @click="doSearch">查询</el-button>
    </div>

    <!-- 列表 -->
    <div class="table-wrap">
      <el-table v-loading="listLoading" :data="list">
        <el-table-column label="标题 / 文号" min-width="220">
          <template #default="{ row }">
            <div class="doc-title" :title="row.title">{{ row.title }}</div>
            <div v-if="row.doc_no" class="doc-no">{{ row.doc_no }}</div>
          </template>
        </el-table-column>
        <el-table-column label="知识库" width="130">
          <template #default="{ row }">{{ kbStore.kbName(row.kb_id) }}</template>
        </el-table-column>
        <el-table-column label="时效" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.timeliness" :type="TIMELINESS[row.timeliness]?.type || 'info'">
              {{ TIMELINESS[row.timeliness]?.label || row.timeliness }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag :type="DOC_STATUS[row.status]?.type || 'info'">
              {{ DOC_STATUS[row.status]?.label || row.status }}
            </el-tag>
            <div v-if="row.status === 'error' && row.error_message" class="err-line" :title="row.error_message">
              {{ row.error_message }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="切片" width="70">
          <template #default="{ row }">{{ row.chunk_count ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="页数" width="70">
          <template #default="{ row }">{{ row.page_count ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="大小" width="90">
          <template #default="{ row }">{{ fmtSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="解析方式" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.parse_method" type="primary">{{ row.parse_method.toUpperCase() }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <div class="ops">
              <el-button link type="primary" size="small" @click="openChunks(row)">切片</el-button>
              <el-button link type="primary" size="small" @click="router.push({ name: 'document-detail', params: { id: row.id } })">详情</el-button>
              <el-button link type="primary" size="small" @click="downloadDoc(row)">下载</el-button>
              <template v-if="auth.canManage">
                <el-button link type="primary" size="small" @click="reparse(row)">重解析</el-button>
                <el-button link type="danger" size="small" @click="removeDoc(row)">删除</el-button>
              </template>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无文档，点击右上角「上传文档」开始" :image-size="60" />
        </template>
      </el-table>
    </div>

    <!-- 分页 -->
    <el-pagination
      style="margin-top: 14px; justify-content: flex-end"
      layout="total, prev, pager, next, sizes"
      :total="total"
      :page-sizes="[10, 20, 50]"
      v-model:current-page="page"
      v-model:page-size="size"
      @current-change="goPage"
      @size-change="onSizeChange"
    />

    <!-- ============ 上传弹窗 ============ -->
    <el-dialog v-model="uploadVisible" title="上传文档" width="720px">
      <div class="field" style="margin-bottom: 14px">
        <label class="field-label">文件<span class="req">*</span>（可多选，元数据应用到全部文件）</label>
        <input
          ref="fileInput"
          type="file"
          multiple
          accept=".pdf,.docx,.doc,.txt,.md,.png,.jpg,.jpeg,.tiff"
          style="display: none"
          @change="onFileChange"
        />
        <el-button :icon="Upload" @click="fileInput?.click()">选择文件</el-button>
        <div v-if="uploadForm.files.length" class="files-preview">
          <span v-for="f in uploadForm.files" :key="f.name" class="tag gray">{{ f.name }}</span>
        </div>
      </div>

      <div class="field" style="margin-bottom: 14px">
        <label class="field-label">知识库<span class="req">*</span></label>
        <el-select v-model="uploadForm.kb_id" style="width: 100%">
          <el-option v-for="kb in kbStore.list" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
      </div>

      <div class="form-grid">
        <div class="field">
          <label class="field-label">标题</label>
          <el-input v-model="uploadForm.title" placeholder="留空自动抽取" />
        </div>
        <div class="field">
          <label class="field-label">文号</label>
          <el-input v-model="uploadForm.doc_no" placeholder="如 银保监会令2018年第3号" />
        </div>
        <div class="field">
          <label class="field-label">文档类型</label>
          <el-select v-model="uploadForm.doc_type" style="width: 100%">
            <el-option label="自动抽取" value="" />
            <el-option v-for="t in DOC_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
        </div>
        <div class="field">
          <label class="field-label">发布机构</label>
          <el-input v-model="uploadForm.issuing_authority" placeholder="留空自动抽取" />
        </div>
        <div class="field">
          <label class="field-label">发布日期</label>
          <el-input v-model="uploadForm.publish_date" type="date" />
        </div>
        <div class="field">
          <label class="field-label">生效日期</label>
          <el-input v-model="uploadForm.effective_date" type="date" />
        </div>
        <div class="field">
          <label class="field-label">失效日期</label>
          <el-input v-model="uploadForm.expiry_date" type="date" />
        </div>
        <div class="field">
          <label class="field-label">时效性</label>
          <el-select v-model="uploadForm.timeliness" style="width: 100%">
            <el-option label="自动判定" value="" />
            <el-option label="现行有效" value="effective" />
            <el-option label="已修订" value="amended" />
            <el-option label="已废止" value="repealed" />
            <el-option label="未知" value="unknown" />
          </el-select>
        </div>
      </div>
      <div class="field" style="margin-top: 14px">
        <label class="field-label">关键词</label>
        <el-input v-model="uploadForm.keywords" placeholder="逗号分隔，选填" />
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
      <template #footer>
        <el-button @click="uploadVisible = false">关闭</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">
          {{ uploading ? '上传中…' : '开始上传' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ============ 切片预览弹窗 ============ -->
    <el-dialog v-model="chunksVisible" :title="`切片预览 · ${chunksDoc?.title || ''}`" width="760px">
      <div v-if="chunksLoading" class="empty-tip">加载中…</div>
      <el-empty v-else-if="!chunks.length" description="暂无切片" :image-size="60" />
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
      <el-pagination
        v-if="chunksTotal > 20"
        style="margin-top: 12px; justify-content: center"
        layout="total, prev, pager, next"
        :total="chunksTotal"
        :page-size="20"
        v-model:current-page="chunksPage"
        @current-change="loadChunks"
      />
    </el-dialog>
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
