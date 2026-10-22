<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { feedbackApi } from '../api'

const tab = ref('evaluate')

const form = reactive({
  target_type: 'answer',
  target_id: '' as string | number,
  is_correct: 1,
  error_type: '',
  comment: '',
  batch_no: '',
})
const submitting = ref(false)

const statQuery = reactive({ batch_no: '', target_type: 'answer' })
const stats = ref<any>(null)
const statsLoading = ref(false)

const ERROR_TYPES: Record<string, string> = {
  retrieval_miss: '检索未命中',
  hallucination: '内容编造',
  citation_wrong: '引用错误',
  outdated: '条文过时',
  incomplete: '答案不完整',
}
const TARGET_TYPES: Record<string, string> = { answer: '答案', knowledge_point: '知识点' }

const accuracyPct = computed(() =>
  stats.value ? `${(Number(stats.value.accuracy) * 100).toFixed(1)}%` : '—',
)
const maxErrorCount = computed(() => {
  const list = stats.value?.error_type_distribution || []
  return Math.max(1, ...list.map((e: any) => Number(e.count) || 0))
})

async function submitReview() {
  if (!form.batch_no.trim()) {
    ElMessage.warning('请填写评测批次号')
    return
  }
  if (!form.target_id) {
    ElMessage.warning('请填写评测目标 ID')
    return
  }
  submitting.value = true
  try {
    await feedbackApi.review({
      target_type: form.target_type,
      target_id: Number(form.target_id),
      is_correct: Number(form.is_correct),
      error_type: form.is_correct === 0 ? form.error_type || undefined : undefined,
      comment: form.comment || undefined,
      batch_no: form.batch_no.trim(),
    })
    ElMessage.success('评测结果已保存')
    form.target_id = ''
    form.comment = ''
  } catch (e: any) {
    ElMessage.error(e?.message || '提交失败')
  } finally {
    submitting.value = false
  }
}

async function loadStats() {
  if (!statQuery.batch_no.trim()) {
    ElMessage.warning('请填写评测批次号')
    return
  }
  statsLoading.value = true
  try {
    stats.value = await feedbackApi.reviewStats(statQuery.batch_no.trim(), statQuery.target_type)
  } catch (e: any) {
    ElMessage.error(e?.message || '统计加载失败')
  } finally {
    statsLoading.value = false
  }
}

onMounted(() => {
  statQuery.batch_no = 'EVAL-20250601'
})
</script>

