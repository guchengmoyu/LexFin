<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Delete, Plus, Check } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { favoriteApi, kpApi, documentApi } from '../api'
import { useAuthStore } from '../stores/auth'
import type { FavoriteItem } from '../types'

const router = useRouter()
const auth = useAuthStore()

const tab = ref<'fav' | 'study' | 'recommend'>('fav')

// ---------------------------------------------------------------- 我的收藏（原有功能）
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

// ---------------------------------------------------------------- 学习清单（本地持久化，按用户隔离）
interface StudyItem {
  id: number
  title: string
  note: string
  done: boolean
  createdAt: string
}

const storageKey = computed(() => `lexfin_study_list_${auth.user?.id || 'anon'}`)
const studyList = ref<StudyItem[]>([])
const studyForm = reactive({ title: '', note: '' })

function loadStudy() {
  try {
    studyList.value = JSON.parse(localStorage.getItem(storageKey.value) || '[]')
  } catch {
    studyList.value = []
  }
}

function saveStudy() {
  localStorage.setItem(storageKey.value, JSON.stringify(studyList.value))
}

const studyDone = computed(() => studyList.value.filter((s) => s.done).length)

function addStudy() {
  if (!studyForm.title.trim()) {
    ElMessage.warning('请填写学习内容')
    return
  }
  studyList.value.unshift({
    id: Date.now(),
    title: studyForm.title.trim(),
    note: studyForm.note.trim(),
    done: false,
    createdAt: new Date().toLocaleString('zh-CN', { hour12: false }),
  })
  studyForm.title = ''
  studyForm.note = ''
  saveStudy()
}

function toggleStudy(item: StudyItem) {
  item.done = !item.done
  saveStudy()
}

function removeStudy(item: StudyItem) {
  studyList.value = studyList.value.filter((s) => s.id !== item.id)
  saveStudy()
}

function clearDone() {
  studyList.value = studyList.value.filter((s) => !s.done)
  saveStudy()
}

// ---------------------------------------------------------------- 推荐阅读（来自知识库的公开内容）
const recKps = ref<any[]>([])
const recDocs = ref<any[]>([])
const recLoading = ref(false)

async function loadRecommend() {
  recLoading.value = true
  try {
    const [kpData, docData]: any[] = await Promise.allSettled([
      kpApi.list({ size: 6, status: 'published' }),
      documentApi.list({ size: 4 }),
    ])
    recKps.value = kpData.status === 'fulfilled' ? kpData.value?.items || [] : []
    recDocs.value = docData.status === 'fulfilled' ? docData.value?.items || [] : []
  } finally {
    recLoading.value = false
  }
}

function openKp(id: number) {
  router.push({ name: 'knowledge-point-detail', params: { id } })
}

function openDoc(id: number) {
  router.push({ name: 'document-detail', params: { id } })
}

onMounted(() => {
  load()
  loadStudy()
  loadRecommend()
})
</script>

<template>
  <div class="doc-page">
    <header class="doc-header">
      <div>
        <h1>我的收藏</h1>
        <p>收藏的问答、个人学习清单与推荐阅读</p>
      </div>
    </header>

    <div class="tabs">
      <button class="tab" :class="{ active: tab === 'fav' }" @click="tab = 'fav'">我的收藏</button>
      <button class="tab" :class="{ active: tab === 'study' }" @click="tab = 'study'">学习清单</button>
      <button class="tab" :class="{ active: tab === 'recommend' }" @click="tab = 'recommend'">推荐阅读</button>
    </div>

    <!-- ==================== 我的收藏 ==================== -->
    <template v-if="tab === 'fav'">
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
    </template>

    <!-- ==================== 学习清单 ==================== -->
    <template v-else-if="tab === 'study'">
      <div class="panel study-add">
        <el-input v-model="studyForm.title" placeholder="要学习的内容，如：流动性覆盖率监管要求" style="flex: 2" @keyup.enter="addStudy" />
        <el-input v-model="studyForm.note" placeholder="备注（可选）" style="flex: 1.4" @keyup.enter="addStudy" />
        <el-button type="primary" :icon="Plus" @click="addStudy">添加</el-button>
      </div>

      <div class="study-meta">
        <el-progress
          :percentage="studyList.length ? Math.round((studyDone / studyList.length) * 100) : 0"
          :stroke-width="8"
          style="max-width: 320px"
        />
        <span class="doc-no">已完成 {{ studyDone }}/{{ studyList.length }}</span>
        <el-button v-if="studyDone" link type="danger" size="small" @click="clearDone">清除已完成</el-button>
      </div>

      <el-empty v-if="!studyList.length" description="暂无学习项，添加一条开始吧" />
      <div v-else class="study-list">
        <div v-for="s in studyList" :key="s.id" class="panel study-item" :class="{ done: s.done }">
          <el-checkbox :model-value="s.done" @change="toggleStudy(s)" />
          <div class="study-body">
            <div class="study-title">{{ s.title }}</div>
            <div v-if="s.note" class="study-note">{{ s.note }}</div>
            <div class="study-time">{{ s.createdAt }}</div>
          </div>
          <el-tag v-if="s.done" size="small" type="success" :icon="Check">已完成</el-tag>
          <el-button link type="danger" size="small" :icon="Delete" @click="removeStudy(s)" />
        </div>
      </div>
    </template>

    <!-- ==================== 推荐阅读 ==================== -->
    <template v-else>
      <div v-if="recLoading" class="empty-tip">加载中…</div>
      <template v-else>
        <h3 class="panel-title" style="margin-bottom: 10px">精选知识点</h3>
        <el-empty v-if="!recKps.length" description="暂无推荐知识点" :image-size="60" />
        <div v-else class="rec-grid">
          <div v-for="kp in recKps" :key="kp.id" class="panel rec-card" @click="openKp(kp.id)">
            <div class="rec-title">{{ kp.title }}</div>
            <div class="rec-desc">{{ (kp.content || '').slice(0, 80) }}…</div>
            <div class="rec-meta">
              <el-tag size="small" type="success">{{ kp.category || '知识点' }}</el-tag>
              <span v-if="kp.doc_no" class="doc-no">{{ kp.doc_no }}</span>
            </div>
          </div>
        </div>

        <h3 class="panel-title" style="margin: 18px 0 10px">最新制度文档</h3>
        <el-empty v-if="!recDocs.length" description="暂无文档" :image-size="60" />
        <div v-else class="rec-grid">
          <div v-for="d in recDocs" :key="d.id" class="panel rec-card" @click="openDoc(d.id)">
            <div class="rec-title">{{ d.title }}</div>
            <div class="rec-meta">
              <el-tag size="small">{{ d.category || '文档' }}</el-tag>
              <span class="doc-no">{{ d.created_at || '' }}</span>
            </div>
          </div>
        </div>
      </template>
    </template>
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

.study-add {
  display: flex;
  gap: 10px;
  align-items: center;
  max-width: 900px;
}

.study-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 12px 0;
}

.study-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 900px;
}

.study-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
}

.study-item.done .study-title {
  text-decoration: line-through;
  color: var(--text-3);
}

.study-body {
  flex: 1;
  min-width: 0;
}

.study-title {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text-1);
}

.study-note {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-2);
}

.study-time {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-3);
}

.rec-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.rec-card {
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.rec-card:hover {
  border-color: var(--primary);
  box-shadow: 0 2px 10px rgba(79, 124, 255, 0.12);
}

.rec-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.rec-desc {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
}

.rec-meta {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
