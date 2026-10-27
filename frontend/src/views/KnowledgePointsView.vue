<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { kpApi } from '../api'
import { useKbStore } from '../stores/kb'

const kbStore = useKbStore()

const list = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(15)
const loading = ref(false)
const filters = reactive({ kbId: '', category: '', subCategory: '', verifyStatus: '', status: '', timeliness: '', difficulty: '', keyword: '' })
const stats = ref(null)

const VERIFY_MAP = {
  pending: { label: '待校验', cls: 'gray' },
  passed: { label: '已通过', cls: 'green' },
  doubted: { label: '存疑', cls: 'yellow' },
  rejected: { label: '已驳回', cls: 'red' },
}
const STATUS_MAP = {
  draft: { label: '草稿', cls: 'gray' },
  published: { label: '已发布', cls: 'blue' },
  archived: { label: '已归档', cls: 'gray' },
}
const DIFF_MAP = { 1: { label: '易', cls: 'green' }, 2: { label: '中', cls: 'yellow' }, 3: { label: '难', cls: 'red' } }
const TIMELINESS = {
  effective: { label: '现行有效', cls: 'green' },
  amended: { label: '已修订', cls: 'yellow' },
  repealed: { label: '已废止', cls: 'red' },
  unknown: { label: '未知', cls: 'gray' },
}

const SUB_CATS = {
  banking: ['资本管理','流动性风险','信用风险','市场风险','操作风险','公司治理','信息披露','支付结算','反洗钱','消费者权益保护','账户管理','信贷业务'],
  securities: ['发行上市','信息披露','交易规则','投资者适当性','证券公司治理','资产管理','债券业务','融资融券','投资顾问','基金销售'],
  insurance: ['产品条款','销售规范','偿付能力','资金运用','理赔服务','客户权益','合规经营','保险营销','再保险','精算'],
}

const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

