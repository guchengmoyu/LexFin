<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { qaApi, documentApi, feedbackApi, favoriteApi } from '../api'
import { streamAsk } from '../api/sse'
import { useKbStore } from '../stores/kb'

const kbStore = useKbStore()

// ---------------------------------------------------------------- 状态
const sessions = ref([])
const currentSessionNo = ref(null)
const messages = ref([])
const question = ref('')
const sending = ref(false)
const loadingSession = ref(false)
const sessionsLoading = ref(false)

const settings = reactive({
  kbIds: [],
  mode: 'hybrid',
  topK: 5,
  useHistory: true,
})

let controller = null
const messagesEl = ref(null)
const taRef = ref(null)
const highlightCitation = ref(null)

const EXAMPLES = [
  '商业银行资本管理办法中核心一级资本充足率的最低要求是多少？',
  '流动性覆盖率的监管标准是什么？',
  '理财产品的销售新规有哪些要点？',
]

const TIMELINESS_MAP = {
  effective: { label: '现行有效', cls: 'green' },
  amended: { label: '已修订', cls: 'yellow' },
  unknown: { label: '时效未知', cls: 'gray' },
  repealed: { label: '已废止', cls: 'red' },
}

const CONF_MAP = {
  high: { label: '可信度高', cls: 'green' },
  medium: { label: '可信度中', cls: 'yellow' },
  low: { label: '可信度低', cls: 'red' },
}

