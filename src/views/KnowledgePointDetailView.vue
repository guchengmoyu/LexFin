<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { View } from '@element-plus/icons-vue'
import { kpApi, documentApi, systemApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { useKbStore } from '../stores/kb'

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const kbStore = useKbStore()

const kpId = route.params.id as string
const loading = ref(true)
const saving = ref(false)
const verifying = ref(false)
const error = ref('')

const kp = ref<any>(null)
const sources = ref<any[]>([])
const chunkTexts = ref<Record<string, string>>({})
const related = ref<any>({ context: [], same_topic: [], supersede: [] })

const config = reactive<{ categories: any[]; timeliness: any[] }>({ categories: [], timeliness: [] })
const form = reactive({
  title: '',
  content: '',
  category: '',
  sub_category: '',
  doc_no: '',
  issuing_authority: '',
  article_no: '',
  effective_date: '',
  expiry_date: '',
  timeliness: 'unknown',
  keywords: '',
  difficulty: 1,
  status: 'draft',
  primary_chunk_id: null as number | null,
})

const verifyForm = reactive({ verify_status: 'passed', comment: '', confidence: 0.9 })

// 关键词 Tag 增删（与 form.keywords 逗号字符串双向同步）
const keywordList = ref<string[]>([])
const keywordInput = ref('')
function syncKeywords() { form.keywords = keywordList.value.join(',') }
function addKeyword() {
  const v = keywordInput.value.trim()
  if (v && !keywordList.value.includes(v)) keywordList.value.push(v)
  keywordInput.value = ''
  syncKeywords()
}
function removeKeyword(i: number) { keywordList.value.splice(i, 1); syncKeywords() }

const categoryOptions = computed(() => config.categories)
const subOptions = computed(
  () => config.categories.find((c: any) => c.value === form.category)?.sub_categories || [],
)

const VERIFY_MAP: Record<string, { label: string; type: TagType }> = {
  passed: { label: '已校验通过', type: 'success' },
  doubted: { label: '存疑', type: 'warning' },
  rejected: { label: '已驳回', type: 'danger' },
  pending: { label: '待校验', type: 'info' },
}
const STATUS_MAP: Record<string, { label: string; type: TagType }> = {
  draft: { label: '草稿', type: 'info' },
  published: { label: '已发布', type: 'success' },
  archived: { label: '已归档', type: 'info' },
}
const DIFF_MAP: Record<number, string> = { 1: '基础', 2: '进阶', 3: '专业' }
const TIMELINESS_MAP: Record<string, string> = {
  effective: '现行有效',
  amended: '已修订',
  repealed: '已废止',
  unknown: '时效未知',
}

function fillForm(data: any) {
  form.title = data.title || ''
  form.content = data.content || ''
  form.category = data.category || ''
  form.sub_category = data.sub_category || ''
  form.doc_no = data.doc_no || ''
  form.issuing_authority = data.issuing_authority || ''
  form.article_no = data.article_no || ''
  form.effective_date = data.effective_date || ''
  form.expiry_date = data.expiry_date || ''
  form.timeliness = data.timeliness || 'unknown'
  form.keywords = data.keywords || ''
  form.difficulty = data.difficulty ?? 1
  form.status = data.status || 'draft'
  form.primary_chunk_id = data.primary_chunk_id ?? null
  keywordList.value = data.keywords ? String(data.keywords).split(',').map((k: string) => k.trim()).filter(Boolean) : []
  keywordInput.value = ''
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [detail, src, rel]: any[] = await Promise.all([
      kpApi.detail(kpId),
      kpApi.sources(kpId).catch(() => []),
      kpApi.related(kpId).catch(() => ({ context: [], same_topic: [], supersede: [] })),
    ])
    kp.value = detail
    sources.value = src || []
    related.value = rel || { context: [], same_topic: [], supersede: [] }
    fillForm(detail)
    verifyForm.confidence = detail.confidence ?? 0.9
    loadSourceTexts()
  } catch (e: any) {
    error.value = e?.message || '知识点加载失败'
  } finally {
    loading.value = false
  }
}

