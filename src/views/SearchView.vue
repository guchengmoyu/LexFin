<script setup>
import { computed, ref } from 'vue'
import { retrieveApi, documentApi } from '../api'
import { useKbStore } from '../stores/kb'

const kbStore = useKbStore()
const q = ref('')
const mode = ref('hybrid')
const kbId = ref('')
const category = ref('')
const timeliness = ref('')
const topK = ref(10)
const searching = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const latency = ref(null)

const TIMELINESS = {
  effective: { label: '现行有效', cls: 'green' },
  amended: { label: '已修订', cls: 'yellow' },
  repealed: { label: '已废止', cls: 'red' },
  unknown: { label: '未知', cls: 'gray' },
}

const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

async function doSearch(p = 1) {
  if (!q.value.trim()) return alert('请输入检索词')
  searching.value = true
  page.value = p
  try {
    const data = await retrieveApi.search({
      q: q.value.trim(), mode: mode.value, kb_id: kbId.value || undefined,
      category: category.value || undefined, timeliness: timeliness.value || undefined,
      page: page.value, size: size.value, highlight: true,
    })
    items.value = data.items || []
    total.value = data.total || 0
    latency.value = data.latency_ms
  } catch (e) {
    alert(e.message || '检索失败')
  } finally {
    searching.value = false
  }
}

function goPage(p) { doSearch(p) }

async function download(item) {
  if (!item.document_id) return
  try { await documentApi.download(item.document_id, `${item.doc_title || 'document'}.pdf`) }
  catch (e) { alert(e.message || '下载失败') }
}

kbStore.ensureLoaded()
</script>

<template>
  <div class="doc-page">
    <header class="doc-header">
      <div><h1>检索中心</h1><p>纯检索（无 LLM），支持关键词 / 向量 / 混合三种模式，结果含条文与页码定位</p></div>
    </header>

    <div class="search-bar">
      <input v-model="q" class="input grow" placeholder="输入检索词，Enter 检索" @keyup.enter="doSearch(1)" />
      <select v-model="mode" class="select" style="width:110px">
        <option value="hybrid">混合</option><option value="vector">向量</option><option value="keyword">关键词</option>
      </select>
      <select v-model="kbId" class="select" style="width:160px"><option value="">全部知识库</option><option v-for="kb in kbStore.list" :key="kb.id" :value="kb.id">{{ kb.name }}</option></select>
      <select v-model="category" class="select" style="width:120px"><option value="">全部分类</option><option value="banking">银行监管</option><option value="securities">证券行业</option><option value="insurance">保险制度</option></select>
      <select v-model="timeliness" class="select" style="width:120px"><option value="">全部时效</option><option value="effective">现行有效</option><option value="amended">已修订</option><option value="repealed">已废止</option></select>
      <select v-model.number="size" class="select" style="width:100px" @change="doSearch(1)"><option :value="10">10 条/页</option><option :value="20">20 条/页</option><option :value="50">50 条/页</option></select>
      <button class="btn" :disabled="searching" @click="doSearch(1)"><span v-if="searching" class="spin" />检索</button>
    </div>

    <div v-if="latency != null" class="latency-line">耗时 {{ latency }} ms · 共 {{ total }} 条结果</div>

    <div v-if="searching" class="empty-tip">检索中…</div>
    <div v-else-if="!items.length && q" class="empty-tip">未命中任何切片，建议更换关键词或扩大知识库范围</div>
    <div v-else class="result-list">
      <div v-for="it in items" :key="`${it.source_type}-${it.source_id}`" class="result-card">
        <div class="result-top">
          <span class="cite-idx">#{{ it.rank }}</span>
          <span v-if="it.source_type === 'knowledge_point'" class="tag purple">知识点</span>
          <span class="cite-doc" :title="it.doc_title">{{ it.doc_title || it.title }}</span>
          <span v-if="it.article_no" class="cite-article">{{ it.article_no }}</span>
          <span v-if="it.timeliness" class="tag" :class="TIMELINESS[it.timeliness]?.cls || 'gray'">{{ TIMELINESS[it.timeliness]?.label || it.timeliness }}</span>
          <span v-if="it.page_no != null" class="tag gray">第 {{ it.page_no }} 页</span>
        </div>
        <div class="result-snippet" v-html="it.highlight || it.snippet"></div>
        <div class="result-foot">
          <span v-if="it.doc_no">{{ it.doc_no }}</span>
          <span v-if="it.vector_rank != null">向量 #{{ it.vector_rank }}</span>
          <span v-if="it.keyword_rank != null">关键词 #{{ it.keyword_rank }}</span>
          <span>得分 {{ it.score }}</span>
          <a v-if="it.document_id" class="cite-page" href="javascript:;" @click="download(it)">下载原文</a>
        </div>
      </div>
    </div>

    <div v-if="total > size" class="pagination">
      <span>共 {{ total }} 条</span>
      <button class="page-btn" :disabled="page <= 1" @click="goPage(page - 1)">‹</button>
      <button v-for="p in pages" :key="p" class="page-btn" :class="{ active: p === page }" @click="goPage(p)">{{ p }}</button>
      <button class="page-btn" :disabled="page >= pages" @click="goPage(page + 1)">›</button>
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
.result-foot { display:flex; gap:12px; margin-top:8px; font-size:11.5px; color:var(--text-3); flex-wrap:wrap; }
</style>