// ---------------------------------------------------------------- 工具
function scrollBottom() {
  nextTick(() => {
    const el = messagesEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function parseContent(content) {
  // [n] 角标 → 可点击标记；越界角标后端已过滤，但渲染层只点亮存在的引用
  return String(content || '')
    .split(/(\[\d{1,2}\])/g)
    .map((seg) => {
      const m = seg.match(/^\[(\d{1,2})\]$/)
      return m ? { badge: Number(m[1]) } : { text: seg }
    })
}

function onBadgeClick(msg, n) {
  highlightCitation.value = null
  nextTick(() => {
    highlightCitation.value = { msgId: msg.id, index: n }
    const card = document.getElementById(`cite-${msg.id}-${n}`)
    card?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
}

function citationDoc(meta) {
  if (meta.knowledge_point_id) return `知识点 KP-${meta.knowledge_point_id}`
  return meta.doc_title || '未知文档'
}

async function downloadCitation(c) {
  if (!c.document_id) return
  try {
    await documentApi.download(c.document_id, `${c.doc_title || 'document'}.pdf`)
  } catch (e) {
    alert(e.message || '下载失败')
  }
}

// ---------------------------------------------------------------- 会话列表
async function loadSessions() {
  sessionsLoading.value = true
  try {
    const data = await qaApi.sessions(1, 50)
    sessions.value = data.items || []
  } catch {
    /* 忽略 */
  } finally {
    sessionsLoading.value = false
  }
}

function newChat() {
  if (sending.value) return
  currentSessionNo.value = null
  messages.value = []
}

async function openSession(s) {
  if (sending.value || s.session_no === currentSessionNo.value) return
  loadingSession.value = true
  try {
    const data = await qaApi.sessionDetail(s.session_no)
    currentSessionNo.value = s.session_no
    messages.value = (data.messages || data.items || []).map((m) => ({
      id: m.message_id,
      role: m.role,
      content: m.content || '',
      citations: m.role === 'assistant' ? m.citations || [] : [],
      done: m.role === 'assistant'
        ? {
            answer_type: m.answer_type,
            confidence: m.confidence,
            confidence_level:
              m.confidence == null ? null : m.confidence >= 0.8 ? 'high' : m.confidence >= 0.6 ? 'medium' : 'low',
            latency_ms: m.latency_ms,
          }
        : null,
      streaming: false,
      error: null,
      favorited: !!m.favorited,
      createdAt: m.created_at,
    }))
    scrollBottom()
  } catch (e) {
    alert(e.message || '加载会话失败')
  } finally {
    loadingSession.value = false
  }
}

async function removeSession(s) {
  if (!confirm(`删除会话「${s.title || s.session_no}」？`)) return
  try {
    await qaApi.deleteSession(s.session_no)
    if (s.session_no === currentSessionNo.value) newChat()
    await loadSessions()
  } catch (e) {
    alert(e.message || '删除失败')
  }
}

// ---------------------------------------------------------------- 问答
function newPlaceholder() {
  const id = `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const msg = reactive({
    id,
    role: 'assistant',
    content: '',
    citations: [],
    done: null,
    error: null,
    streaming: true,
    retrieved: false,
    startedAt: Date.now(),
  })
  messages.value.push(msg)
  scrollBottom()
  return msg
}

async function send(text) {
  const q = (text ?? question.value).trim()
  if (!q || sending.value) return
  if (q.length > 500) {
    alert('问题最多 500 字')
    return
  }

  question.value = ''
  messages.value.push({ id: `u-${Date.now()}`, role: 'user', content: q, citations: [], done: null, error: null, streaming: false })
  const assistant = newPlaceholder()
  sending.value = true
  controller = new AbortController()

  await streamAsk(
    {
      question: q,
      session_no: currentSessionNo.value,
      kb_ids: settings.kbIds.length ? settings.kbIds : undefined,
      mode: settings.mode,
      top_k: settings.topK,
      use_history: settings.useHistory,
    },
    {
      onMeta(data) {
        assistant.retrieved = true
        assistant.citations = data.citations || []
        if (data.message_id) assistant.id = data.message_id
        if (data.session_no) currentSessionNo.value = data.session_no
        scrollBottom()
      },
      onToken(delta) {
        assistant.content += delta
        scrollBottom()
      },
      onDone(data) {
        assistant.done = data
        assistant.streaming = false
        sending.value = false
        controller = null
        loadSessions()
      },
      onError(e) {
        assistant.error = e?.message || '生成失败'
        assistant.streaming = false
        sending.value = false
        controller = null
      },
    },
    controller,
  )
  // 客户端中断时也结束流式态
  if (assistant.streaming) {
    assistant.streaming = false
    sending.value = false
    controller = null
  }
}

function stopStream() {
  controller?.abort()
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}

// ---------------------------------------------------------------- 反馈与收藏
const feedbackDlg = ref(false)
const feedbackTarget = ref(null)
const feedbackForm = reactive({ reason: '', comment: '' })
const FEEDBACK_REASONS = [
  { value: 'retrieval_miss', label: '检索未命中' },
  { value: 'hallucination', label: '内容编造' },
  { value: 'citation_wrong', label: '引用错误' },
  { value: 'outdated', label: '条文过时' },
  { value: 'incomplete', label: '答案不完整' },
]

async function submitFeedback(msg, rating) {
  try {
    await feedbackApi.submit(msg.id, { rating })
    msg.feedbackRating = rating
  } catch (e) {
    alert(e.message || '反馈失败')
  }
}

function openFeedbackDlg(msg) {
  feedbackTarget.value = msg
  feedbackForm.reason = ''
  feedbackForm.comment = ''
  feedbackDlg.value = true
}

async function submitNegativeFeedback() {
  const msg = feedbackTarget.value
  try {
    await feedbackApi.submit(msg.id, {
      rating: -1,
      reason: feedbackForm.reason || undefined,
      comment: feedbackForm.comment || undefined,
    })
    msg.feedbackRating = -1
    feedbackDlg.value = false
  } catch (e) {
    alert(e.message || '反馈失败')
  }
}

async function toggleFavorite(msg) {
  try {
    if (msg.favorited) {
      await favoriteApi.remove(msg.id)
      msg.favorited = false
    } else {
      await favoriteApi.add(msg.id)
      msg.favorited = true
    }
  } catch (e) {
    alert(e.message || '操作失败')
  }
}


function toggleKb(id) {
  const i = settings.kbIds.indexOf(id)
  if (i >= 0) settings.kbIds.splice(i, 1)
  else if (settings.kbIds.length < 5) settings.kbIds.push(id)
  else alert('最多选择 5 个知识库')
}

onMounted(() => {
  loadSessions()
  kbStore.ensureLoaded()
})
</script>

<template>
  <div class="chat-page">
    <!-- ============ 会话侧栏 ============ -->
    <aside class="session-panel">
      <button class="btn new-chat" @click="newChat">＋ 新对话</button>
      <div v-if="sessionsLoading" class="empty-tip">加载中…</div>
      <div v-else-if="!sessions.length" class="empty-tip">暂无历史会话</div>
      <div v-else class="session-list">
        <div
          v-for="s in sessions"
          :key="s.session_no"
          class="session-item"
          :class="{ active: s.session_no === currentSessionNo }"
          @click="openSession(s)"
        >
          <div class="session-title">{{ s.title || '未命名会话' }}</div>
          <div class="session-meta">
            <span>{{ s.message_count }} 条消息</span>
            <span>{{ s.last_active_at || '' }}</span>
          </div>
          <button class="session-del" title="删除会话" @click.stop="removeSession(s)">✕</button>
        </div>
      </div>
    </aside>

    <!-- ============ 主对话区 ============ -->
    <section class="chat-main">
      <div ref="messagesEl" class="messages">
        <!-- 空状态 -->
        <div v-if="!messages.length" class="welcome">
          <div class="welcome-logo">LF</div>
          <h2>金融制度知识问答</h2>
          <p>基于混合检索与角标溯源，每条答案均可回溯至具体条文与页码</p>
          <div class="examples">
            <button v-for="ex in EXAMPLES" :key="ex" class="example-card" @click="send(ex)">
              {{ ex }}
            </button>
          </div>
        </div>

        <!-- 消息流 -->
        <template v-for="msg in messages" :key="msg.id">
          <!-- 用户消息 -->
          <div v-if="msg.role === 'user'" class="row user">
            <div class="bubble user-bubble">{{ msg.content }}</div>
          </div>

          <!-- 助手消息 -->
          <div v-else class="row assistant">
            <div class="assistant-avatar">AI</div>
            <div class="assistant-body">
              <!-- 生成状态行 -->
              <div v-if="msg.streaming" class="status-line">
                <span v-if="!msg.retrieved" class="spin dark" />
                <span v-else class="dot-stream">•</span>
                <span>{{ msg.retrieved ? '检索完成，正在生成答案…' : '正在检索知识库…' }}</span>
              </div>

              <!-- 答案正文 -->
              <div v-if="msg.content" class="answer-text">
                <template v-for="(seg, i) in parseContent(msg.content)" :key="i">
                  <sup
                    v-if="seg.badge !== undefined"
                    class="cite-badge"
                    :class="{ on: msg.citations.some((c) => c.cite_index === seg.badge) }"
                    @click="onBadgeClick(msg, seg.badge)"
                  >{{ seg.badge }}</sup>
                  <span v-else class="pre-wrap">{{ seg.text }}</span>
                </template>
              </div>

              <!-- 错误 -->
              <div v-if="msg.error" class="answer-error">⚠ {{ msg.error }}</div>

              <!-- 溯源引用 -->
              <div v-if="msg.citations.length" class="citations">
                <div class="citations-head">参考依据（{{ msg.citations.length }}）</div>
                <div
                  v-for="c in msg.citations"
                  :id="`cite-${msg.id}-${c.cite_index}`"
                  :key="c.cite_index"
                  class="cite-card"
                  :class="{
                    dim: msg.done?.used_citations && !msg.done.used_citations.includes(c.cite_index),
                    hl: highlightCitation && highlightCitation.msgId === msg.id && highlightCitation.index === c.cite_index,
                  }"
                >
                  <div class="cite-top">
                    <span class="cite-idx">[{{ c.cite_index }}]</span>
                    <span class="cite-doc" :title="c.doc_title">{{ citationDoc(c) }}</span>
                    <span v-if="c.article_no" class="cite-article">{{ c.article_no }}</span>
                    <span
                      v-if="c.timeliness"
                      class="tag"
                      :class="TIMELINESS_MAP[c.timeliness]?.cls || 'gray'"
                    >{{ TIMELINESS_MAP[c.timeliness]?.label || c.timeliness }}</span>
                  </div>
                  <div class="cite-snippet">{{ c.snippet }}</div>
                  <div class="cite-foot">
                    <span v-if="c.doc_no">{{ c.doc_no }}</span>
                    <span v-if="c.issuing_authority">{{ c.issuing_authority }}</span>
                    <a
                      v-if="c.page_no != null"
                      class="cite-page"
                      @click.prevent="downloadCitation(c)"
                      href="javascript:;"
                    >第 {{ c.page_no }} 页 · 下载原文</a>
                  </div>
                </div>
              </div>

              <!-- 完成态指标 -->
              <div v-if="msg.done && !msg.streaming" class="metrics">
                <span
                  v-if="msg.done.confidence_level"
                  class="tag"
                  :class="CONF_MAP[msg.done.confidence_level]?.cls || 'gray'"
                >{{ CONF_MAP[msg.done.confidence_level]?.label }} {{ ((msg.done.confidence ?? 0) * 100).toFixed(0) }}分</span>
                <span
                  v-if="msg.done.answer_type === 'refused'"
                  class="tag yellow"
                >知识库未命中，已拒答</span>
                <span v-if="msg.done.latency_ms != null" class="metric-item">耗时 {{ (msg.done.latency_ms / 1000).toFixed(1) }}s</span>
                <span v-if="msg.done.latency_detail?.retrieve != null" class="metric-item">检索 {{ msg.done.latency_detail.retrieve }}ms</span>
                <span v-if="msg.done.model_name" class="metric-item">{{ msg.done.model_name }}</span>
              </div>

              <!-- 拒答建议检索词 -->
              <div v-if="msg.done?.suggestions?.length" class="suggestions">
                <span class="sug-label">建议尝试：</span>
                <button
                  v-for="s in msg.done.suggestions"
                  :key="s"
                  class="sug-chip"
                  @click="send(s)"
                >{{ s }}</button>
              </div>

              <!-- 反馈与收藏（仅真实消息 id，本地占位 id 不展示） -->
              <div v-if="msg.done && !msg.streaming && typeof msg.id === 'number'" class="msg-actions">
                <button
                  class="act-btn"
                  :class="{ on: msg.feedbackRating === 1 }"
                  title="点赞"
                  @click="submitFeedback(msg, 1)"
                >👍</button>
                <button
                  class="act-btn"
                  :class="{ on: msg.feedbackRating === -1 }"
                  title="点踩/纠错"
                  @click="openFeedbackDlg(msg)"
                >👎</button>
                <button
                  class="act-btn"
                  :class="{ on: msg.favorited }"
                  title="收藏答案"
                  @click="toggleFavorite(msg)"
                >{{ msg.favorited ? '★' : '☆' }}</button>
                <span v-if="msg.feedbackRating === 1" class="act-tip">已点赞</span>
                <span v-else-if="msg.feedbackRating === -1" class="act-tip">已反馈</span>
                <span v-if="msg.favorited" class="act-tip">已收藏</span>
              </div>
            </div>
          </div>
        </template>

        <div v-if="loadingSession" class="empty-tip">加载会话中…</div>
      </div>

      <!-- ============ 输入区 ============ -->
      <div class="composer">
        <div class="composer-settings">
          <div class="kb-picker">
            <span class="picker-label">知识库</span>
            <button
              v-for="kb in kbStore.list"
              :key="kb.id"
              class="kb-chip"
              :class="{ on: settings.kbIds.includes(kb.id) }"
              :title="kb.description || kb.name"
              @click="toggleKb(kb.id)"
            >{{ kb.name }}</button>
            <span v-if="!kbStore.list.length" class="picker-empty">未加载到知识库</span>
          </div>
          <div class="settings-right">
            <label class="picker-label">
              检索
              <select v-model="settings.mode" class="mini-select">
                <option value="hybrid">混合</option>
                <option value="vector">向量</option>
                <option value="keyword">关键词</option>
              </select>
            </label>
            <label class="picker-label">
              引用数
              <select v-model.number="settings.topK" class="mini-select">
                <option v-for="n in [3, 5, 8, 10]" :key="n" :value="n">{{ n }}</option>
              </select>
            </label>
            <label class="picker-label checkbox">
              <input v-model="settings.useHistory" type="checkbox" /> 多轮
            </label>
          </div>
        </div>

        <div class="composer-input">
          <textarea
            ref="taRef"
            v-model="question"
            class="textarea"
            rows="2"
            placeholder="输入金融制度相关问题，Enter 发送 / Shift+Enter 换行（最多 500 字）"
            :disabled="sending"
            @keydown="onKeydown"
          />
          <button v-if="sending" class="btn stop-btn" @click="stopStream">
            <span class="stop-icon" />停止
          </button>
          <button v-else class="btn send-btn" :disabled="!question.trim()" @click="send()">
            发送
          </button>
        </div>
      </div>
    </section>

    <!-- ============ 点踩反馈弹窗 ============ -->
    <div v-if="feedbackDlg" class="modal-mask" @click.self="feedbackDlg = false">
      <div class="modal feedback-modal">
        <div class="modal-head">
          <h3>答案纠错反馈</h3>
          <button class="modal-close" @click="feedbackDlg = false">✕</button>
        </div>
        <div class="modal-body">
          <label class="form-label">问题类型</label>
          <select v-model="feedbackForm.reason" class="input">
            <option value="">请选择（可不选）</option>
            <option v-for="r in FEEDBACK_REASONS" :key="r.value" :value="r.value">{{ r.label }}</option>
          </select>
          <label class="form-label">补充说明</label>
          <textarea
            v-model="feedbackForm.comment"
            class="input textarea"
            rows="4"
            placeholder="请描述答案存在的问题，帮助改进检索与生成质量（可选）"
          />
        </div>
        <div class="modal-foot">
          <button class="btn btn-ghost" @click="feedbackDlg = false">取消</button>
          <button class="btn" @click="submitNegativeFeedback">提交反馈</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  height: 100%;
  min-height: 0;
}

/* ---------------- 会话侧栏 ---------------- */
.session-panel {
  width: 250px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  background: var(--surface);
  display: flex;
  flex-direction: column;
  padding: 14px 10px;
  min-height: 0;
}

.new-chat {
  width: 100%;
  margin-bottom: 12px;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.session-item {
  position: relative;
  padding: 9px 26px 9px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.15s;
}

.session-item:hover {
  background: var(--surface-2);
}

.session-item.active {
  background: var(--primary-soft);
}

.session-title {
  font-size: 13px;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-meta {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--text-3);
  margin-top: 3px;
}

.session-del {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  border: none;
  background: none;
  color: var(--text-3);
  cursor: pointer;
  font-size: 12px;
  opacity: 0;
  transition: opacity 0.15s;
}

.session-item:hover .session-del {
  opacity: 1;
}

.session-del:hover {
  color: var(--danger);
}

/* ---------------- 消息区 ---------------- */
.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 28px 8% 12px;
  min-height: 0;
}

.welcome {
  text-align: center;
  padding-top: 9vh;
}

.welcome-logo {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: linear-gradient(135deg, #2f6fed, #67a1ff);
  color: #fff;
  font-weight: 700;
  font-size: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
}

.welcome h2 {
  margin: 0 0 8px;
  font-size: 22px;
}

.welcome p {
  margin: 0 0 28px;
  color: var(--text-3);
  font-size: 13px;
}

.examples {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 520px;
  margin: 0 auto;
}

.example-card {
  text-align: left;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  font-size: 13px;
  color: var(--text-2);
  cursor: pointer;
  transition: all 0.15s;
}

.example-card:hover {
  border-color: var(--primary);
  color: var(--primary);
  box-shadow: var(--shadow);
}

.row {
  display: flex;
  margin-bottom: 22px;
  gap: 12px;
}

.row.user {
  justify-content: flex-end;
}

.bubble.user-bubble {
  max-width: 72%;
  background: var(--primary);
  color: #fff;
  padding: 11px 16px;
  border-radius: 14px 14px 4px 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, #2f6fed, #67a1ff);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.assistant-body {
  flex: 1;
  min-width: 0;
}

.status-line {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 13px;
  padding: 6px 0;
}

.dot-stream {
  color: var(--primary);
  animation: blink 1s infinite;
  font-size: 20px;
  line-height: 14px;
}

.answer-text {
  font-size: 14.5px;
  line-height: 1.8;
  color: var(--text-1);
  word-break: break-word;
}

.pre-wrap {
  white-space: pre-wrap;
}

.cite-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  margin: 0 2px;
  border-radius: 5px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  vertical-align: super;
  transition: all 0.12s;
}

.cite-badge.on:hover {
  background: var(--primary);
  color: #fff;
}

.answer-error {
  margin-top: 8px;
  padding: 10px 14px;
  background: var(--danger-soft);
  color: var(--danger);
  border-radius: var(--radius-sm);
  font-size: 13px;
}

/* ---------------- 引用卡片 ---------------- */
.citations {
  margin-top: 14px;
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}

.citations-head {
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 8px;
}

.cite-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--surface-2);
  transition: border-color 0.2s, box-shadow 0.2s, opacity 0.2s;
}

.cite-card.dim {
  opacity: 0.55;
}

.cite-card.hl {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(26, 86, 219, 0.18);
  background: var(--primary-soft);
}

.cite-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.cite-idx {
  color: var(--primary);
  font-weight: 700;
  font-size: 12px;
  flex-shrink: 0;
}

.cite-doc {
  font-weight: 600;
  font-size: 13px;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cite-article {
  font-size: 12px;
  color: var(--primary);
  background: var(--primary-soft);
  padding: 1px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}

.cite-snippet {
  font-size: 12.5px;
  color: var(--text-2);
  line-height: 1.6;
}

.cite-foot {
  display: flex;
  gap: 12px;
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--text-3);
  flex-wrap: wrap;
}

.cite-page {
  color: var(--primary);
  cursor: pointer;
  text-decoration: none;
}

.cite-page:hover {
  text-decoration: underline;
}

/* ---------------- 指标行 ---------------- */
.metrics {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  flex-wrap: wrap;
}

.metric-item {
  font-size: 12px;
  color: var(--text-3);
}

/* ---------------- 输入区 ---------------- */
.composer {
  border-top: 1px solid var(--border);
  background: var(--surface);
  padding: 12px 8% 16px;
}

.composer-settings {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.kb-picker {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.picker-label {
  font-size: 12px;
  color: var(--text-3);
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.picker-empty {
  font-size: 12px;
  color: var(--text-3);
}

.kb-chip {
  border: 1px solid var(--border-strong);
  background: var(--surface);
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 12px;
  color: var(--text-2);
  cursor: pointer;
  transition: all 0.15s;
}

.kb-chip.on {
  background: var(--primary-soft);
  border-color: var(--primary);
  color: var(--primary);
  font-weight: 500;
}

.settings-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.mini-select {
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  padding: 3px 6px;
  font-size: 12px;
  color: var(--text-2);
  background: var(--surface);
}

.checkbox {
  cursor: pointer;
  user-select: none;
}

.composer-input {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}

.composer-input .textarea {
  flex: 1;
  line-height: 1.6;
}

.send-btn {
  height: 58px;
  min-width: 84px;
  font-size: 15px;
}

.stop-btn {
  height: 58px;
  min-width: 84px;
  background: var(--surface);
  color: var(--danger);
  border-color: #fca5a5;
}

.stop-btn:hover {
  background: var(--danger-soft);
}

.stop-icon {
  width: 10px;
  height: 10px;
  background: var(--danger);
  border-radius: 2px;
}

/* ---------------- 建议词 ---------------- */
.suggestions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.sug-label {
  font-size: 12px;
  color: var(--text-3);
}

.sug-chip {
  border: 1px dashed var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
  border-radius: 999px;
  padding: 3px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.sug-chip:hover {
  background: var(--primary);
  color: #fff;
}

/* ---------------- 反馈与收藏 ---------------- */
.msg-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
}

.act-btn {
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 14px;
  color: var(--text-3);
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1.4;
}

.act-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.act-btn.on {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary);
}

.act-tip {
  font-size: 12px;
  color: var(--text-3);
}

/* ---------------- 反馈弹窗 ---------------- */
.feedback-modal {
  width: 440px;
}

.feedback-modal h3 {
  margin: 0;
  font-size: 16px;
}

.form-label {
  display: block;
  font-size: 13px;
  color: var(--text-2);
  margin: 14px 0 6px;
}

.form-label:first-child {
  margin-top: 0;
}
</style>
