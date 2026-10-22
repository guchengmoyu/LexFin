<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { qaApi } from '../api'
import type { SessionSummary } from '../types'

const router = useRouter()
const loading = ref(false)
const sessions = ref<SessionSummary[]>([])
const total = ref(0)
const pages = ref(1)
const page = ref(1)
const size = 20

async function load(): Promise<void> {
  loading.value = true
  try {
    const data: any = await qaApi.sessions(page.value, size)
    sessions.value = data.items || []
    total.value = data.total || 0
    pages.value = data.pages || 1
  } catch (e: any) {
    ElMessage.error(e.message || '历史会话加载失败')
  } finally {
    loading.value = false
  }
}

function goPage(p: number): void {
  if (p < 1 || p > pages.value) return
  page.value = p
  load()
}

function open(s: SessionSummary): void {
  router.push({ name: 'chat-session', params: { sessionNo: s.session_no } })
}

async function remove(s: SessionSummary): Promise<void> {
  const ok = await ElMessageBox.confirm(`删除会话「${s.title || s.session_no}」？`, '提示', {
    type: 'warning',
  })
    .then(() => true)
    .catch(() => false)
  if (!ok) return
  try {
    await qaApi.deleteSession(s.session_no)
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
        <h1>问答历史</h1>
        <p>共 {{ total }} 个会话，点击进入可完整回看回答与引用</p>
      </div>
    </div>

    <div v-if="loading" class="empty-state">加载中…</div>
    <el-empty v-else-if="!sessions.length" description="暂无历史会话" />

    <div v-else class="history-list">
      <div v-for="s in sessions" :key="s.session_no" class="history-item" @click="open(s)">
        <div class="history-main">
          <div class="history-title">{{ s.title || '未命名会话' }}</div>
          <div class="history-meta">
            <el-tag size="small" type="info">{{ s.message_count }} 条消息</el-tag>
            <span>{{ s.last_active_at || '—' }}</span>
            <span class="doc-no">{{ s.session_no }}</span>
          </div>
        </div>
        <el-button size="small" type="danger" plain :icon="Delete" @click.stop="remove(s)">删除</el-button>
      </div>
    </div>

    <div class="pager-row">
      <el-pagination
        v-model:current-page="page"
        layout="total, prev, pager, next"
        :total="total"
        :page-size="size"
        @current-change="goPage"
      />
    </div>
  </section>
</template>

<style scoped>
.history-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  padding: 12px 16px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.history-item:hover {
  border-color: var(--primary);
  box-shadow: 0 2px 8px rgba(47, 111, 237, 0.08);
}

.history-main {
  flex: 1;
  min-width: 0;
}

.history-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-3);
}
</style>
