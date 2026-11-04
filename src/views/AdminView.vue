<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { systemApi, statsApi } from '../api'

/**
 * 管理员界面（仅 admin）：系统健康、全局统计、运行配置与管理入口。
 */
const router = useRouter()

const health = ref<any>(null)
const healthError = ref('')
const overview = ref<any>(null)
const config = ref<any>(null)

const DEP_LABEL: Record<string, string> = {
  mysql: 'MySQL',
  milvus: 'Milvus 向量库',
  llm: '大模型',
  ocr: 'OCR 引擎',
  embedding: 'Embedding 模型',
}

const SHORTCUTS = [
  { name: 'knowledge-base', label: '知识库管理', desc: '知识库统计与入库任务', icon: '📚' },
  { name: 'documents', label: '文档管理', desc: '制度文档上传与解析', icon: '📄' },
  { name: 'feedback', label: '反馈处理', desc: '用户反馈定位答案问题', icon: '🗣' },
  { name: 'evaluation', label: '测评', desc: '检索 hit@k 与准确率', icon: '📈' },
  { name: 'dashboard', label: '数据概览', desc: '核心指标看板', icon: '📊' },
]

function uptimeText(sec?: number): string {
  if (!sec && sec !== 0) return '—'
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return h ? `${h} 小时 ${m} 分` : `${m} 分`
}

onMounted(async () => {
  try {
    health.value = await systemApi.health()
  } catch (e: any) {
    healthError.value = e?.message || '健康检查失败'
  }
  try {
    overview.value = await statsApi.overview()
  } catch {
    /* 忽略单项失败 */
  }
  try {
    config.value = await systemApi.config()
  } catch {
    /* 忽略单项失败 */
  }
})
</script>

<template>
  <section class="doc-page">
    <div class="doc-header">
      <div>
        <h1>管理员界面</h1>
        <p>系统运行状态、全局指标与管理入口（仅管理员可见）</p>
      </div>
    </div>

    <!-- 系统健康 -->
    <div class="panel">
      <h3 class="panel-title">
        <span>系统健康</span>
        <el-tag v-if="health" :type="health.status === 'ok' ? 'success' : 'warning'">
          {{ health.status === 'ok' ? '运行正常' : '部分异常' }}
        </el-tag>
      </h3>
      <el-alert v-if="healthError" :title="healthError" type="error" :closable="false" show-icon />
      <template v-else-if="health">
        <div class="health-meta">
          <span>版本 {{ health.version || '—' }}</span>
          <span>已运行 {{ uptimeText(health.uptime_seconds) }}</span>
        </div>
        <div class="dep-grid">
          <div
            v-for="(dep, key) in health.dependencies || {}"
            :key="key"
            class="dep-card"
            :class="(dep as any).status === 'ok' ? 'ok' : 'err'"
          >
            <div class="dep-name">{{ DEP_LABEL[key as string] || key }}</div>
            <div class="dep-status">
              {{ (dep as any).status === 'ok' ? '✅ 正常' : '❌ 异常' }}
              <span v-if="(dep as any).latency_ms != null" class="dep-extra">{{ (dep as any).latency_ms }}ms</span>
            </div>
            <div class="dep-extra">
              <span v-if="(dep as any).model">模型 {{ (dep as any).model }}</span>
              <span v-else-if="(dep as any).entities != null">向量 {{ (dep as any).entities }} 条</span>
              <span v-else-if="(dep as any).langs">语言 {{ ((dep as any).langs || []).join(' / ') }}</span>
              <span v-else-if="(dep as any).message">{{ (dep as any).message }}</span>
            </div>
          </div>
        </div>
      </template>
      <div v-else class="empty-state">加载中…</div>
    </div>

    <!-- 全局统计 -->
    <div class="panel" style="margin-top: 16px">
      <h3 class="panel-title">全局统计</h3>
      <div v-if="!overview" class="empty-state">加载中…</div>
      <div v-else class="metric-grid">
        <div class="metric-card"><div class="metric-num">{{ overview.kb_count }}</div><div class="metric-label">知识库</div></div>
        <div class="metric-card"><div class="metric-num">{{ overview.document_count }}</div><div class="metric-label">文档（目标 ≥ 200）</div></div>
        <div class="metric-card"><div class="metric-num">{{ overview.chunk_count }}</div><div class="metric-label">切片</div></div>
        <div class="metric-card highlight"><div class="metric-num">{{ overview.knowledge_point_count }}</div><div class="metric-label">知识点（目标 ≥ 1000）</div></div>
        <div class="metric-card"><div class="metric-num">{{ overview.verified_kp_count }}</div><div class="metric-label">已校验知识点</div></div>
        <div class="metric-card">
          <div class="metric-num">{{ overview.verify_pass_rate == null ? '—' : `${(overview.verify_pass_rate * 100).toFixed(1)}%` }}</div>
          <div class="metric-label">校验通过率</div>
        </div>
        <div class="metric-card"><div class="metric-num">{{ overview.qa_total }}</div><div class="metric-label">累计问答（今日 {{ overview.qa_today ?? 0 }}）</div></div>
        <div class="metric-card">
          <div class="metric-num">{{ overview.avg_latency_ms == null ? '—' : `${(overview.avg_latency_ms / 1000).toFixed(1)}s` }}</div>
          <div class="metric-label">平均问答耗时</div>
        </div>
      </div>
    </div>

    <!-- 运行配置 -->
    <div class="panel" style="margin-top: 16px">
      <h3 class="panel-title">运行配置</h3>
      <div v-if="!config" class="empty-state">加载中…</div>
      <div v-else class="kv-list">
        <span class="kv-key">允许上传格式</span>
        <span class="kv-val">{{ (config.allowed_extensions || []).join('、') || '—' }}</span>
        <span class="kv-key">单文件上限</span>
        <span class="kv-val">{{ config.max_file_size_mb ?? '—' }} MB</span>
        <span class="kv-key">特性开关</span>
        <span class="kv-val">
          <el-tag
            v-for="(v, k) in config.features || {}"
            :key="k"
            size="small"
            :type="v ? 'success' : 'info'"
            style="margin-right: 6px"
          >{{ k }} {{ v ? '开' : '关' }}</el-tag>
        </span>
        <span class="kv-key">知识库分类</span>
        <span class="kv-val">{{ (config.categories || []).map((c: any) => c.label).join('、') || '—' }}</span>
      </div>
    </div>

    <!-- 管理入口 -->
    <h3 class="panel-title" style="margin: 18px 0 10px">管理入口</h3>
    <div class="shortcut-grid">
      <div v-for="s in SHORTCUTS" :key="s.name" class="panel shortcut-card" @click="router.push({ name: s.name })">
        <div class="shortcut-icon">{{ s.icon }}</div>
        <div>
          <div class="shortcut-label">{{ s.label }}</div>
          <div class="shortcut-desc">{{ s.desc }}</div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.health-meta {
  display: flex;
  gap: 20px;
  margin-bottom: 12px;
  font-size: 12.5px;
  color: var(--text-3);
}

.dep-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}

.dep-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px;
}

.dep-card.ok {
  border-left: 3px solid #21a366;
}

.dep-card.err {
  border-left: 3px solid #e5484d;
}

.dep-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
}

.dep-status {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--text-2);
}

.dep-extra {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--text-3);
}

.shortcut-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.shortcut-card {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.shortcut-card:hover {
  border-color: var(--primary);
  box-shadow: 0 2px 10px rgba(79, 124, 255, 0.12);
}

.shortcut-icon {
  font-size: 22px;
}

.shortcut-label {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-1);
}

.shortcut-desc {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-3);
}
</style>
