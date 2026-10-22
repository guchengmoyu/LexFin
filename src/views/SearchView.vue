<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, Download } from '@element-plus/icons-vue'
import { retrieveApi, documentApi } from '../api'
import { useKbStore } from '../stores/kb'
import type { SearchHit } from '../types'

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

const route = useRoute()
const router = useRouter()
const kbStore = useKbStore()
const q = ref('')
const mode = ref<'keyword' | 'vector' | 'hybrid'>('hybrid')
const kbId = ref<string | number>('')
const category = ref('')
const timeliness = ref('')
const topK = ref(10)
const searching = ref(false)
const items = ref<SearchHit[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const latency = ref<number | null>(null)

const TIMELINESS: Record<string, { label: string; type: TagType }> = {
  effective: { label: '现行有效', type: 'success' },
  amended: { label: '已修订', type: 'warning' },
  repealed: { label: '已废止', type: 'danger' },
  unknown: { label: '未知', type: 'info' },
}

async function doSearch(p = 1) {
  if (!q.value.trim()) { ElMessage.warning('请输入检索词'); return }
  searching.value = true
  page.value = p
  // URL ?q= 同步
  router.replace({ query: { ...route.query, q: q.value.trim() } })
  try {
    const data: any = await retrieveApi.search({
      q: q.value.trim(), mode: mode.value, kb_id: kbId.value || undefined,
      category: category.value || undefined, timeliness: timeliness.value || undefined,
      page: page.value, size: size.value, highlight: true,
    })
    items.value = data.items || []
    total.value = data.total || 0
    latency.value = data.latency_ms
  } catch (e: any) {
    ElMessage.error(e?.message || '检索失败')
  } finally {
    searching.value = false
  }
}

function goPage(p: number) { doSearch(p) }

async function download(item: any) {
  if (!item.document_id) return
  try { await documentApi.download(item.document_id, `${item.doc_title || 'document'}.pdf`) }
  catch (e: any) { ElMessage.error(e?.message || '下载失败') }
}

kbStore.ensureLoaded()

onMounted(() => {
  // 支持 ?q= 直达检索
  const qs = (route.query.q as string) || ''
  if (qs.trim()) { q.value = qs; doSearch(1) }
})
</script>

<template>
  <div class="doc-page">
    <header class="doc-header">
      <div><h1>检索中心</h1><p>纯检索（无 LLM），支持关键词 / 向量 / 混合三种模式，结果含条文与页码定位</p></div>
    </header>

    <div class="search-bar">
      <el-input v-model="q" class="grow" style="flex:1; min-width:220px" clearable placeholder="输入检索词，Enter 检索" :prefix-icon="Search" @keyup.enter="doSearch(1)" />
      <el-radio-group v-model="mode">
        <el-radio-button value="hybrid">混合</el-radio-button>
        <el-radio-button value="vector">向量</el-radio-button>
        <el-radio-button value="keyword">关键词</el-radio-button>
      </el-radio-group>
      <el-select v-model="kbId" style="width:160px" clearable placeholder="全部知识库">
        <el-option v-for="kb in kbStore.list" :key="kb.id" :value="kb.id" :label="kb.name" />
      </el-select>
      <el-select v-model="category" style="width:120px" clearable placeholder="全部分类">
        <el-option value="banking" label="银行监管" />
        <el-option value="securities" label="证券行业" />
        <el-option value="insurance" label="保险制度" />
      </el-select>
      <el-select v-model="timeliness" style="width:120px" clearable placeholder="全部时效">
        <el-option value="effective" label="现行有效" />
        <el-option value="amended" label="已修订" />
        <el-option value="repealed" label="已废止" />
      </el-select>
      <el-select v-model="size" style="width:100px" @change="doSearch(1)">
        <el-option :value="10" label="10 条/页" />
        <el-option :value="20" label="20 条/页" />
        <el-option :value="50" label="50 条/页" />
      </el-select>
      <el-button type="primary" :icon="Search" :loading="searching" @click="doSearch(1)">检索</el-button>
    </div>

    <div v-if="latency != null" class="latency-line">耗时 {{ latency }} ms · 共 {{ total }} 条结果</div>

    <div v-if="searching" class="empty-tip">检索中…</div>
    <el-empty v-else-if="!items.length && q" description="未命中任何切片，建议更换关键词或扩大知识库范围" />
    <el-empty v-else-if="!items.length" description="输入检索词，Enter 或点击「检索」开始" />
    <div v-else class="result-list">
      <div v-for="it in items" :key="`${it.source_type}-${it.source_id}`" class="result-card">
        <div class="result-top">
          <span class="cite-idx">#{{ it.rank }}</span>
          <el-tag v-if="it.source_type === 'knowledge_point'" size="small">知识点</el-tag>
          <span class="cite-doc" :title="it.doc_title">{{ it.doc_title || it.title }}</span>
          <span v-if="it.article_no" class="cite-article">{{ it.article_no }}</span>
          <el-tag v-if="it.timeliness" size="small" :type="TIMELINESS[it.timeliness]?.type || 'info'">{{ TIMELINESS[it.timeliness]?.label || it.timeliness }}</el-tag>
          <el-tag v-if="it.page_no != null" size="small" type="info">第 {{ it.page_no }} 页</el-tag>
        </div>
        <div class="result-snippet" v-html="it.highlight || it.snippet"></div>
        <div class="result-foot">
          <span v-if="it.doc_no">{{ it.doc_no }}</span>
          <span v-if="it.vector_rank != null">向量 #{{ it.vector_rank }}</span>
          <span v-if="it.keyword_rank != null">关键词 #{{ it.keyword_rank }}</span>
          <span>得分 {{ it.score }}</span>
          <el-button v-if="it.document_id" link type="primary" :icon="Download" @click="download(it)">下载原文</el-button>
        </div>
      </div>
    </div>

    <div v-if="total > size" class="pagination" style="margin-top:14px">
      <el-pagination
        background
        layout="total, prev, pager, next, sizes"
        :total="total"
        :page-sizes="[10, 20, 50]"
        v-model:current-page="page"
        v-model:page-size="size"
        @current-change="goPage"
        @size-change="() => doSearch(1)"
      />
    </div>
  </div>
</template>

<style scoped>
.search-bar { display:flex; gap:10px; margin-bottom:12px; align-items:center; flex-wrap:wrap; }
.search-bar .grow { flex:1; min-width:220px; }
.latency-line { font-size:12px; color:var(--text-3); margin-bottom:12px; }
.result-list { display:flex; flex-direction:column; gap:10px; }
.result-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-sm); padding:14px; }
.result-top { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:8px; }
.result-snippet { font-size:13.5px; line-height:1.7; color:var(--text-2); white-space:pre-wrap; word-break:break-word; }
.result-foot { display:flex; gap:12px; margin-top:8px; font-size:11.5px; color:var(--text-3); flex-wrap:wrap; align-items:center; }
</style>
