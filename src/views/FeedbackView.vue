<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { feedbackApi } from '../api'
import type { FeedbackItem } from '../types'

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const loading = ref(false)
const items = ref<FeedbackItem[]>([])
const total = ref(0)
const pages = ref(1)
const page = ref(1)
const size = ref(10)
const filters = reactive({ status: '', rating: '', reason: '' })

const REASON_MAP: Record<string, string> = {
  inaccurate: '答案不准确',
  incomplete: '答案不完整',
  outdated: '条文过时',
  wrong_citation: '引用错误',
  other: '其他',
}
const STATUS_MAP: Record<string, { label: string; type: TagType }> = {
  open: { label: '待处理', type: 'warning' },
  handled: { label: '已处理', type: 'success' },
  ignored: { label: '已忽略', type: 'info' },
}

async function load() {
  loading.value = true
  try {
    const data: any = await feedbackApi.list({
      status: filters.status,
      rating: filters.rating,
      reason: filters.reason,
      page: page.value,
      size: size.value,
    })
    items.value = data.items || []
    total.value = data.total || 0
    pages.value = data.pages || 1
  } catch (e: any) {
    ElMessage.error(e?.message || '反馈列表加载失败')
  } finally {
    loading.value = false
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

onMounted(load)
</script>

<template>
  <section class="doc-page">
    <div class="doc-header">
      <div>
        <h1>反馈处理</h1>
        <p>用户点赞 / 点踩记录，按原因与状态定位答案问题</p>
      </div>
      <el-button @click="load">刷新</el-button>
    </div>

    <div class="page-toolbar">
      <el-select v-model="filters.status" class="filter-item" style="width:130px" clearable placeholder="全部状态" @change="page = 1; load()">
        <el-option v-for="(v, k) in STATUS_MAP" :key="k" :value="k" :label="v.label" />
      </el-select>
      <el-select v-model="filters.rating" class="filter-item" style="width:120px" clearable placeholder="全部评价" @change="page = 1; load()">
        <el-option value="1" label="点赞" />
        <el-option value="-1" label="点踩" />
      </el-select>
      <el-select v-model="filters.reason" class="filter-item" style="width:130px" clearable placeholder="全部原因" @change="page = 1; load()">
        <el-option v-for="(label, k) in REASON_MAP" :key="k" :value="k" :label="label" />
      </el-select>
      <span class="spacer"></span>
      <span class="tag gray">共 {{ total }} 条</span>
    </div>

    <el-table :data="items" v-loading="loading" stripe>
      <template #empty>
        <el-empty description="暂无反馈" />
      </template>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column label="消息" width="80">
        <template #default="{ row }">#{{ row.message_id }}</template>
      </el-table-column>
      <el-table-column label="用户" width="80">
        <template #default="{ row }">#{{ row.user_id }}</template>
      </el-table-column>
      <el-table-column label="评价" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.rating === 1" size="small" type="success">👍 点赞</el-tag>
          <el-tag v-else size="small" type="danger">👎 点踩</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="原因" width="110">
        <template #default="{ row }">{{ REASON_MAP[row.reason] || row.reason || '—' }}</template>
      </el-table-column>
      <el-table-column label="答案摘要" min-width="200">
        <template #default="{ row }">
          <div class="digest">{{ row.answer_digest || '—' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="说明" width="170">
        <template #default="{ row }">
          <div class="digest">{{ row.comment || '—' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="STATUS_MAP[row.status]?.type">{{ STATUS_MAP[row.status]?.label || row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="时间" width="170" />
    </el-table>

    <div class="pager-row" style="margin-top:14px">
      <el-pagination
        background
        layout="total, prev, pager, next, sizes"
        :total="total"
        :page-sizes="[10, 20, 50]"
        v-model:current-page="page"
        v-model:page-size="size"
        @current-change="goPage"
        @size-change="onSizeChange"
      />
    </div>
  </section>
</template>

<style scoped>
.digest {
  max-width: 280px;
  font-size: 12.5px;
  color: var(--text-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