<template>
  <section class="doc-page">
    <div class="doc-header">
      <div>
        <h1>人工校验与准确率</h1>
        <p>答案评测落库入口；准确率对照 ≥ 85% 验收阈值</p>
      </div>
    </div>

    <div class="tabs">
      <button class="tab" :class="{ active: tab === 'evaluate' }" @click="tab = 'evaluate'">答案评测</button>
      <button class="tab" :class="{ active: tab === 'report' }" @click="tab = 'report'">准确率报告</button>
    </div>

    <!-- Tab 1：逐题评测 -->
    <div v-if="tab === 'evaluate'" class="split-layout">
      <div class="panel">
        <h3 class="panel-title">评测对象</h3>
        <label class="form-label">评测批次号</label>
        <el-input v-model="form.batch_no" placeholder="如 EVAL-20250601" />

        <label class="form-label">目标类型</label>
        <el-select v-model="form.target_type" style="width:100%">
          <el-option v-for="(label, k) in TARGET_TYPES" :key="k" :value="k" :label="label" />
        </el-select>

        <label class="form-label">目标 ID</label>
        <el-input v-model="form.target_id" type="number" placeholder="答案 message_id 或知识点 id" />

        <p class="hint">
          对照会话回看中的答案与引用后录入结论；同一条目重复提交会覆盖原记录。
        </p>
      </div>

      <div class="panel">
        <h3 class="panel-title">评测结论</h3>
        <div class="radio-row">
          <el-radio-group v-model="form.is_correct">
            <el-radio-button :value="1">正确</el-radio-button>
            <el-radio-button :value="0">错误</el-radio-button>
          </el-radio-group>
        </div>

        <template v-if="form.is_correct === 0">
          <label class="form-label">错误类型</label>
          <el-select v-model="form.error_type" style="width:100%">
            <el-option value="" label="未选择" />
            <el-option v-for="(label, k) in ERROR_TYPES" :key="k" :value="k" :label="label" />
          </el-select>
        </template>

        <label class="form-label">备注</label>
        <el-input v-model="form.comment" type="textarea" :rows="4" placeholder="可选，最多 1000 字" />

        <div style="margin-top: 14px">
          <el-button type="primary" :loading="submitting" @click="submitReview">
            {{ submitting ? '提交中…' : '提交评测' }}
          </el-button>
        </div>
      </div>
    </div>

    <!-- Tab 2：准确率报告 -->
    <template v-else>
      <div class="page-toolbar">
        <el-input v-model="statQuery.batch_no" class="filter-item" style="width:200px" placeholder="评测批次号" />
        <el-select v-model="statQuery.target_type" class="filter-item" style="width:140px">
          <el-option v-for="(label, k) in TARGET_TYPES" :key="k" :value="k" :label="label" />
        </el-select>
        <el-button type="primary" :loading="statsLoading" @click="loadStats">
          {{ statsLoading ? '查询中…' : '查询报告' }}
        </el-button>
      </div>

      <el-empty v-if="!stats" description="填写批次号后查询准确率报告" />

      <template v-else>
        <div class="report-hero panel">
          <div>
            <div class="metric-label">答案准确率</div>
            <div class="big-accuracy" :class="stats.pass ? 'pass' : 'fail'">{{ accuracyPct }}</div>
            <div class="metric-label">
              阈值 {{ (stats.threshold * 100).toFixed(0) }}% ·
              <span :class="stats.pass ? 'pass-text' : 'fail-text'">{{ stats.pass ? '通过 ✅' : '未通过 ❌' }}</span>
            </div>
          </div>
          <div class="metric-grid" style="margin: 0; flex: 1; max-width: 620px">
            <div class="metric-card"><div class="metric-num">{{ stats.total }}</div><div class="metric-label">评测总数</div></div>
            <div class="metric-card"><div class="metric-num">{{ stats.correct }}</div><div class="metric-label">正确</div></div>
            <div class="metric-card"><div class="metric-num">{{ stats.incorrect }}</div><div class="metric-label">错误</div></div>
            <div class="metric-card"><div class="metric-num">{{ stats.reviewer_count }}</div><div class="metric-label">评测人数</div></div>
            <div class="metric-card highlight">
              <div class="metric-num">{{ stats.cohen_kappa == null ? '—' : stats.cohen_kappa }}</div>
              <div class="metric-label">Cohen's Kappa</div>
            </div>
          </div>
        </div>

        <div class="panel" style="margin-top: 16px">
          <h3 class="panel-title">错误类型分布</h3>
          <el-empty v-if="!stats.error_type_distribution?.length" description="本批次无错误记录" :image-size="60" />
          <div v-for="e in stats.error_type_distribution" :key="e.error_type" class="bar-row">
            <span class="bar-label">{{ ERROR_TYPES[e.error_type] || e.error_type }}</span>
            <span class="bar-track">
              <span class="bar-fill" :style="{ width: `${(e.count / maxErrorCount) * 100}%` }"></span>
            </span>
            <span>{{ e.count }}</span>
          </div>
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
.form-label {
  display: block;
  font-size: 13px;
  color: var(--text-2);
  margin: 12px 0 6px;
}

.hint {
  margin-top: 14px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.7;
}

.radio-row {
  margin-bottom: 6px;
}

.report-hero {
  display: flex;
  align-items: center;
  gap: 32px;
  flex-wrap: wrap;
}

.pass-text {
  color: #21a366;
}

.fail-text {
  color: #e5484d;
}
</style>