async function loadList() {
  loading.value = true
  try {
    const data = await kpApi.list({
      kb_id: filters.kbId, category: filters.category, sub_category: filters.subCategory,
      verify_status: filters.verifyStatus, status: filters.status, timeliness: filters.timeliness,
      difficulty: filters.difficulty, keyword: filters.keyword,
      page: page.value, size: size.value,
    })
    list.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    alert(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}
async function loadStats() {
  try { stats.value = await kpApi.stats() } catch {/*ignore*/}
}
function doSearch() { page.value = 1; loadList() }
function goPage(p) { page.value = Math.min(Math.max(1, p), pages.value); loadList() }

// 导入
const importVisible = ref(false)
const importForm = reactive({ file: null, kb_id: '', dryRun: true })
const importResult = ref(null)
const importing = ref(false)
function openImport() {
  importForm.kb_id = kbStore.list[0]?.id ?? ''; importForm.file = null; importForm.dryRun = true
  importResult.value = null; importVisible.value = true
}
function onImportFile(e) { importForm.file = (e.target.files || [])[0] }
async function submitImport() {
  if (!importForm.file) return alert('请选择文件')
  if (!importForm.kb_id) return alert('请选择知识库')
  importing.value = true
  try {
    const fd = new FormData()
    fd.append('file', importForm.file)
    fd.append('kb_id', String(importForm.kb_id))
    fd.append('dry_run', importForm.dryRun ? 'true' : 'false')
    const res = await kpApi.importFile(fd)
    importResult.value = res
    if (!importForm.dryRun) { loadList(); loadStats() }
  } catch (e) { alert(e.message || '导入失败') } finally { importing.value = false }
}

// 编辑
const editor = ref(null)
const editorTitle = ref('')
const editPayload = reactive({ id: null, kb_id: '', title: '', content: '', category: '', sub_category: '', doc_no: '', issuing_authority: '', article_no: '', effective_date: '', expiry_date: '', timeliness: 'unknown', keywords: '', difficulty: 1, primary_chunk_id: '' })
const saving = ref(false)

function resetEditor() {
  Object.assign(editPayload, { id: null, kb_id: '', title: '', content: '', category: '', sub_category: '', doc_no: '', issuing_authority: '', article_no: '', effective_date: '', expiry_date: '', timeliness: 'unknown', keywords: '', difficulty: 1, primary_chunk_id: '' })
}
function openNew() { resetEditor(); editorTitle.value = '新增知识点'; editor.value = true }
function openEdit(row) {
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
  if (!editPayload.title || editPayload.title.length < 5) return alert('标题至少5字')
  if (!editPayload.content || editPayload.content.length < 10) return alert('内容至少10字')
  saving.value = true
  try {
    const body = { ...editPayload, kb_id: editPayload.kb_id, difficulty: Number(editPayload.difficulty), primary_chunk_id: editPayload.primary_chunk_id ? Number(editPayload.primary_chunk_id) : undefined }
    if (body.effective_date === '') body.effective_date = null
    if (body.expiry_date === '') body.expiry_date = null
    if (editPayload.id) await kpApi.update(editPayload.id, body)
    else await kpApi.create(body)
    editor.value = false
    loadList(); loadStats()
  } catch (e) { alert(e.message || '保存失败') } finally { saving.value = false }
}
async function removeRow(row) {
  if (!confirm(`删除知识点「${row.title}」？`)) return
  try { await kpApi.remove(row.id); loadList(); loadStats() } catch (e) { alert(e.message || '删除失败') }
}

// 校验
const verifyDlg = ref(false)
const verifyRow = ref(null)
const verifyForm = reactive({ status: 'passed', comment: '', confidence: '' })
function openVerify(row) { verifyRow.value = row; verifyForm.status = 'passed'; verifyForm.comment = ''; verifyForm.confidence = ''; verifyDlg.value = true }
async function submitVerify() {
  try {
    await kpApi.verify(verifyRow.value.id, {
      verify_status: verifyForm.status,
      comment: verifyForm.comment || undefined,
      confidence: verifyForm.confidence !== '' ? Number(verifyForm.confidence) : undefined,
    })
    verifyDlg.value = false
    loadList(); loadStats()
  } catch (e) { alert(e.message || '校验失败') }
}

// 关联
const relatedDlg = ref(false)
const relatedData = ref(null)
async function openRelated(row) {
  try {
    relatedData.value = await kpApi.related(row.id)
    relatedDlg.value = true
  } catch (e) { alert(e.message || '加载关联失败') }
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
        <div class="stat-num" :style="{color: VERIFY_MAP[v.verify_status]?.cls === 'green' ? 'var(--success)' : VERIFY_MAP[v.verify_status]?.cls === 'red' ? 'var(--danger)' : 'var(--text-2)'}">{{ v.count }}</div>
        <div class="stat-label">{{ VERIFY_MAP[v.verify_status]?.label ?? v.verify_status }}</div>
      </div>
    </div>

    <!-- 顶栏 -->
    <header class="doc-header" style="margin-bottom:12px">
      <div><h1>知识点库</h1><p>核心知识点 ≥ 1000 条，支持导入、校验、关联查询与导出</p></div>
      <div class="btn-group">
        <button class="btn outline" @click="openImport">📤 批量导入</button>
        <button class="btn outline" @click="kpApi.exportCsv(filters.kbId)">📥 导出 CSV</button>
        <button class="btn" @click="openNew">＋ 新增知识点</button>
      </div>
    </header>

    <!-- 筛选 -->
    <div class="filter-bar" style="flex-wrap:wrap">
      <select v-model="filters.kbId" class="select filter-item" @change="doSearch"><option value="">全部知识库</option><option v-for="kb in kbStore.list" :key="kb.id" :value="kb.id">{{ kb.name }}</option></select>
      <select v-model="filters.category" class="select filter-item" @change="doSearch"><option value="">全部分类</option><option value="banking">银行监管</option><option value="securities">证券行业</option><option value="insurance">保险制度</option></select>
      <select v-model="filters.subCategory" class="select filter-item" @change="doSearch"><option value="">全部子类</option><option v-for="s in (SUB_CATS[filters.category] || [])" :key="s" :value="s">{{ s }}</option></select>
      <select v-model="filters.verifyStatus" class="select filter-item" @change="doSearch"><option value="">全部校验</option><option value="pending">待校验</option><option value="passed">已通过</option><option value="doubted">存疑</option><option value="rejected">已驳回</option></select>
      <select v-model="filters.status" class="select filter-item" @change="doSearch"><option value="">全部状态</option><option value="draft">草稿</option><option value="published">已发布</option><option value="archived">已归档</option></select>
      <select v-model="filters.difficulty" class="select filter-item" @change="doSearch"><option value="">全部难度</option><option value="1">易</option><option value="2">中</option><option value="3">难</option></select>
      <select v-model="filters.timeliness" class="select filter-item" @change="doSearch"><option value="">全部时效</option><option value="effective">现行有效</option><option value="amended">已修订</option><option value="repealed">已废止</option><option value="unknown">未知</option></select>
      <input v-model="filters.keyword" class="input filter-item grow" placeholder="按标题/关键词/文号搜索" @keyup.enter="doSearch" />
      <button class="btn outline" @click="doSearch">查询</button>
    </div>

    <!-- 列表 -->
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr>
          <th>编号</th><th>标题</th><th>分类</th><th>时效</th><th>难度</th><th>校验</th><th>状态</th><th>操作</th>
        </tr></thead>
        <tbody>
          <tr v-if="loading"><td colspan="8" class="empty-tip">加载中…</td></tr>
          <tr v-else-if="!list.length"><td colspan="8" class="empty-tip">暂无知识点，点击右上角「新增」或「批量导入」</td></tr>
          <tr v-for="row in list" :key="row.id">
            <td><span class="tag blue">{{ row.code }}</span></td>
            <td>
              <div class="doc-title" :title="row.title">{{ row.title }}</div>
              <div class="doc-no" :title="row.content">{{ row.content?.slice(0, 40) }}…</div>
            </td>
            <td>
              <span class="tag gray">{{ row.category === 'banking' ? '银行' : row.category === 'securities' ? '证券' : row.category === 'insurance' ? '保险' : row.category }}</span>
              <span v-if="row.sub_category" class="tag gray">{{ row.sub_category }}</span>
            </td>
            <td><span class="tag" :class="TIMELINESS[row.timeliness]?.cls || 'gray'">{{ TIMELINESS[row.timeliness]?.label || row.timeliness }}</span></td>
            <td><span class="tag" :class="DIFF_MAP[row.difficulty]?.cls || 'gray'">{{ DIFF_MAP[row.difficulty]?.label || row.difficulty }}</span></td>
            <td><span class="tag" :class="VERIFY_MAP[row.verify_status]?.cls || 'gray'">{{ VERIFY_MAP[row.verify_status]?.label || row.verify_status }}</span></td>
            <td><span class="tag" :class="STATUS_MAP[row.status]?.cls || 'gray'">{{ STATUS_MAP[row.status]?.label || row.status }}</span></td>
            <td>
              <div class="ops">
                <button class="btn-ghost op" @click="openRelated(row)">关联</button>
                <button class="btn-ghost op" @click="openVerify(row)">校验</button>
                <button class="btn-ghost op" @click="openEdit(row)">编辑</button>
                <button class="btn-ghost op danger" @click="removeRow(row)">删除</button>
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
      <button v-for="p in pages" :key="p" class="page-btn" :class="{ active: p === page }" @click="goPage(p)">{{ p }}</button>
      <button class="page-btn" :disabled="page >= pages" @click="goPage(page + 1)">›</button>
    </div>

    <!-- ========== 编辑弹窗 ========== -->
    <div v-if="editor" class="modal-mask" @click.self="editor = false">
      <div class="modal" style="max-height:92vh">
        <div class="modal-head"><div class="modal-title">{{ editorTitle }}</div><button class="modal-close" @click="editor = false">×</button></div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="field"><label class="field-label">标题<span class="req">*</span></label><input v-model="editPayload.title" class="input" placeholder="5~300 字" /></div>
            <div class="field"><label class="field-label">知识库<span class="req">*</span></label><select v-model="editPayload.kb_id" class="select"><option v-for="kb in kbStore.list" :key="kb.id" :value="kb.id">{{ kb.name }}</option></select></div>
            <div class="field"><label class="field-label">分类<span class="req">*</span></label>
              <select v-model="editPayload.category" class="select">
                <option value="">选择分类</option><option value="banking">银行监管</option><option value="securities">证券行业</option><option value="insurance">保险制度</option>
              </select>
            </div>
            <div class="field"><label class="field-label">子分类</label>
              <select v-model="editPayload.sub_category" class="select">
                <option value="">自动</option><option v-for="s in (SUB_CATS[editPayload.category] || [])" :key="s" :value="s">{{ s }}</option>
              </select>
            </div>
            <div class="field"><label class="field-label">文号</label><input v-model="editPayload.doc_no" class="input" /></div>
            <div class="field"><label class="field-label">发布机构</label><input v-model="editPayload.issuing_authority" class="input" /></div>
            <div class="field"><label class="field-label">条号</label><input v-model="editPayload.article_no" class="input" /></div>
            <div class="field"><label class="field-label">时效</label>
              <select v-model="editPayload.timeliness" class="select"><option value="effective">现行有效</option><option value="amended">已修订</option><option value="repealed">已废止</option><option value="unknown">未知</option></select>
            </div>
            <div class="field"><label class="field-label">生效日期</label><input v-model="editPayload.effective_date" type="date" class="input" /></div>
            <div class="field"><label class="field-label">失效日期</label><input v-model="editPayload.expiry_date" type="date" class="input" /></div>
            <div class="field"><label class="field-label">难度</label>
              <select v-model.number="editPayload.difficulty" class="select"><option :value="1">易</option><option :value="2">中</option><option :value="3">难</option></select>
            </div>
            <div class="field"><label class="field-label">来源 Chunk ID</label><input v-model="editPayload.primary_chunk_id" type="number" class="input" placeholder="选填" /></div>
          </div>
          <div class="field" style="margin-top:14px"><label class="field-label">内容<span class="req">*</span></label><textarea v-model="editPayload.content" class="textarea" rows="4" placeholder="10~2000 字，人工可读的最小制度事实" /></div>
          <div class="field" style="margin-top:14px"><label class="field-label">关键词</label><input v-model="editPayload.keywords" class="input" placeholder="逗号分隔" /></div>
        </div>
        <div class="modal-foot">
          <button class="btn outline" @click="editor = false">取消</button>
          <button class="btn" :disabled="saving" @click="saveEdit"><span v-if="saving" class="spin" />保存</button>
        </div>
      </div>
    </div>

    <!-- ========== 校验弹窗 ========== -->
    <div v-if="verifyDlg" class="modal-mask" @click.self="verifyDlg = false">
      <div class="modal" style="width:420px">
        <div class="modal-head"><div class="modal-title">人工校验 · {{ verifyRow?.title }}</div><button class="modal-close" @click="verifyDlg = false">×</button></div>
        <div class="modal-body">
          <div class="field"><label class="field-label">校验结论<span class="req">*</span></label>
            <select v-model="verifyForm.status" class="select">
              <option value="passed">✅ 通过</option><option value="doubted">⚠ 存疑</option><option value="rejected">❌ 驳回</option>
            </select>
          </div>
          <div class="field" style="margin-top:12px"><label class="field-label">置信度 (0~1)</label><input v-model="verifyForm.confidence" class="input" type="number" min="0" max="1" step="0.01" placeholder="选填" /></div>
          <div class="field" style="margin-top:12px"><label class="field-label">备注</label><textarea v-model="verifyForm.comment" class="textarea" rows="3" placeholder="最多 500 字" /></div>
        </div>
        <div class="modal-foot">
          <button class="btn outline" @click="verifyDlg = false">取消</button>
          <button class="btn" @click="submitVerify">提交校验</button>
        </div>
      </div>
    </div>

    <!-- ========== 关联弹窗 ========== -->
    <div v-if="relatedDlg" class="modal-mask" @click.self="relatedDlg = false">
      <div class="modal wide">
        <div class="modal-head"><div class="modal-title">条文关联查询 · {{ relatedData?.knowledge_point_id }}</div><button class="modal-close" @click="relatedDlg = false">×</button></div>
        <div class="modal-body">
          <div v-if="!relatedData" class="empty-tip">加载中…</div>
          <div v-else>
            <div class="rel-section"><div class="rel-title">同制度上下文（context）</div>
              <div v-if="!relatedData.context?.length" class="empty-tip">无关联</div>
              <div v-for="c in relatedData.context || []" :key="c.id" class="cite-card">
                <div class="cite-top"><span class="cite-idx">#{{ c.chunk_index }}</span><span class="cite-article">{{ c.article_no }}</span><span class="tag gray">第 {{ c.page_start }} 页</span></div>
                <div class="cite-snippet">{{ c.raw_content }}</div>
              </div>
            </div>
            <div class="rel-section"><div class="rel-title">同主题跨制度（same_topic）</div>
              <div v-if="!relatedData.same_topic?.length" class="empty-tip">无关联</div>
              <div v-for="c in relatedData.same_topic || []" :key="c.code" class="cite-card">
                <div class="cite-top"><span class="tag blue">{{ c.code }}</span><span class="cite-doc">{{ c.title }}</span><span class="tag gray">{{ c.category }}</span></div>
                <div class="cite-snippet">{{ c.content }}</div>
              </div>
            </div>
            <div class="rel-section"><div class="rel-title">修订替代关系（supersede）</div>
              <div v-if="!relatedData.supersede?.length" class="empty-tip">无关联</div>
              <div v-for="c in relatedData.supersede || []" :key="c.code" class="cite-card">
                <div class="cite-top"><span class="tag blue">{{ c.code }}</span><span class="cite-doc">{{ c.title }}</span><span class="tag" :class="TIMELINESS[c.timeliness]?.cls || 'gray'">{{ TIMELINESS[c.timeliness]?.label || c.timeliness }}</span></div>
                <div class="cite-snippet">{{ c.content }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 导入弹窗 ========== -->
    <div v-if="importVisible" class="modal-mask" @click.self="importVisible = false">
      <div class="modal">
        <div class="modal-head"><div class="modal-title">批量导入知识点（Excel / CSV）</div><button class="modal-close" @click="importVisible = false">×</button></div>
        <div class="modal-body">
          <div class="field"><label class="field-label">文件<span class="req">*</span></label><input type="file" accept=".xlsx,.xls,.csv" @change="onImportFile" /></div>
          <div class="field" style="margin-top:12px"><label class="field-label">目标知识库<span class="req">*</span></label><select v-model="importForm.kb_id" class="select"><option v-for="kb in kbStore.list" :key="kb.id" :value="kb.id">{{ kb.name }}</option></select></div>
          <div class="field" style="margin-top:12px"><label class="field-label"><input v-model="importForm.dryRun" type="checkbox" /> 仅预校验（dry_run）</label></div>
          <div v-if="importResult" class="import-res">
            <div>总行数：{{ importResult.total_rows }} / 有效：{{ importResult.valid_rows }}</div>
            <div v-if="importResult.errors?.length" class="error-text">错误 {{ importResult.errors.length }} 条：<div v-for="e in importResult.errors.slice(0,10)" :key="e.row">第{{ e.row }}行 {{ e.message }}</div></div>
            <div v-if="importResult.preview?.length">预览前 {{ Math.min(importResult.preview.length,5) }} 条：<div v-for="p in importResult.preview.slice(0,5)" :key="p.row">第{{ p.row }}行 → {{ p.action === 'create' ? '新建' : '更新' }}「{{ p.title }}」</div></div>
            <div v-if="importResult.created != null">新建 {{ importResult.created }} / 更新 {{ importResult.updated }} / 跳过 {{ importResult.skipped }}</div>
          </div>
        </div>
        <div class="modal-foot">
          <button class="btn outline" @click="importVisible = false">关闭</button>
          <button class="btn" :disabled="importing" @click="submitImport"><span v-if="importing" class="spin" />{{ importing ? '处理中…' : '开始导入' }}</button>
        </div>
      </div>
    </div>
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
