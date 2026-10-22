<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Upload, Download } from '@element-plus/icons-vue'
import { kpApi } from '../api'
import { useKbStore } from '../stores/kb'
import type { KnowledgePoint } from '../types'

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const kbStore = useKbStore()
const router = useRouter()

const list = ref<KnowledgePoint[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(15)
const loading = ref(false)
const filters = reactive<{ kbId: string | number; category: string; subCategory: string; verifyStatus: string; status: string; timeliness: string; difficulty: string; keyword: string }>({ kbId: '', category: '', subCategory: '', verifyStatus: '', status: '', timeliness: '', difficulty: '', keyword: '' })
const stats = ref<any>(null)

const VERIFY_MAP: Record<string, { label: string; type: TagType }> = {
  pending: { label: '待校验', type: 'info' },
  passed: { label: '已通过', type: 'success' },
  doubted: { label: '存疑', type: 'warning' },
  rejected: { label: '已驳回', type: 'danger' },
}
const STATUS_MAP: Record<string, { label: string; type: TagType }> = {
  draft: { label: '草稿', type: 'info' },
  published: { label: '已发布', type: 'success' },
  archived: { label: '已归档', type: 'info' },
}
const DIFF_MAP: Record<number, { label: string; type: TagType }> = {
  1: { label: '易', type: 'success' },
  2: { label: '中', type: 'warning' },
  3: { label: '难', type: 'danger' },
}
const TIMELINESS: Record<string, { label: string; type: TagType }> = {
  effective: { label: '现行有效', type: 'success' },
  amended: { label: '已修订', type: 'warning' },
  repealed: { label: '已废止', type: 'danger' },
  unknown: { label: '未知', type: 'info' },
}

const SUB_CATS: Record<string, string[]> = {
  banking: ['资本管理','流动性风险','信用风险','市场风险','操作风险','公司治理','信息披露','支付结算','反洗钱','消费者权益保护','账户管理','信贷业务'],
  securities: ['发行上市','信息披露','交易规则','投资者适当性','证券公司治理','资产管理','债券业务','融资融券','投资顾问','基金销售'],
  insurance: ['产品条款','销售规范','偿付能力','资金运用','理赔服务','客户权益','合规经营','保险营销','再保险','精算'],
}

function catLabel(c?: string): string {
  return c === 'banking' ? '银行' : c === 'securities' ? '证券' : c === 'insurance' ? '保险' : c || ''
}

function statColor(v: any): string {
  const t = VERIFY_MAP[v?.verify_status]?.type
  return t === 'success' ? 'var(--success)' : t === 'danger' ? 'var(--danger)' : 'var(--text-2)'
}

const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

async function loadList() {
  loading.value = true
  try {
    const data: any = await kpApi.list({
      kb_id: filters.kbId, category: filters.category, sub_category: filters.subCategory,
      verify_status: filters.verifyStatus, status: filters.status, timeliness: filters.timeliness,
      difficulty: filters.difficulty, keyword: filters.keyword,
      page: page.value, size: size.value,
    })
    list.value = data.items || []
    total.value = data.total || 0
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}
async function loadStats() {
  try { stats.value = await kpApi.stats() } catch {/*ignore*/}
}
function doSearch() { page.value = 1; loadList() }
function goPage(p: number) { page.value = Math.min(Math.max(1, p), pages.value); loadList() }

// 导入
const importVisible = ref(false)
const importForm = reactive<{ file: any; kb_id: string | number; dryRun: boolean }>({ file: null, kb_id: '', dryRun: true })
const importResult = ref<any>(null)
const importing = ref(false)
function openImport() {
  importForm.kb_id = kbStore.list[0]?.id ?? ''; importForm.file = null; importForm.dryRun = true
  importResult.value = null; importVisible.value = true
}
function onImportFile(file: any) { importForm.file = file?.raw ?? file }
async function submitImport() {
  if (!importForm.file) { ElMessage.warning('请选择文件'); return }
  if (!importForm.kb_id) { ElMessage.warning('请选择知识库'); return }
  importing.value = true
  try {
    const fd = new FormData()
    fd.append('file', importForm.file)
    fd.append('kb_id', String(importForm.kb_id))
    fd.append('dry_run', importForm.dryRun ? 'true' : 'false')
    const res = await kpApi.importFile(fd)
    importResult.value = res
    if (!importForm.dryRun) { loadList(); loadStats() }
  } catch (e: any) { ElMessage.error(e?.message || '导入失败') } finally { importing.value = false }
}

// 编辑
const editor = ref(false)
const editorTitle = ref('')
const editPayload = reactive<Record<string, any>>({ id: null, kb_id: '', title: '', content: '', category: '', sub_category: '', doc_no: '', issuing_authority: '', article_no: '', effective_date: '', expiry_date: '', timeliness: 'unknown', keywords: '', difficulty: 1, primary_chunk_id: '' })
const saving = ref(false)

function resetEditor() {
  Object.assign(editPayload, { id: null, kb_id: '', title: '', content: '', category: '', sub_category: '', doc_no: '', issuing_authority: '', article_no: '', effective_date: '', expiry_date: '', timeliness: 'unknown', keywords: '', difficulty: 1, primary_chunk_id: '' })
}
function openNew() { resetEditor(); editorTitle.value = '新增知识点'; editor.value = true }
function openEdit(row: any) {
  resetEditor()
  Object.assign(editPayload, {
    id: row.id, kb_id: row.kb_id, title: row.title, content: row.content,
    category: row.category, sub_category: row.sub_category, doc_no: row.doc_no,
    issuing_authority: row.issuing_authority, article_no: row.article_no,
    effective_date: row.effective_date, expiry_date: row.expiry_date,
    timeliness: row.timeliness || 'unknown', keywords: row.keywords, difficulty: row.difficulty,
    primary_chunk_id: row.primary_chunk_id,
  })
  editorTitle.value = '编辑知识点'
  editor.value = true
}
async function saveEdit() {
  if (!editPayload.title || editPayload.title.length < 5) { ElMessage.warning('标题至少5字'); return }
  if (!editPayload.content || editPayload.content.length < 10) { ElMessage.warning('内容至少10字'); return }
  saving.value = true
  try {
    const body: Record<string, any> = { ...editPayload, kb_id: editPayload.kb_id, difficulty: Number(editPayload.difficulty), primary_chunk_id: editPayload.primary_chunk_id ? Number(editPayload.primary_chunk_id) : undefined }
    if (body.effective_date === '') body.effective_date = null
    if (body.expiry_date === '') body.expiry_date = null
    if (editPayload.id) await kpApi.update(editPayload.id, body)
    else await kpApi.create(body)
    editor.value = false
    loadList(); loadStats()
  } catch (e: any) { ElMessage.error(e?.message || '保存失败') } finally { saving.value = false }
}
async function removeRow(row: any) {
  const ok = await ElMessageBox.confirm(`删除知识点「${row.title}」？`, '提示', { type: 'warning' }).then(() => true).catch(() => false)
  if (!ok) return
  try { await kpApi.remove(row.id); loadList(); loadStats() } catch (e: any) { ElMessage.error(e?.message || '删除失败') }
}

// 校验
const verifyDlg = ref(false)
const verifyRow = ref<any>(null)
const verifyForm = reactive<{ status: string; comment: string; confidence: number | null }>({ status: 'passed', comment: '', confidence: null })
function openVerify(row: any) { verifyRow.value = row; verifyForm.status = 'passed'; verifyForm.comment = ''; verifyForm.confidence = null; verifyDlg.value = true }
async function submitVerify() {
  try {
    await kpApi.verify(verifyRow.value.id, {
      verify_status: verifyForm.status,
      comment: verifyForm.comment || undefined,
      confidence: verifyForm.confidence !== null ? Number(verifyForm.confidence) : undefined,
    })
    verifyDlg.value = false
    loadList(); loadStats()
  } catch (e: any) { ElMessage.error(e?.message || '校验失败') }
}

// 关联
const relatedDlg = ref(false)
const relatedData = ref<any>(null)
async function openRelated(row: any) {
  try {
    relatedData.value = await kpApi.related(row.id)
    relatedDlg.value = true
  } catch (e: any) { ElMessage.error(e?.message || '加载关联失败') }
}

onMounted(() => { loadList(); loadStats(); kbStore.ensureLoaded() })
</script>

<template>
  <div class="doc-page">
    <!-- 统计卡 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-num">{{ stats?.total ?? '-' }}</div>
        <div class="stat-label">知识点总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ stats?.by_status?.published ?? '-' }}</div>
        <div class="stat-label">已发布</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{{ stats?.by_status?.draft ?? '-' }}</div>
        <div class="stat-label">草稿</div>
      </div>
      <div v-for="v in stats?.by_verify || []" :key="v.verify_status" class="stat-card">
        <div class="stat-num" :style="{ color: statColor(v) }">{{ v.count }}</div>
        <div class="stat-label">{{ VERIFY_MAP[v.verify_status]?.label ?? v.verify_status }}</div>
      </div>
    </div>

    <!-- 顶栏 -->
    <header class="doc-header" style="margin-bottom:12px">
      <div><h1>知识点库</h1><p>核心知识点 ≥ 1000 条，支持导入、校验、关联查询与导出</p></div>
      <div class="btn-group">
        <el-button :icon="Upload" @click="openImport">批量导入</el-button>
        <el-button :icon="Download" @click="kpApi.exportCsv(filters.kbId)">导出 CSV</el-button>
        <el-button type="primary" :icon="Plus" @click="openNew">新增知识点</el-button>
      </div>
    </header>

    <!-- 筛选 -->
    <div class="filter-bar" style="flex-wrap:wrap">
      <el-select v-model="filters.kbId" class="filter-item" style="width:150px" clearable placeholder="全部知识库" @change="doSearch">
        <el-option v-for="kb in kbStore.list" :key="kb.id" :value="kb.id" :label="kb.name" />
      </el-select>
      <el-select v-model="filters.category" class="filter-item" style="width:120px" clearable placeholder="全部分类" @change="doSearch">
        <el-option value="banking" label="银行监管" />
        <el-option value="securities" label="证券行业" />
        <el-option value="insurance" label="保险制度" />
      </el-select>
      <el-select v-model="filters.subCategory" class="filter-item" style="width:140px" clearable placeholder="全部子类" @change="doSearch">
        <el-option v-for="s in (SUB_CATS[filters.category] || [])" :key="s" :value="s" :label="s" />
      </el-select>
      <el-select v-model="filters.verifyStatus" class="filter-item" style="width:120px" clearable placeholder="全部校验" @change="doSearch">
        <el-option value="pending" label="待校验" />
        <el-option value="passed" label="已通过" />
        <el-option value="doubted" label="存疑" />
        <el-option value="rejected" label="已驳回" />
      </el-select>
      <el-select v-model="filters.status" class="filter-item" style="width:110px" clearable placeholder="全部状态" @change="doSearch">
        <el-option value="draft" label="草稿" />
        <el-option value="published" label="已发布" />
        <el-option value="archived" label="已归档" />
      </el-select>
      <el-select v-model="filters.difficulty" class="filter-item" style="width:100px" clearable placeholder="全部难度" @change="doSearch">
        <el-option value="1" label="易" />
        <el-option value="2" label="中" />
        <el-option value="3" label="难" />
      </el-select>
      <el-select v-model="filters.timeliness" class="filter-item" style="width:120px" clearable placeholder="全部时效" @change="doSearch">
        <el-option value="effective" label="现行有效" />
        <el-option value="amended" label="已修订" />
        <el-option value="repealed" label="已废止" />
        <el-option value="unknown" label="未知" />
      </el-select>
      <el-input v-model="filters.keyword" class="filter-item grow" style="flex:1; min-width:200px" clearable placeholder="按标题/关键词/文号搜索" @keyup.enter="doSearch" />
      <el-button :icon="Search" @click="doSearch">查询</el-button>
    </div>

    <!-- 列表 -->
    <el-table :data="list" v-loading="loading" stripe>
      <template #empty>
        <el-empty description="暂无知识点，点击右上角「新增」或「批量导入」" />
      </template>
      <el-table-column label="编号" width="120">
        <template #default="{ row }">
          <el-tag size="small">{{ row.code }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="标题" min-width="260">
        <template #default="{ row }">
          <div class="doc-title" :title="row.title">{{ row.title }}</div>
          <div class="doc-no" :title="row.content">{{ row.content?.slice(0, 40) }}…</div>
        </template>
      </el-table-column>
      <el-table-column label="分类" width="140">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ catLabel(row.category) }}</el-tag>
          <el-tag v-if="row.sub_category" size="small" type="info" style="margin-left:4px">{{ row.sub_category }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="时效" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="TIMELINESS[row.timeliness]?.type || 'info'">{{ TIMELINESS[row.timeliness]?.label || row.timeliness }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="难度" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="DIFF_MAP[row.difficulty]?.type || 'info'">{{ DIFF_MAP[row.difficulty]?.label || row.difficulty }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="校验" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="VERIFY_MAP[row.verify_status]?.type || 'info'">{{ VERIFY_MAP[row.verify_status]?.label || row.verify_status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="STATUS_MAP[row.status]?.type || 'info'">{{ STATUS_MAP[row.status]?.label || row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="270" fixed="right">
        <template #default="{ row }">
          <div class="ops">
            <el-button link type="primary" @click="router.push({ name: 'knowledge-point-detail', params: { id: row.id } })">详情</el-button>
            <el-button link type="primary" @click="openRelated(row)">关联</el-button>
            <el-button link type="primary" @click="openVerify(row)">校验</el-button>
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="removeRow(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination" style="margin-top:14px">
      <el-pagination
        background
        layout="total, prev, pager, next, sizes"
        :total="total"
        :page-sizes="[15, 30, 50, 100]"
        v-model:current-page="page"
        v-model:page-size="size"
        @current-change="goPage"
        @size-change="doSearch"
      />
    </div>

    <!-- ========== 编辑弹窗 ========== -->
    <el-dialog v-model="editor" :title="editorTitle" width="760px" top="4vh">
      <div class="form-grid">
        <div class="field"><label class="field-label">标题<span class="req">*</span></label><el-input v-model="editPayload.title" placeholder="5~300 字" /></div>
        <div class="field"><label class="field-label">知识库<span class="req">*</span></label>
          <el-select v-model="editPayload.kb_id" style="width:100%">
            <el-option v-for="kb in kbStore.list" :key="kb.id" :value="kb.id" :label="kb.name" />
          </el-select>
        </div>
        <div class="field"><label class="field-label">分类<span class="req">*</span></label>
          <el-select v-model="editPayload.category" style="width:100%">
            <el-option value="" label="选择分类" />
            <el-option value="banking" label="银行监管" />
            <el-option value="securities" label="证券行业" />
            <el-option value="insurance" label="保险制度" />
          </el-select>
        </div>
        <div class="field"><label class="field-label">子分类</label>
          <el-select v-model="editPayload.sub_category" style="width:100%">
            <el-option value="" label="自动" />
            <el-option v-for="s in (SUB_CATS[editPayload.category] || [])" :key="s" :value="s" :label="s" />
          </el-select>
        </div>
        <div class="field"><label class="field-label">文号</label><el-input v-model="editPayload.doc_no" /></div>
        <div class="field"><label class="field-label">发布机构</label><el-input v-model="editPayload.issuing_authority" /></div>
        <div class="field"><label class="field-label">条号</label><el-input v-model="editPayload.article_no" /></div>
        <div class="field"><label class="field-label">时效</label>
          <el-select v-model="editPayload.timeliness" style="width:100%">
            <el-option value="effective" label="现行有效" />
            <el-option value="amended" label="已修订" />
            <el-option value="repealed" label="已废止" />
            <el-option value="unknown" label="未知" />
          </el-select>
        </div>
        <div class="field"><label class="field-label">生效日期</label><el-input v-model="editPayload.effective_date" type="date" /></div>
        <div class="field"><label class="field-label">失效日期</label><el-input v-model="editPayload.expiry_date" type="date" /></div>
        <div class="field"><label class="field-label">难度</label>
          <el-select v-model="editPayload.difficulty" style="width:100%">
            <el-option :value="1" label="易" />
            <el-option :value="2" label="中" />
            <el-option :value="3" label="难" />
          </el-select>
        </div>
        <div class="field"><label class="field-label">来源 Chunk ID</label><el-input v-model="editPayload.primary_chunk_id" type="number" placeholder="选填" /></div>
      </div>
      <div class="field" style="margin-top:14px"><label class="field-label">内容<span class="req">*</span></label><el-input v-model="editPayload.content" type="textarea" :rows="4" placeholder="10~2000 字，人工可读的最小制度事实" /></div>
      <div class="field" style="margin-top:14px"><label class="field-label">关键词</label><el-input v-model="editPayload.keywords" placeholder="逗号分隔" /></div>
      <template #footer>
        <el-button @click="editor = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- ========== 校验弹窗 ========== -->
    <el-dialog v-model="verifyDlg" :title="`人工校验 · ${verifyRow?.title || ''}`" width="460px">
      <div class="field"><label class="field-label">校验结论<span class="req">*</span></label>
        <el-radio-group v-model="verifyForm.status">
          <el-radio-button value="passed">通过</el-radio-button>
          <el-radio-button value="doubted">存疑</el-radio-button>
          <el-radio-button value="rejected">驳回</el-radio-button>
        </el-radio-group>
      </div>
      <div class="field" style="margin-top:12px"><label class="field-label">置信度（选填，当前：{{ verifyForm.confidence ?? '—' }}）</label>
        <el-slider v-model="verifyForm.confidence" :min="0" :max="1" :step="0.01" show-input :show-input-controls="false" />
      </div>
      <div class="field" style="margin-top:12px"><label class="field-label">备注</label><el-input v-model="verifyForm.comment" type="textarea" :rows="3" placeholder="最多 500 字" /></div>
      <template #footer>
        <el-button @click="verifyDlg = false">取消</el-button>
        <el-button type="primary" @click="submitVerify">提交校验</el-button>
      </template>
    </el-dialog>

    <!-- ========== 关联弹窗 ========== -->
    <el-dialog v-model="relatedDlg" :title="`条文关联查询 · ${relatedData?.knowledge_point_id ?? ''}`" width="860px" top="5vh">
      <div v-if="!relatedData" class="empty-tip">加载中…</div>
      <div v-else>
        <div class="rel-section"><div class="rel-title">同制度上下文（context）</div>
          <div v-if="!relatedData.context?.length" class="empty-tip">无关联</div>
          <div v-for="c in relatedData.context || []" :key="c.id" class="cite-card">
            <div class="cite-top"><span class="cite-idx">#{{ c.chunk_index }}</span><span class="cite-article">{{ c.article_no }}</span><el-tag size="small" type="info">第 {{ c.page_start }} 页</el-tag></div>
            <div class="cite-snippet">{{ c.raw_content }}</div>
          </div>
        </div>
        <div class="rel-section"><div class="rel-title">同主题跨制度（same_topic）</div>
          <div v-if="!relatedData.same_topic?.length" class="empty-tip">无关联</div>
          <div v-for="c in relatedData.same_topic || []" :key="c.code" class="cite-card">
            <div class="cite-top"><el-tag size="small">{{ c.code }}</el-tag><span class="cite-doc">{{ c.title }}</span><el-tag size="small" type="info">{{ c.category }}</el-tag></div>
            <div class="cite-snippet">{{ c.content }}</div>
          </div>
        </div>
        <div class="rel-section"><div class="rel-title">修订替代关系（supersede）</div>
          <div v-if="!relatedData.supersede?.length" class="empty-tip">无关联</div>
          <div v-for="c in relatedData.supersede || []" :key="c.code" class="cite-card">
            <div class="cite-top"><el-tag size="small">{{ c.code }}</el-tag><span class="cite-doc">{{ c.title }}</span><el-tag size="small" :type="TIMELINESS[c.timeliness]?.type || 'info'">{{ TIMELINESS[c.timeliness]?.label || c.timeliness }}</el-tag></div>
            <div class="cite-snippet">{{ c.content }}</div>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- ========== 导入弹窗 ========== -->
    <el-dialog v-model="importVisible" title="批量导入知识点（Excel / CSV）" width="880px">
      <div class="field"><label class="field-label">文件<span class="req">*</span></label>
        <el-upload
          :auto-upload="false"
          :limit="1"
          accept=".xlsx,.xls,.csv"
          :on-change="onImportFile"
          :on-remove="() => (importForm.file = null)"
        >
          <el-button type="primary" plain>选择文件</el-button>
          <template #tip><div class="el-upload__tip">支持 .xlsx / .xls / .csv</div></template>
        </el-upload>
      </div>
      <div class="field" style="margin-top:12px"><label class="field-label">目标知识库<span class="req">*</span></label>
        <el-select v-model="importForm.kb_id" style="width:100%">
          <el-option v-for="kb in kbStore.list" :key="kb.id" :value="kb.id" :label="kb.name" />
        </el-select>
      </div>
      <div style="margin-top:12px"><el-checkbox v-model="importForm.dryRun">仅预校验（dry_run）</el-checkbox></div>
      <div v-if="importResult" class="import-res">
        <div>总行数：{{ importResult.total_rows }} / 有效：{{ importResult.valid_rows }}</div>
        <div v-if="importResult.errors?.length" class="error-text">错误 {{ importResult.errors.length }} 条：</div>
        <el-table v-if="importResult.errors?.length" :data="importResult.errors.slice(0, 10)" size="small" style="margin-top:6px">
          <el-table-column prop="row" label="行号" width="80" />
          <el-table-column prop="message" label="错误原因" />
        </el-table>
        <div v-if="importResult.preview?.length">预览前 {{ Math.min(importResult.preview.length,5) }} 条：<div v-for="p in importResult.preview.slice(0,5)" :key="p.row">第{{ p.row }}行 → {{ p.action === 'create' ? '新建' : '更新' }}「{{ p.title }}」</div></div>
        <div v-if="importResult.created != null">新建 {{ importResult.created }} / 更新 {{ importResult.updated }} / 跳过 {{ importResult.skipped }}</div>
      </div>
      <template #footer>
        <el-button @click="importVisible = false">关闭</el-button>
        <el-button type="primary" :loading="importing" @click="submitImport">{{ importing ? '处理中…' : '开始导入' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.stats-row { display:grid; grid-template-columns:repeat(auto-fit, minmax(130px,1fr)); gap:12px; margin-bottom:16px; }
.stat-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:16px; text-align:center; }
.stat-num { font-size:28px; font-weight:700; color:var(--text-1); }
.stat-label { font-size:12px; color:var(--text-3); margin-top:4px; }
.btn-group { display:flex; gap:8px; }
.import-res { margin-top:12px; padding:10px; background:var(--surface-2); border-radius:var(--radius-sm); font-size:13px; }
.rel-section { margin-bottom:14px; }
.rel-title { font-weight:600; font-size:13px; margin-bottom:8px; color:var(--text-2); }
.doc-page .cite-card { margin-bottom:6px; }
</style>