/** 来源切片只给 quote_text，完整原文按 document_id 拉取切片后按 chunk_id 匹配 */
async function loadSourceTexts() {
  const docIds = [...new Set(sources.value.map((s: any) => s.document_id).filter(Boolean))]
  const map: Record<string, string> = {}
  for (const id of docIds) {
    try {
      const data: any = await documentApi.chunks(id, 1, 100)
      ;(data.items || []).forEach((c: any) => {
        map[c.id] = c.raw_content || ''
      })
    } catch {
      /* 原文拉取失败时降级为 quote_text */
    }
  }
  chunkTexts.value = map
}

function escapeHtml(text: any): string {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** 原文中高亮 quote（返回已转义 HTML，避免 XSS） */
function highlightedSource(s: any): string {
  const text = chunkTexts.value[s.chunk_id] || s.quote_text || '（未绑定原文切片）'
  const quote = (s.quote_text || '').trim()
  const safe = escapeHtml(text)
  if (!quote) return safe
  const safeQuote = escapeHtml(quote)
  return safe.includes(safeQuote) ? safe.replace(safeQuote, `<mark>${safeQuote}</mark>`) : safe
}

async function save() {
  saving.value = true
  try {
    const payload = {
      title: form.title,
      content: form.content,
      category: form.category,
      sub_category: form.sub_category || null,
      doc_no: form.doc_no || null,
      issuing_authority: form.issuing_authority || null,
      article_no: form.article_no || null,
      effective_date: form.effective_date || null,
      expiry_date: form.expiry_date || null,
      timeliness: form.timeliness,
      keywords: form.keywords || null,
      difficulty: Number(form.difficulty) || 1,
      status: form.status,
      primary_chunk_id: form.primary_chunk_id,
    }
    const data: any = await kpApi.update(kpId, payload)
    kp.value = data
    fillForm(data)
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function submitVerify() {
  verifying.value = true
  try {
    const data: any = await kpApi.verify(kpId, {
      verify_status: verifyForm.verify_status,
      comment: verifyForm.comment || undefined,
      confidence: verifyForm.confidence,
    })
    kp.value = data
    ElMessage.success('校验结果已提交')
  } catch (e: any) {
    ElMessage.error(e?.message || '校验提交失败')
  } finally {
    verifying.value = false
  }
}

function openDoc(docId: number, pageNo?: number) {
  if (!docId) return
  router.push({ name: 'document-detail', params: { id: docId }, query: pageNo ? { page: pageNo } : {} })
}

onMounted(async () => {
  await kbStore.ensureLoaded()
  try {
    const cfg: any = await systemApi.config()
    config.categories = cfg.categories || []
    config.timeliness = cfg.timeliness || []
  } catch {
    config.categories = [
      { value: 'banking', label: '银行监管', sub_categories: [] },
      { value: 'securities', label: '证券行业', sub_categories: [] },
      { value: 'insurance', label: '保险制度', sub_categories: [] },
    ]
  }
  load()
})
</script>

<template>
  <section class="doc-page">
    <div class="doc-header">
      <div>
        <h1>知识点详情与人工校验</h1>
        <p v-if="kp">{{ kp.code }} · {{ kp.title }}</p>
        <p v-else>加载中…</p>
      </div>
      <div class="page-toolbar" style="margin: 0">
        <el-button @click="router.push({ name: 'knowledge-points' })">返回列表</el-button>
        <el-button v-if="auth.canManage" type="primary" :loading="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </el-button>
      </div>
    </div>

    <div v-if="error" class="empty-state error-text">{{ error }}</div>
    <div v-else-if="loading" class="empty-state">加载中…</div>

    <div v-else-if="kp" class="split-layout">
      <!-- 左侧：知识点编辑 -->
      <div class="panel">
        <h3 class="panel-title">
          <span>知识点内容</span>
          <el-tag size="small" :type="STATUS_MAP[form.status]?.type">{{ STATUS_MAP[form.status]?.label }}</el-tag>
        </h3>

        <label class="form-label">标题</label>
        <el-input v-model="form.title" :disabled="!auth.canManage" />

        <label class="form-label">正文</label>
        <el-input v-model="form.content" type="textarea" :rows="6" :disabled="!auth.canManage" />

        <div class="form-grid">
          <div>
            <label class="form-label">分类</label>
            <el-select v-model="form.category" style="width:100%" :disabled="!auth.canManage">
              <el-option value="" label="未分类" />
              <el-option v-for="c in categoryOptions" :key="c.value" :value="c.value" :label="c.label" />
            </el-select>
          </div>
          <div>
            <label class="form-label">子类</label>
            <el-select v-model="form.sub_category" style="width:100%" :disabled="!auth.canManage">
              <el-option value="" label="未设置" />
              <el-option v-for="s in subOptions" :key="s" :value="s" :label="s" />
            </el-select>
          </div>
          <div>
            <label class="form-label">难度</label>
            <el-select v-model="form.difficulty" style="width:100%" :disabled="!auth.canManage">
              <el-option v-for="(label, v) in DIFF_MAP" :key="v" :value="Number(v)" :label="label" />
            </el-select>
          </div>
          <div>
            <label class="form-label">时效</label>
            <el-select v-model="form.timeliness" style="width:100%" :disabled="!auth.canManage">
              <el-option v-for="t in config.timeliness" :key="t.value" :value="t.value" :label="t.label" />
            </el-select>
          </div>
          <div>
            <label class="form-label">发布状态</label>
            <el-select v-model="form.status" style="width:100%" :disabled="!auth.canManage">
              <el-option value="draft" label="草稿" />
              <el-option value="published" label="已发布" />
              <el-option value="archived" label="已归档" />
            </el-select>
          </div>
          <div>
            <label class="form-label">关键词</label>
            <div class="kw-row">
              <el-tag
                v-for="(kw, i) in keywordList"
                :key="`${kw}-${i}`"
                size="small"
                closable
                :disabled="!auth.canManage"
                @close="removeKeyword(i)"
              >{{ kw }}</el-tag>
              <el-input
                v-model="keywordInput"
                size="small"
                style="width: 140px"
                placeholder="回车添加"
                :disabled="!auth.canManage"
                @keydown.enter.prevent="addKeyword"
              />
            </div>
          </div>
        </div>

        <h3 class="panel-title" style="margin-top: 18px">出处信息</h3>
        <div class="form-grid">
          <div>
            <label class="form-label">文号</label>
            <el-input v-model="form.doc_no" :disabled="!auth.canManage" />
          </div>
          <div>
            <label class="form-label">发布机构</label>
            <el-input v-model="form.issuing_authority" :disabled="!auth.canManage" />
          </div>
          <div>
            <label class="form-label">条号</label>
            <el-input v-model="form.article_no" :disabled="!auth.canManage" />
          </div>
          <div>
            <label class="form-label">生效日期</label>
            <el-input v-model="form.effective_date" type="date" :disabled="!auth.canManage" />
          </div>
          <div>
            <label class="form-label">失效日期</label>
            <el-input v-model="form.expiry_date" type="date" :disabled="!auth.canManage" />
          </div>
        </div>

        <!-- 校验提交面板（docs/07 §4.4） -->
        <div v-if="auth.canManage" class="verify-box">
          <h3 class="panel-title">提交校验</h3>
          <div class="verify-row">
            <el-radio-group v-model="verifyForm.verify_status">
              <el-radio-button v-for="(v, key) in VERIFY_MAP" :key="key" :value="key">{{ v.label }}</el-radio-button>
            </el-radio-group>
          </div>
          <label class="form-label">校验意见</label>
          <el-input v-model="verifyForm.comment" type="textarea" :rows="2" placeholder="可选，最多 500 字" />
          <label class="form-label">置信度：{{ Number(verifyForm.confidence).toFixed(2) }}</label>
          <el-slider v-model="verifyForm.confidence" :min="0" :max="1" :step="0.01" />
          <div style="margin-top: 12px">
            <el-button type="primary" :loading="verifying" @click="submitVerify">
              {{ verifying ? '提交中…' : '提交校验' }}
            </el-button>
          </div>
        </div>

        <div v-else class="panel" style="margin-top: 16px">
          <h3 class="panel-title">校验状态</h3>
          <el-tag :type="VERIFY_MAP[kp.verify_status]?.type">{{ VERIFY_MAP[kp.verify_status]?.label }}</el-tag>
          <span style="margin-left: 10px; font-size: 12.5px; color: var(--text-3)">
            置信度 {{ kp.confidence == null ? '—' : kp.confidence.toFixed(2) }}
          </span>
        </div>
      </div>

      <!-- 右侧：来源原文对照 -->
      <div class="panel">
        <h3 class="panel-title">
          <span>来源原文</span>
          <el-tag size="small" type="info">{{ sources.length }} 条来源</el-tag>
        </h3>

        <el-empty v-if="!sources.length" description="尚未绑定来源切片" />
        <div v-for="(s, i) in sources" :key="s.source_id" class="source-item">
          <div class="source-head">
            <span class="cite-idx">[{{ i + 1 }}]</span>
            <span
              class="cite-article"
              :class="{ 'is-primary': s.is_primary }"
            >{{ s.article_no || '未标注条号' }}</span>
            <el-tag v-if="s.is_primary" size="small">主要来源</el-tag>
            <span class="spacer"></span>
            <el-button link type="primary" :icon="View" @click="openDoc(s.document_id, s.page_no)">查看原文</el-button>
          </div>
          <div class="source-quote" v-html="highlightedSource(s)"></div>
          <div class="cite-foot">
            <span>文档 #{{ s.document_id }}</span>
            <span>第 {{ s.page_no ?? '—' }} 页</span>
            <span>切片 #{{ s.chunk_id }}</span>
          </div>
        </div>

        <h3 class="panel-title" style="margin-top: 20px">关联条文</h3>
        <div v-for="group in ['context', 'same_topic', 'supersede']" :key="group" class="related-group">
          <div class="related-title">
            {{ group === 'context' ? '同制度上下文' : group === 'same_topic' ? '同主题知识点' : '新旧替代' }}
            <el-tag size="small" type="info">{{ related[group]?.length || 0 }}</el-tag>
          </div>
          <el-empty v-if="!related[group]?.length" description="暂无" :image-size="60" />
          <div v-for="r in related[group]" :key="`${group}-${r.id || r.chunk_id || r.kp_id}`" class="cite-card">
            <div class="cite-top">
              <span class="cite-idx">{{ r.code || `#${r.chunk_id || r.id}` }}</span>
              <span class="cite-doc">{{ r.title || r.doc_title || r.article_no || '相关条文' }}</span>
            </div>
            <div class="cite-snippet">{{ r.snippet || r.content || '' }}</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.form-label {
  display: block;
  font-size: 13px;
  color: var(--text-2);
  margin: 12px 0 6px;
}

.verify-box {
  margin-top: 18px;
  border-top: 1px dashed var(--border);
  padding-top: 8px;
}

.verify-row {
  margin-bottom: 6px;
}

.kw-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.source-item {
  border-bottom: 1px dashed var(--border);
  padding-bottom: 12px;
  margin-bottom: 12px;
}

.source-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.source-head .spacer {
  flex: 1;
}

.cite-article.is-primary {
  background: #e7f7ee;
  color: #15803d;
}

.related-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-2);
  margin: 12px 0 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
