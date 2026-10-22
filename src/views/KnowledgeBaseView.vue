<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { kbApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { useKbStore } from '../stores/kb'
import type { KbInfo } from '../types'

const auth = useAuthStore()
const kbStore = useKbStore()

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

onMounted(load)
</script>

<template>
  <section class="doc-page">
    <div class="doc-header">
      <div>
        <h1>知识库管理</h1>
        <p>知识点分布与知识点 ≥ 1000 验收指标的数据来源</p>
      </div>
      <div class="page-toolbar" style="margin: 0">
        <el-button v-if="auth.isAdmin" type="primary" @click="openCreate">新建知识库</el-button>
      </div>
    </div>

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

    <!-- 新建 / 编辑弹窗 -->
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
