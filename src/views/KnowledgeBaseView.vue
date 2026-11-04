<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { kbApi, taskApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { useKbStore } from '../stores/kb'
import type { KbInfo, TaskItem } from '../types'

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const kbStore = useKbStore()

// ---------------------------------------------------------------- 页签（入库任务并入本界面）
const tab = ref<'kb' | 'tasks'>(route.query.tab === 'tasks' ? 'tasks' : 'kb')

// ---------------------------------------------------------------- 知识库
const loading = ref(false)
const list = ref<KbInfo[]>([])
const stats = ref<any>(null)
const statsLoading = ref(false)

const dialog = ref(false)
const editing = ref<KbInfo | null>(null)
const form = reactive({ code: '', name: '', category: 'banking', description: '' })

const CATEGORY_LABEL: Record<string, string> = { banking: '银行监管', securities: '证券行业', insurance: '保险制度' }
const TIMELINESS_LABEL: Record<string, string> = {
  effective: '现行有效',
  amended: '已修订',
  repealed: '已废止',
  unknown: '时效未知',
}

async function load() {
  loading.value = true
  try {
    list.value = (await kbApi.list()) || []
  } catch (e: any) {
    ElMessage.error(e.message || '知识库加载失败')
  } finally {
    loading.value = false
  }
}

async function loadStats(kb: KbInfo) {
  statsLoading.value = true
  try {
    stats.value = await kbApi.stats(kb.id)
  } catch (e: any) {
    ElMessage.error(e.message || '统计加载失败')
  } finally {
    statsLoading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { code: '', name: '', category: 'banking', description: '' })
  dialog.value = true
}

function openEdit(kb: KbInfo) {
  editing.value = kb
  Object.assign(form, {
    code: kb.code,
    name: kb.name,
    category: kb.category,
    description: kb.description || '',
  })
  dialog.value = true
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写知识库名称')
    return
  }
  try {
    if (editing.value) {
      await kbApi.update(editing.value.id, {
        name: form.name,
        description: form.description || null,
      })
    } else {
      if (!form.code.trim()) {
        ElMessage.warning('请填写知识库编码')
        return
      }
      await kbApi.create({
        code: form.code.trim(),
        name: form.name.trim(),
        category: form.category,
        description: form.description || null,
      })
    }
    dialog.value = false
    kbStore.loaded = false
    await kbStore.ensureLoaded()
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '保存失败')
  }
}

