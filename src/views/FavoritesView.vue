<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { favoriteApi } from '../api'
import type { FavoriteItem } from '../types'

const list = ref<FavoriteItem[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const data: any = await favoriteApi.list(page.value, size.value)
    list.value = data.items || []
    total.value = data.total || 0
  } catch (e: any) {
    ElMessage.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function remove(item: FavoriteItem): Promise<void> {
  const ok = await ElMessageBox.confirm(`取消收藏「${item.title || item.message_id}」？`, '提示', {
    type: 'warning',
  })
    .then(() => true)
    .catch(() => false)
  if (!ok) return
  try {
    await favoriteApi.remove(item.message_id)
    load()
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}
onMounted(load)
</script>

<template>
  <div class="doc-page">
    <header class="doc-header"><div><h1>我的收藏</h1><p>收藏的问答记录，便于快速回看高质量答案</p></div></header>

    <div v-if="loading" class="empty-tip">加载中…</div>
    <el-empty v-else-if="!list.length" description="暂无收藏，去问答页点击「⭐ 收藏」" />
    <div v-else class="fav-list">
      <div v-for="f in list" :key="f.id" class="fav-card">
        <div class="fav-head">
          <el-tag type="primary" size="small">Q</el-tag>
          <span class="fav-q">{{ f.question || '（查看详情）' }}</span>
          <span v-if="f.created_at" class="fav-time">{{ f.created_at }}</span>
        </div>
        <div v-if="f.note" class="fav-note">📝 {{ f.note }}</div>
        <div class="fav-foot">
          <el-button size="small" type="danger" plain :icon="Delete" @click="remove(f)">取消收藏</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fav-list { display:flex; flex-direction:column; gap:10px; max-width:860px; }
.fav-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-sm); padding:14px; }
.fav-head { display:flex; align-items:center; gap:8px; }
.fav-q { font-weight:500; flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.fav-time { font-size:11px; color:var(--text-3); flex-shrink:0; }
.fav-note { font-size:12px; color:var(--text-2); margin-top:6px; }
.fav-foot { margin-top:8px; }
</style>
