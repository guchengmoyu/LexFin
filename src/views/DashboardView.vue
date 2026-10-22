<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { statsApi } from '../api'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const data = ref<any>(null)

const CATEGORY_LABEL: Record<string, string> = { banking: '银行监管', securities: '证券行业', insurance: '保险制度' }
const STATUS_MAP: Record<string, { label: string; type: 'info' | 'primary' | 'success' | 'danger' }> = {
  pending: { label: '待解析', type: 'info' },
  parsing: { label: '解析中', type: 'primary' },
  embedding: { label: '向量化中', type: 'primary' },
  ready: { label: '就绪', type: 'success' },
  error: { label: '失败', type: 'danger' },
  archived: { label: '已归档', type: 'info' },
}

const maxCategory = computed(() => {
  const rows: any[] = data.value?.category_distribution || []
  return Math.max(1, ...rows.map((r: any) => Math.max(Number(r.docs) || 0, Number(r.kps) || 0)))
})

function pct(v: any): string {
  return v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await statsApi.overview()
  } catch (e: any) {
    error.value = e.message || '统计加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="doc-page">
    <div class="doc-header">
      <div>
        <h1>数据概览</h1>
        <p>知识库、文档、知识点与问答运行指标</p>
      </div>
      <el-button :icon="Refresh" plain @click="load">刷新</el-button>
    </div>

    <div v-if="loading" class="empty-state">加载中…</div>
    <div v-else-if="error" class="empty-state error-text">{{ error }}</div>

    <template v-else-if="data">
      <div class="metric-grid">
        <div class="metric-card"><div class="metric-num">{{ data.kb_count }}</div><div class="metric-label">知识库</div></div>
        <div class="metric-card"><div class="metric-num">{{ data.document_count }}</div><div class="metric-label">文档</div></div>
        <div class="metric-card"><div class="metric-num">{{ data.chunk_count }}</div><div class="metric-label">切片</div></div>
        <div class="metric-card highlight"><div class="metric-num">{{ data.knowledge_point_count }}</div><div class="metric-label">知识点总数</div></div>
        <div class="metric-card"><div class="metric-num">{{ data.published_kp_count }}</div><div class="metric-label">已发布知识点</div></div>
        <div class="metric-card"><div class="metric-num">{{ data.verified_kp_count }}</div><div class="metric-label">已校验通过</div></div>
        <div class="metric-card"><div class="metric-num">{{ pct(data.verify_pass_rate) }}</div><div class="metric-label">校验通过率</div></div>
        <div class="metric-card"><div class="metric-num">{{ data.qa_total }}</div><div class="metric-label">问答总数（今日 {{ data.qa_today }}）</div></div>
        <div class="metric-card"><div class="metric-num">{{ data.avg_latency_ms == null ? '—' : `${data.avg_latency_ms}ms` }}</div><div class="metric-label">平均时延</div></div>
        <div class="metric-card"><div class="metric-num">{{ data.avg_confidence == null ? '—' : data.avg_confidence.toFixed(2) }}</div><div class="metric-label">平均可信度</div></div>
      </div>

      <div class="split-layout">
        <div class="panel">
          <h3 class="panel-title">分类分布</h3>
          <el-empty v-if="!data.category_distribution?.length" description="暂无数据" :image-size="60" />
          <div v-for="c in data.category_distribution" :key="c.category" class="category-row">
            <div class="category-head">
              <span class="bar-label">{{ CATEGORY_LABEL[c.category] || c.category }}</span>
              <span class="doc-no">文档 {{ c.docs }} · 知识点 {{ c.kps }}</span>
            </div>
            <div class="bar-row">
              <span class="bar-label" style="width: 46px">文档</span>
              <span class="bar-track"><span class="bar-fill" :style="{ width: `${(c.docs / maxCategory) * 100}%` }"></span></span>
              <span>{{ c.docs }}</span>
            </div>
            <div class="bar-row">
              <span class="bar-label" style="width: 46px">知识点</span>
              <span class="bar-track">
                <span class="bar-fill alt" :style="{ width: `${(c.kps / maxCategory) * 100}%` }"></span>
              </span>
              <span>{{ c.kps }}</span>
            </div>
          </div>
        </div>

        <div class="panel">
          <h3 class="panel-title">最近入库</h3>
          <el-empty v-if="!data.recent_documents?.length" description="暂无文档" :image-size="60" />
          <div v-for="d in data.recent_documents" :key="d.id" class="recent-item">
            <div class="recent-main">
              <div class="recent-title">{{ d.title }}</div>
              <div class="recent-meta">
                <el-tag size="small" :type="STATUS_MAP[d.status]?.type || 'info'">{{ STATUS_MAP[d.status]?.label || d.status }}</el-tag>
                <span>{{ d.created_at || '—' }}</span>
              </div>
            </div>
            <el-button size="small" plain @click="router.push({ name: 'document-detail', params: { id: d.id } })">详情</el-button>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.category-row {
  margin-bottom: 14px;
}

.category-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.bar-fill.alt {
  background: linear-gradient(90deg, #7c5cff, #b39dff);
}

.recent-item {
  display: flex;
  align-items: center;
  gap: 10px;
  border-bottom: 1px dashed var(--border);
  padding: 10px 0;
}

.recent-item:last-child {
  border-bottom: none;
}

.recent-main {
  flex: 1;
  min-width: 0;
}

.recent-title {
  font-size: 13px;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 5px;
  font-size: 11.5px;
  color: var(--text-3);
}
</style>
