<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { taskApi } from '../api'
import { useKbStore } from '../stores/kb'
import type { TaskItem } from '../types'

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const route = useRoute()
const router = useRouter()
const kbStore = useKbStore()

const loading = ref(false)
const tasks = ref<TaskItem[]>([])
const total = ref(0)
const pages = ref(1)
const page = ref(1)
const size = ref(10)
const filters = reactive({ status: '', kb_id: '' })
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

async function load() {
  loading.value = true
  try {
    const data: any = await taskApi.list({
      status: filters.status,
      kb_id: filters.kb_id,
      page: page.value,
      size: size.value,
    })
    tasks.value = data.items || []
    total.value = data.total || 0
    pages.value = data.pages || 1
  } catch (e: any) {
    ElMessage.error(e.message || '任务列表加载失败')
  } finally {
    loading.value = false
  }
}

async function loadFocused(taskNo: string) {
  try {
    focused.value = await taskApi.detail(taskNo)
  } catch {
    focused.value = null
  }
}

function goPage(p: number) {
  if (p < 1 || p > pages.value) return
  page.value = p
  load()
}

function onSizeChange() {
  page.value = 1
  load()
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
  if (route.query.task_no) await loadFocused(route.query.task_no as string)
  await load()
  timer = setInterval(() => {
    if (hasRunning.value) load()
    if (focused.value && RUNNING.includes(focused.value.status)) loadFocused(focused.value.task_no)
  }, 1500)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <section class="doc-page">
    <div class="doc-header">
      <div>
        <h1>入库任务</h1>
        <p>任务进度每 1.5 秒自动刷新；完成后自动停止轮询</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <div class="page-toolbar">
      <el-select v-model="filters.status" class="filter-item" @change="page = 1; load()">
        <el-option label="全部状态" value="" />
        <el-option v-for="(v, k) in STATUS_MAP" :key="k" :label="v.label" :value="k" />
      </el-select>
      <el-select v-model="filters.kb_id" class="filter-item" @change="page = 1; load()">
        <el-option label="全部知识库" value="" />
        <el-option v-for="kb in kbStore.list" :key="kb.id" :label="kb.name" :value="kb.id" />
      </el-select>
      <span class="spacer"></span>
      <el-tag type="info">共 {{ total }} 个任务</el-tag>
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
      <el-table v-loading="loading" :data="tasks">
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
      :total="total"
      :page-sizes="[10, 20, 50]"
      v-model:current-page="page"
      v-model:page-size="size"
      @current-change="goPage"
      @size-change="onSizeChange"
    />
  </section>
</template>