async function remove(kb: KbInfo) {
  const ok = await ElMessageBox.confirm(`删除知识库「${kb.name}」？该操作为软删除。`, '提示', { type: 'warning' })
    .then(() => true)
    .catch(() => false)
  if (!ok) return
  try {
    await kbApi.remove(kb.id)
    if (stats.value?.kb_id === kb.id) stats.value = null
    kbStore.loaded = false
    await kbStore.ensureLoaded()
    await load()
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}

// ---------------------------------------------------------------- 入库任务（原 TaskListView 并入）
const tasksLoading = ref(false)
const tasks = ref<TaskItem[]>([])
const tasksTotal = ref(0)
const tasksPages = ref(1)
const tasksPage = ref(1)
const tasksSize = ref(10)
const taskFilters = reactive({ status: '', kb_id: '' })
const focused = ref<TaskItem | null>(null)

const STATUS_MAP: Record<string, { label: string; type: TagType }> = {
  queued: { label: '排队中', type: 'info' },
  parsing: { label: '正在解析 / OCR', type: 'warning' },
  cleaning: { label: '正在清洗文本', type: 'warning' },
  chunking: { label: '正在切分条文', type: 'warning' },
  embedding: { label: '正在向量化', type: 'warning' },
  indexing: { label: '正在写入向量库', type: 'warning' },
  success: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
}
const RUNNING = ['queued', 'parsing', 'cleaning', 'chunking', 'embedding', 'indexing']

let timer: ReturnType<typeof setInterval> | null = null
const hasRunning = computed(() => tasks.value.some((t) => RUNNING.includes(t.status)))

async function loadTasks() {
  tasksLoading.value = true
  try {
    const data: any = await taskApi.list({
      status: taskFilters.status,
      kb_id: taskFilters.kb_id,
      page: tasksPage.value,
      size: tasksSize.value,
    })
    tasks.value = data.items || []
    tasksTotal.value = data.total || 0
    tasksPages.value = data.pages || 1
  } catch (e: any) {
    ElMessage.error(e.message || '任务列表加载失败')
  } finally {
    tasksLoading.value = false
  }
}

async function loadFocused(taskNo: string) {
  try {
    focused.value = await taskApi.detail(taskNo)
  } catch {
    focused.value = null
  }
}

function goTasksPage(p: number) {
  if (p < 1 || p > tasksPages.value) return
  tasksPage.value = p
  loadTasks()
}

function onTasksSizeChange() {
  tasksPage.value = 1
  loadTasks()
}

function progressOf(t: any) {
  return Math.max(0, Math.min(100, Number(t.progress) || 0))
}

function barClass(t: any) {
  if (t.status === 'success') return 'done'
  if (t.status === 'failed') return 'failed'
  return ''
}

function openDoc(id: any) {
  if (id) router.push({ name: 'document-detail', params: { id } })
}

onMounted(async () => {
  await kbStore.ensureLoaded()
  load()
  if (route.query.task_no) {
    tab.value = 'tasks'
    await loadFocused(route.query.task_no as string)
  }
  if (tab.value === 'tasks') await loadTasks()
  timer = setInterval(() => {
    if (tab.value !== 'tasks') return
    if (hasRunning.value) loadTasks()
    if (focused.value && RUNNING.includes(focused.value.status)) loadFocused(focused.value.task_no)
  }, 1500)
})

function onTabChange(name: 'kb' | 'tasks') {
  if (name === 'tasks' && !tasks.value.length) loadTasks()
}

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <section class="doc-page">
    <div class="doc-header">
      <div>
        <h1>知识库管理</h1>
        <p>知识库统计与文档入库任务进度（任务每 1.5 秒自动刷新）</p>
      </div>
      <div class="page-toolbar" style="margin: 0">
        <el-button v-if="tab === 'tasks'" :icon="Refresh" @click="loadTasks">刷新</el-button>
        <el-button v-if="tab === 'kb' && auth.isAdmin" type="primary" @click="openCreate">新建知识库</el-button>
      </div>
    </div>

    <div class="tabs">
      <button class="tab" :class="{ active: tab === 'kb' }" @click="tab = 'kb'; onTabChange('kb')">知识库</button>
      <button class="tab" :class="{ active: tab === 'tasks' }" @click="tab = 'tasks'; onTabChange('tasks')">入库任务</button>
    </div>

    <!-- ==================== 知识库 ==================== -->
    <template v-if="tab === 'kb'">
      <div v-if="loading" class="empty-state">加载中…</div>
      <el-empty v-else-if="!list.length" description="暂无知识库" />

      <div v-else class="kb-grid">
        <div v-for="kb in list" :key="kb.id" class="panel kb-card">
          <div class="kb-head">
            <div>
              <div class="kb-name">{{ kb.name }}</div>
              <div class="doc-no">{{ kb.code }} · {{ CATEGORY_LABEL[kb.category || ''] || kb.category }}</div>
            </div>
            <el-tag :type="kb.status === 1 ? 'success' : 'info'">
              {{ kb.status === 1 ? '启用' : '停用' }}
            </el-tag>
          </div>
          <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>
          <div class="kb-metrics">
            <span><b>{{ kb.doc_count ?? 0 }}</b> 文档</span>
            <span><b>{{ kb.chunk_count ?? 0 }}</b> 切片</span>
            <span><b>{{ kb.kp_count ?? 0 }}</b> 知识点</span>
          </div>
          <div class="kb-actions">
            <el-button link type="primary" size="small" @click="loadStats(kb)">查看统计</el-button>
            <el-button v-if="auth.isAdmin" link type="primary" size="small" @click="openEdit(kb)">编辑</el-button>
            <el-button v-if="auth.isAdmin" link type="danger" size="small" @click="remove(kb)">删除</el-button>
          </div>
        </div>
      </div>

      <div v-if="stats" class="panel" style="margin-top: 16px">
        <h3 class="panel-title">
          <span>{{ stats.name }} · 统计</span>
          <el-button link type="primary" @click="stats = null">关闭</el-button>
        </h3>
        <div v-if="statsLoading" class="empty-state">加载中…</div>
        <template v-else>
          <div class="metric-grid">
            <div class="metric-card"><div class="metric-num">{{ stats.doc_count }}</div><div class="metric-label">文档（就绪 {{ stats.ready_doc_count }} / 失败 {{ stats.error_doc_count }}）</div></div>
            <div class="metric-card"><div class="metric-num">{{ stats.chunk_count }}</div><div class="metric-label">切片</div></div>
            <div class="metric-card highlight"><div class="metric-num">{{ stats.kp_count }}</div><div class="metric-label">知识点（已发布 {{ stats.published_kp_count }}）</div></div>
            <div class="metric-card"><div class="metric-num">{{ stats.verified_kp_count }}</div><div class="metric-label">已校验通过</div></div>
            <div class="metric-card"><div class="metric-num">{{ stats.verify_pass_rate == null ? '—' : `${(stats.verify_pass_rate * 100).toFixed(1)}%` }}</div><div class="metric-label">校验通过率</div></div>
          </div>

          <div class="split-layout">
            <div>
              <h3 class="panel-title">子类分布</h3>
              <el-empty v-if="!stats.sub_category_distribution?.length" description="暂无数据" :image-size="60" />
              <div v-for="s in stats.sub_category_distribution" :key="s.sub_category" class="bar-row">
                <span class="bar-label">{{ s.sub_category }}</span>
                <span class="bar-track">
                  <span
                    class="bar-fill"
                    :style="{ width: `${(s.count / Math.max(1, ...stats.sub_category_distribution.map((x: any) => x.count))) * 100}%` }"
                  ></span>
                </span>
                <span>{{ s.count }}</span>
              </div>
            </div>
            <div>
              <h3 class="panel-title">时效分布</h3>
              <el-empty v-if="!stats.timeliness_distribution?.length" description="暂无数据" :image-size="60" />
              <div v-for="t in stats.timeliness_distribution" :key="t.timeliness" class="bar-row">
                <span class="bar-label">{{ TIMELINESS_LABEL[t.timeliness] || t.timeliness }}</span>
                <span class="bar-track">
                  <span
                    class="bar-fill"
                    :style="{ width: `${(t.count / Math.max(1, ...stats.timeliness_distribution.map((x: any) => x.count))) * 100}%` }"
                  ></span>
                </span>
                <span>{{ t.count }}</span>
              </div>
            </div>
          </div>
        </template>
      </div>
    </template>

    <!-- ==================== 入库任务 ==================== -->
    <template v-else>
      <div class="page-toolbar">
        <el-select v-model="taskFilters.status" class="filter-item" @change="tasksPage = 1; loadTasks()">
          <el-option label="全部状态" value="" />
          <el-option v-for="(v, k) in STATUS_MAP" :key="k" :label="v.label" :value="k" />
        </el-select>
        <el-select v-model="taskFilters.kb_id" class="filter-item" @change="tasksPage = 1; loadTasks()">
          <el-option label="全部知识库" value="" />
          <el-option v-for="kb in kbStore.list" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
        <span class="spacer"></span>
        <el-tag type="info">共 {{ tasksTotal }} 个任务</el-tag>
      </div>

      <div v-if="focused" class="panel" style="margin-bottom: 14px">
        <h3 class="panel-title">
          <span>任务详情 · {{ focused.task_no }}</span>
          <el-button link type="primary" @click="focused = null">关闭</el-button>
        </h3>
        <div class="kv-list">
          <span class="kv-key">状态</span>
          <span class="kv-val">
            <el-tag :type="STATUS_MAP[focused.status]?.type || 'info'">{{ STATUS_MAP[focused.status]?.label }}</el-tag>
            <span style="margin-left: 8px">{{ focused.stage_message || '' }}</span>
          </span>
          <span class="kv-key">文档</span>
          <span class="kv-val">
            <el-button link type="primary" @click="openDoc(focused.document_id)">#{{ focused.document_id }}</el-button>
          </span>
          <span class="kv-key">进度</span>
          <span class="kv-val">
            <div class="progress-track" style="max-width: 420px">
              <div class="progress-bar" :class="barClass(focused)" :style="{ width: `${progressOf(focused)}%` }"></div>
            </div>
            <div class="doc-no">{{ progressOf(focused) }}% · 切片 {{ focused.done_chunks || 0 }}/{{ focused.total_chunks || 0 }}</div>
          </span>
          <span class="kv-key">耗时</span>
          <span class="kv-val">{{ focused.duration_ms ? `${(focused.duration_ms / 1000).toFixed(1)}s` : '—' }}</span>
          <span class="kv-key">时间</span>
          <span class="kv-val">{{ focused.started_at || '—' }} → {{ focused.finished_at || '进行中' }}</span>
        </div>
        <div v-if="focused.error_message" class="error-text" style="margin-top: 10px">{{ focused.error_message }}</div>
      </div>

      <div class="table-wrap">
        <el-table v-loading="tasksLoading" :data="tasks">
          <el-table-column label="任务号" min-width="200">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="loadFocused(row.task_no)">{{ row.task_no }}</el-button>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="90" prop="task_type" />
          <el-table-column label="状态" width="170">
            <template #default="{ row }">
              <el-tag :type="STATUS_MAP[row.status]?.type || 'info'">{{ STATUS_MAP[row.status]?.label || row.status }}</el-tag>
              <div class="doc-no">{{ row.stage_message }}</div>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="220">
            <template #default="{ row }">
              <div class="progress-track">
                <div class="progress-bar" :class="barClass(row)" :style="{ width: `${progressOf(row)}%` }"></div>
              </div>
              <div class="doc-no">{{ progressOf(row) }}%</div>
            </template>
          </el-table-column>
          <el-table-column label="切片" width="110">
            <template #default="{ row }">{{ row.done_chunks || 0 }} / {{ row.total_chunks || 0 }}</template>
          </el-table-column>
          <el-table-column label="耗时" width="100">
            <template #default="{ row }">{{ row.duration_ms ? `${(row.duration_ms / 1000).toFixed(1)}s` : '—' }}</template>
          </el-table-column>
          <el-table-column label="开始 / 结束" width="170">
            <template #default="{ row }">
              <div>{{ row.started_at || '—' }}</div>
              <div class="doc-no">{{ row.finished_at || '' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="文档" width="80">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openDoc(row.document_id)">#{{ row.document_id }}</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无任务" :image-size="60" />
          </template>
        </el-table>
      </div>

      <el-pagination
        style="margin-top: 14px; justify-content: flex-end"
        layout="total, prev, pager, next, sizes"
        :total="tasksTotal"
        :page-sizes="[10, 20, 50]"
        v-model:current-page="tasksPage"
        v-model:page-size="tasksSize"
        @current-change="goTasksPage"
        @size-change="onTasksSizeChange"
      />
    </template>

    <!-- 新建 / 编辑知识库弹窗 -->
    <el-dialog v-model="dialog" :title="editing ? '编辑知识库' : '新建知识库'" width="520px">
      <label class="form-label">编码</label>
      <el-input v-model="form.code" :disabled="!!editing" placeholder="如 banking" />
      <label class="form-label">名称</label>
      <el-input v-model="form.name" placeholder="如 银行监管制度库" />
      <label class="form-label">分类</label>
      <el-select v-model="form.category" :disabled="!!editing" style="width: 100%">
        <el-option v-for="(label, k) in CATEGORY_LABEL" :key="k" :label="label" :value="k" />
      </el-select>
      <label class="form-label">描述</label>
      <el-input v-model="form.description" type="textarea" :rows="3" />
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.form-label {
  display: block;
  font-size: 13px;
  color: var(--text-2);
  margin: 12px 0 6px;
}

.form-label:first-child {
  margin-top: 0;
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

.kb-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.kb-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-1);
}

.kb-desc {
  margin: 10px 0;
  font-size: 12.5px;
  color: var(--text-3);
  min-height: 34px;
  line-height: 1.6;
}

.kb-metrics {
  display: flex;
  gap: 16px;
  font-size: 12.5px;
  color: var(--text-2);
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}

.kb-metrics b {
  color: var(--primary);
  font-size: 14px;
}

.kb-actions {
  display: flex;
  gap: 4px;
  margin-top: 10px;
}
</style>
