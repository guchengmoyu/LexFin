<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Refresh } from '@element-plus/icons-vue'
import { documentApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { useKbStore } from '../stores/kb'
import type { DocChunk, DocItem } from '../types'

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const kbStore = useKbStore()

const docId = route.params.id as string
const loading = ref(true)
const error = ref('')
const doc = ref<DocItem | null>(null)
const chunks = ref<DocChunk[]>([])
const chunkLoading = ref(false)
const page = ref(1)
const size = ref(20)
const total = ref(0)
const expanded = reactive<Record<string | number, boolean>>({})
const reparseTask = ref('')

const STATUS_MAP: Record<string, { label: string; type: TagType }> = {
  pending: { label: '待解析', type: 'info' },
  parsing: { label: '解析中', type: 'warning' },
  embedding: { label: '向量化中', type: 'warning' },
  ready: { label: '就绪', type: 'success' },
  error: { label: '失败', type: 'danger' },
  archived: { label: '已归档', type: 'info' },
}
const TIMELINESS_MAP: Record<string, { label: string; type: TagType }> = {
  effective: { label: '现行有效', type: 'success' },
  amended: { label: '已修订', type: 'warning' },
  repealed: { label: '已废止', type: 'danger' },
  unknown: { label: '时效未知', type: 'info' },
}
const DOC_TYPE_MAP: Record<string, string> = {
  law: '法律',
  regulation: '行政法规/办法',
  rule: '部门规章/细则',
  notice: '通知/公告',
  guideline: '自律规范/指引',
  other: '其他',
}
const PARSE_MAP: Record<string, string> = { text: '文本层', ocr: 'OCR', mixed: '混合' }

const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

async function loadDoc() {
  loading.value = true
  error.value = ''
  try {
    doc.value = await documentApi.detail(docId)
    const pageQuery = Number(route.query.page)
    if (pageQuery > 0) page.value = pageQuery
    await loadChunks()
  } catch (e: any) {
    error.value = e.message || '文档加载失败'
  } finally {
    loading.value = false
  }
}

async function loadChunks() {
  chunkLoading.value = true
  try {
    const data: any = await documentApi.chunks(docId, page.value, size.value)
    chunks.value = data.items || []
    total.value = data.total || 0
  } catch (e: any) {
    ElMessage.error(e.message || '切片加载失败')
  } finally {
    chunkLoading.value = false
  }
}

function goPage(p: number) {
  if (p < 1 || p > pages.value) return
  page.value = p
  loadChunks()
}

function onSizeChange() {
  page.value = 1
  loadChunks()
}

async function reparse() {
  const ok = await ElMessageBox.confirm('重新解析将清空现有切片并重建索引，确认继续？', '提示', { type: 'warning' })
    .then(() => true)
    .catch(() => false)
  if (!ok) return
  try {
    const data: any = await documentApi.reparse(docId)
    reparseTask.value = data.task_no
    ElMessage.success(`已提交重新解析任务：${data.task_no}`)
  } catch (e: any) {
    ElMessage.error(e.message || '提交失败')
  }
}

async function download() {
  try {
    await documentApi.download(docId, doc.value?.file_name || `document-${docId}`)
  } catch (e: any) {
    ElMessage.error(e.message || '下载失败')
  }
}

onMounted(async () => {
  await kbStore.ensureLoaded()
  loadDoc()
})
</script>

<template>
  <section class="doc-page">
    <div class="doc-header">
      <div>
        <h1>文档详情</h1>
        <p v-if="doc">{{ doc.title }} · {{ doc.file_name }}</p>
        <p v-else>加载中…</p>
      </div>
      <div class="page-toolbar" style="margin: 0">
        <el-button @click="router.push({ name: 'documents' })">返回列表</el-button>
        <el-button :icon="Download" @click="download">下载原文</el-button>
        <el-button v-if="auth.canManage" type="primary" :icon="Refresh" @click="reparse">重新解析</el-button>
      </div>
    </div>

    <div v-if="error" class="empty-state error-text">{{ error }}</div>
    <div v-else-if="loading" class="empty-state">加载中…</div>

    <template v-else-if="doc">
      <div v-if="reparseTask" class="panel" style="margin-bottom: 14px">
        <el-tag type="primary">解析任务已提交</el-tag>
        <span style="margin-left: 10px; font-size: 13px">
          任务号 {{ reparseTask }}
        </span>
        <el-button
          link
          type="primary"
          style="margin-left: 12px"
          @click="router.push({ name: 'tasks', query: { task_no: reparseTask } })"
        >
          查看任务进度
        </el-button>
      </div>

      <div class="panel" style="margin-bottom: 16px">
        <h3 class="panel-title">
          <span>元数据</span>
          <span>
            <el-tag :type="STATUS_MAP[doc.status]?.type || 'info'">{{ STATUS_MAP[doc.status]?.label }}</el-tag>
            <el-tag :type="TIMELINESS_MAP[doc.timeliness ?? 'current']?.type || 'info'" style="margin-left: 6px">
              {{ TIMELINESS_MAP[doc.timeliness ?? 'current']?.label || doc.timeliness }}
            </el-tag>
          </span>
        </h3>
        <div class="kv-list">
          <span class="kv-key">所属知识库</span><span class="kv-val">{{ kbStore.kbName(doc.kb_id ?? '') }}</span>
          <span class="kv-key">文号</span><span class="kv-val">{{ doc.doc_no || '—' }}</span>
          <span class="kv-key">文档类型</span><span class="kv-val">{{ DOC_TYPE_MAP[doc.doc_type] || doc.doc_type || '—' }}</span>
          <span class="kv-key">分类</span><span class="kv-val">{{ doc.category || '—' }}</span>
          <span class="kv-key">发布机构</span><span class="kv-val">{{ doc.issuing_authority || '—' }}</span>
          <span class="kv-key">发布日期</span><span class="kv-val">{{ doc.publish_date || '—' }}</span>
          <span class="kv-key">生效日期</span><span class="kv-val">{{ doc.effective_date || '—' }}</span>
          <span class="kv-key">失效日期</span><span class="kv-val">{{ doc.expiry_date || '—' }}</span>
          <span class="kv-key">解析方式</span><span class="kv-val">{{ PARSE_MAP[doc.parse_method] || doc.parse_method || '—' }}</span>
          <span class="kv-key">页数 / 切片</span><span class="kv-val">{{ doc.page_count ?? '—' }} 页 / {{ doc.chunk_count ?? 0 }} 片</span>
          <span class="kv-key">关键词</span><span class="kv-val">{{ doc.keywords || '—' }}</span>
          <span class="kv-key">上传时间</span><span class="kv-val">{{ doc.created_at || '—' }}</span>
        </div>
        <div v-if="doc.warnings?.length" class="error-text" style="margin-top: 10px">
          解析告警：{{ doc.warnings.join('；') }}
        </div>
      </div>

      <div class="panel">
        <h3 class="panel-title">
          <span>切片列表</span>
          <el-tag type="info">共 {{ total }} 片 · 每页 {{ size }}</el-tag>
        </h3>
        <el-table v-loading="chunkLoading" :data="chunks">
          <el-table-column label="序号" width="70" prop="chunk_index" />
          <el-table-column label="章节 / 条号" width="130">
            <template #default="{ row }">
              <div>{{ row.chapter_no || '—' }}</div>
              <div class="doc-no">{{ row.article_no || '' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="页码" width="110">
            <template #default="{ row }">
              {{ row.page_start ?? '—' }}<span v-if="row.page_end && row.page_end !== row.page_start">~{{ row.page_end }}</span>
            </template>
          </el-table-column>
          <el-table-column label="字数" width="80" prop="char_count" />
          <el-table-column label="原文片段" min-width="320">
            <template #default="{ row }">
              <div class="chunk-text" :class="{ expanded: expanded[row.id] }">{{ row.raw_content }}</div>
              <el-button link type="primary" size="small" @click="expanded[row.id] = !expanded[row.id]">
                {{ expanded[row.id] ? '收起' : '展开全文' }}
              </el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无切片" :image-size="60" />
          </template>
        </el-table>

        <el-pagination
          style="margin-top: 14px; justify-content: flex-end"
          layout="total, prev, pager, next, sizes"
          :total="total"
          :page-sizes="[20, 50, 100]"
          v-model:current-page="page"
          v-model:page-size="size"
          @current-change="goPage"
          @size-change="onSizeChange"
        />
      </div>
    </template>
  </section>
</template>

<style scoped>
.chunk-text {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-2);
  max-width: 640px;
}

.chunk-text.expanded {
  display: block;
  -webkit-line-clamp: unset;
  white-space: pre-wrap;
}
</style>
