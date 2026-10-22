<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Promotion, Star, StarFilled, VideoPause } from '@element-plus/icons-vue'
import { qaApi, documentApi, feedbackApi, favoriteApi } from '../api'
import { streamAsk } from '../api/sse'
import { useKbStore } from '../stores/kb'
import type {
  Citation,
  FeedbackReason,
  QaDoneEvent,
  QaMetaEvent,
  RetrieveMode,
  SessionSummary,
} from '../types'

const kbStore = useKbStore()
const route = useRoute()
const router = useRouter()

// ---------------------------------------------------------------- 类型
/** 消息视图模型：会话消息叠加本地流式/反馈状态；后端字段不确定处保持宽松 */
interface ChatItem {
  id: number | string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  done: QaDoneEvent | null
  error: string | null
  streaming: boolean
  retrieved?: boolean
  favorited?: boolean
  feedbackRating?: number | null
  createdAt?: string
  startedAt?: number
}

interface ContentSeg {
  badge?: number
  text?: string
}

// ---------------------------------------------------------------- 状态
const sessions = ref<SessionSummary[]>([])
const currentSessionNo = ref<string | null>(null)
const messages = ref<ChatItem[]>([])
const question = ref('')
const sending = ref(false)
const loadingSession = ref(false)
const sessionsLoading = ref(false)

const settings = reactive({
  kbIds: [] as number[],
  mode: 'hybrid' as RetrieveMode,
  topK: 5,
  useHistory: true,
})

let controller: AbortController | null = null
const messagesEl = ref<HTMLElement | null>(null)
const highlightCitation = ref<{ msgId: number | string; index: number } | null>(null)

// 右侧证据面板（docs/07 §4.1）：宽 380px，可折叠
const evidenceOpen = ref(true)
const evidenceMsgId = ref<number | string | null>(null)
const evidenceMsg = computed<ChatItem | null>(() => {
  const own = messages.value.find((m) => m.id === evidenceMsgId.value && m.citations?.length)
  if (own) return own
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    const m = messages.value[i]
    if (m.role === 'assistant' && m.citations?.length) return m
  }
  return null
})

const EXAMPLES: string[] = [
  '商业银行资本管理办法中核心一级资本充足率的最低要求是多少？',
  '流动性覆盖率的监管标准是什么？',
  '理财产品的销售新规有哪些要点？',
]

const TIMELINESS_MAP: Record<string, { label: string; type: 'success' | 'warning' | 'info' | 'danger' }> = {
  effective: { label: '现行有效', type: 'success' },
  amended: { label: '已修订', type: 'warning' },
  unknown: { label: '时效未知', type: 'info' },
  repealed: { label: '已废止', type: 'danger' },
}

const CONF_MAP: Record<string, { label: string; type: 'success' | 'warning' | 'info' | 'danger' }> = {
  high: { label: '可信度高', type: 'success' },
  medium: { label: '可信度中', type: 'warning' },
  low: { label: '可信度低', type: 'danger' },
}

// ---------------------------------------------------------------- 工具
function scrollBottom() {
  nextTick(() => {
    const el = messagesEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function parseContent(content: string | null | undefined): ContentSeg[] {
  // [n] 角标 → 可点击标记；越界角标后端已过滤，但渲染层只点亮存在的引用
  return String(content || '')
    .split(/(\[\d{1,2}\])/g)
    .map((seg) => {
      const m = seg.match(/^\[(\d{1,2})\]$/)
      return m ? { badge: Number(m[1]) } : { text: seg }
    })
}

function onBadgeClick(msg: ChatItem, n: number) {
  evidenceOpen.value = true
  evidenceMsgId.value = msg.id
  highlightCitation.value = null
  nextTick(() => {
    highlightCitation.value = { msgId: msg.id, index: n }
    const card = document.getElementById(`cite-${msg.id}-${n}`)
    card?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
}

function onEvidenceClick(c: any) {
  const msg = evidenceMsg.value
  if (!msg) return
  onBadgeClick(msg, c.cite_index)
}

function citationDoc(meta: any): string {
  if (meta.knowledge_point_id) return `知识点 KP-${meta.knowledge_point_id}`
  return meta.doc_title || '未知文档'
}

async function downloadCitation(c: any) {
  if (!c.document_id) return
  try {
    await documentApi.download(c.document_id, `${c.doc_title || 'document'}.pdf`)
  } catch (e: any) {
    ElMessage.error(e?.message || '下载失败')
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
  evidenceMsgId.value = null
  if (route.name === 'chat-session') router.replace({ name: 'chat' })
}

async function openSession(s: SessionSummary) {
  if (sending.value || s.session_no === currentSessionNo.value) return
  await loadSessionNo(s.session_no)
}

/** 会话回看（/chat/:sessionNo 直达或侧栏点击共用） */
async function loadSessionNo(sessionNo: string) {
  loadingSession.value = true
  try {
    const data = await qaApi.sessionDetail(sessionNo)
    currentSessionNo.value = sessionNo
    messages.value = ((data.messages || data.items || []) as any[]).map((m): ChatItem => ({
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
      feedbackRating: m.feedback?.rating ?? null,
      createdAt: m.created_at,
    }))
    const lastAssistant = [...messages.value].reverse().find((m) => m.role === 'assistant')
    evidenceMsgId.value = lastAssistant?.id ?? null
    scrollBottom()
  } catch (e: any) {
    ElMessage.error(e?.message || '加载会话失败')
  } finally {
    loadingSession.value = false
  }
}

function syncSessionRoute() {
  if (!currentSessionNo.value) return
  if (currentSessionNo.value === route.params.sessionNo) return
  router.replace({ name: 'chat-session', params: { sessionNo: currentSessionNo.value } })
}

async function removeSession(s: SessionSummary) {
  const ok = await ElMessageBox
    .confirm(`删除会话「${s.title || s.session_no}」？`, '提示', { type: 'warning' })
    .then(() => true)
    .catch(() => false)
  if (!ok) return
  try {
    await qaApi.deleteSession(s.session_no)
    if (s.session_no === currentSessionNo.value) newChat()
    await loadSessions()
  } catch (e: any) {
    ElMessage.error(e?.message || '删除失败')
  }
}

// ---------------------------------------------------------------- 问答
function newPlaceholder(): ChatItem {
  const id = `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const msg = reactive<ChatItem>({
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

async function send(text?: string) {
  const q = (text ?? question.value).trim()
  if (!q || sending.value) return
  if (q.length > 500) {
    ElMessage.warning('问题最多 500 字')
    return
  }

  question.value = ''
  messages.value.push({ id: `u-${Date.now()}`, role: 'user', content: q, citations: [], done: null, error: null, streaming: false })
  const assistant = newPlaceholder()
  sending.value = true
  const ctrl = new AbortController()
  controller = ctrl

  await streamAsk(
    {
      question: q,
      session_no: currentSessionNo.value || undefined,
      kb_ids: settings.kbIds.length ? settings.kbIds : undefined,
      mode: settings.mode,
      top_k: settings.topK,
      use_history: settings.useHistory,
    },
    {
      onMeta(data: QaMetaEvent) {
        assistant.retrieved = true
        assistant.citations = data.citations || []
        if (data.message_id) assistant.id = data.message_id
        if (data.session_no) currentSessionNo.value = data.session_no
        evidenceMsgId.value = assistant.id
        scrollBottom()
      },
      onToken(delta: string) {
        assistant.content += delta
        scrollBottom()
      },
      onDone(data: QaDoneEvent) {
        assistant.done = data
        assistant.streaming = false
        sending.value = false
        controller = null
        syncSessionRoute()
        loadSessions()
      },
      onError(e: any) {
        assistant.error = e?.message || '生成失败'
        assistant.streaming = false
        sending.value = false
        controller = null
      },
    },
    ctrl,
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

function onKeydown(e: KeyboardEvent) {
  if (e.isComposing) return
  if (e.key === 'Enter' && (e.ctrlKey || !e.shiftKey)) {
    e.preventDefault()
    send()
  }
}

// ---------------------------------------------------------------- 反馈与收藏
const feedbackDlg = ref(false)
const feedbackTarget = ref<ChatItem | null>(null)
const feedbackForm = reactive<{ reason: FeedbackReason | ''; comment: string }>({ reason: '', comment: '' })
const FEEDBACK_REASONS: { value: FeedbackReason; label: string }[] = [
  { value: 'inaccurate', label: '答案不准确' },
  { value: 'incomplete', label: '答案不完整' },
  { value: 'outdated', label: '条文过时' },
  { value: 'wrong_citation', label: '引用错误' },
  { value: 'other', label: '其他' },
]

async function submitFeedback(msg: ChatItem, rating: number) {
  try {
    await feedbackApi.submit(msg.id, { rating })
    msg.feedbackRating = rating
  } catch (e: any) {
    ElMessage.error(e?.message || '反馈失败')
  }
}

function openFeedbackDlg(msg: ChatItem) {
  feedbackTarget.value = msg
  feedbackForm.reason = ''
  feedbackForm.comment = ''
  feedbackDlg.value = true
}

async function submitNegativeFeedback() {
  const msg = feedbackTarget.value
  if (!msg) return
  try {
    await feedbackApi.submit(msg.id, {
      rating: -1,
      reason: feedbackForm.reason || undefined,
      comment: feedbackForm.comment || undefined,
    })
    msg.feedbackRating = -1
    feedbackDlg.value = false
  } catch (e: any) {
    ElMessage.error(e?.message || '反馈失败')
  }
}

async function toggleFavorite(msg: ChatItem) {
  try {
    if (msg.favorited) {
      await favoriteApi.remove(msg.id)
      msg.favorited = false
    } else {
      await favoriteApi.add(msg.id)
      msg.favorited = true
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '操作失败')
  }
}

onMounted(() => {
  loadSessions()
  kbStore.ensureLoaded()
  if (route.params.sessionNo) loadSessionNo(route.params.sessionNo as string)
})
</script>

<template>
  <div class="chat-page">
    <!-- ============ 会话侧栏 ============ -->
    <aside class="session-panel">
      <el-button type="primary" class="new-chat" @click="newChat">＋ 新对话</el-button>
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
          <el-button
            class="session-del"
            link
            type="danger"
            size="small"
            title="删除会话"
            @click.stop="removeSession(s)"
          >✕</el-button>
        </div>
      </div>
    </aside>

    <!-- ============ 主对话区 ============ -->
    <section class="chat-main">
      <el-button
        size="small"
        round
        class="evidence-toggle"
        @click="evidenceOpen = !evidenceOpen"
      >
        {{ evidenceOpen ? '证据 »' : '« 证据' }}
      </el-button>
      <div ref="messagesEl" class="messages">
        <!-- 空状态 -->
        <div v-if="!messages.length" class="welcome">
          <div class="welcome-logo">LF</div>
          <h2>金融制度知识问答</h2>
          <p>基于混合检索与角标溯源，每条答案均可回溯至具体条文与页码</p>
          <div class="examples">
            <el-button v-for="ex in EXAMPLES" :key="ex" class="example-card" @click="send(ex)">
              {{ ex }}
            </el-button>
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
                    <el-tag
                      v-if="c.timeliness"
                      size="small"
                      :type="TIMELINESS_MAP[c.timeliness]?.type || 'info'"
                    >{{ TIMELINESS_MAP[c.timeliness]?.label || c.timeliness }}</el-tag>
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
                <el-tag
                  v-if="msg.done.confidence_level"
                  size="small"
                  :type="CONF_MAP[msg.done.confidence_level]?.type || 'info'"
                >{{ CONF_MAP[msg.done.confidence_level]?.label }} {{ ((msg.done.confidence ?? 0) * 100).toFixed(0) }}分</el-tag>
                <el-tag
                  v-if="msg.done.answer_type === 'refused'"
                  size="small"
                  type="warning"
                >知识库未命中，已拒答</el-tag>
                <span v-if="msg.done.latency_ms != null" class="metric-item">耗时 {{ (msg.done.latency_ms / 1000).toFixed(1) }}s</span>
                <span v-if="msg.done.latency_detail?.retrieve != null" class="metric-item">检索 {{ msg.done.latency_detail.retrieve }}ms</span>
                <span v-if="msg.done.model_name" class="metric-item">{{ msg.done.model_name }}</span>
              </div>

              <!-- 拒答建议检索词 -->
              <div v-if="msg.done?.suggestions?.length" class="suggestions">
                <span class="sug-label">建议尝试：</span>
                <el-button
                  v-for="s in msg.done.suggestions"
                  :key="s"
                  size="small"
                  round
                  class="sug-chip"
                  @click="send(s)"
                >{{ s }}</el-button>
              </div>

              <!-- 反馈与收藏（仅真实消息 id，本地占位 id 不展示） -->
              <div v-if="msg.done && !msg.streaming && typeof msg.id === 'number'" class="msg-actions">
                <el-button
                  size="small"
                  :type="msg.feedbackRating === 1 ? 'primary' : 'default'"
                  title="点赞"
                  @click="submitFeedback(msg, 1)"
                >👍</el-button>
                <el-button
                  size="small"
                  :type="msg.feedbackRating === -1 ? 'primary' : 'default'"
                  title="点踩/纠错"
                  @click="openFeedbackDlg(msg)"
                >👎</el-button>
                <el-button
                  size="small"
                  :type="msg.favorited ? 'warning' : 'default'"
                  :icon="msg.favorited ? StarFilled : Star"
                  title="收藏答案"
                  @click="toggleFavorite(msg)"
                />
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
            <el-select
              v-model="settings.kbIds"
              class="kb-select"
              multiple
              clearable
              :multiple-limit="5"
              placeholder="选择知识库（最多 5 个）"
            >
              <el-option
                v-for="kb in kbStore.list"
                :key="kb.id"
                :label="kb.name"
                :value="kb.id"
                :title="kb.description || kb.name"
              />
            </el-select>
            <span v-if="!kbStore.list.length" class="picker-empty">未加载到知识库</span>
          </div>
          <div class="settings-right">
            <label class="picker-label">
              检索
              <el-select v-model="settings.mode" class="mini-select">
                <el-option label="混合" value="hybrid" />
                <el-option label="向量" value="vector" />
                <el-option label="关键词" value="keyword" />
              </el-select>
            </label>
            <label class="picker-label">
              引用数
              <el-select v-model="settings.topK" class="mini-select">
                <el-option v-for="n in [3, 5, 8, 10]" :key="n" :label="String(n)" :value="n" />
              </el-select>
            </label>
            <el-checkbox v-model="settings.useHistory">多轮</el-checkbox>
          </div>
        </div>

        <div class="composer-input">
          <el-input
            v-model="question"
            type="textarea"
            class="composer-textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            :maxlength="500"
            show-word-limit
            placeholder="输入金融制度相关问题，Enter / Ctrl+Enter 发送，Shift+Enter 换行（最多 500 字）"
            :disabled="sending"
            @keydown="onKeydown"
          />
          <el-button v-if="sending" class="stop-btn" :icon="VideoPause" @click="stopStream">
            停止
          </el-button>
          <el-button v-else type="primary" class="send-btn" :icon="Promotion" :disabled="!question.trim()" @click="send()">
            发送
          </el-button>
        </div>
      </div>
    </section>

    <!-- ============ 右侧证据面板 ============ -->
    <aside v-if="evidenceOpen" class="evidence-panel">
      <div class="evidence-head">
        <span>本次回答参考条文</span>
        <el-tag size="small" type="info">{{ evidenceMsg?.citations?.length || 0 }}</el-tag>
      </div>
      <div v-if="!evidenceMsg" class="empty-tip" style="padding: 24px 0">提问后将在此展示检索到的条文</div>
      <div v-else class="evidence-list">
        <div
          v-for="c in evidenceMsg.citations"
          :key="c.cite_index"
          class="cite-card evidence-card"
          :class="{
            hl: highlightCitation && highlightCitation.msgId === evidenceMsg.id && highlightCitation.index === c.cite_index,
            dim: evidenceMsg.done?.used_citations && !evidenceMsg.done.used_citations.includes(c.cite_index),
          }"
          @click="onEvidenceClick(c)"
        >
          <div class="cite-top">
            <span class="cite-idx">[{{ c.cite_index }}]</span>
            <span class="cite-doc" :title="c.doc_title">{{ citationDoc(c) }}</span>
            <el-tag
              v-if="evidenceMsg.done?.used_citations?.includes(c.cite_index)"
              size="small"
              type="success"
            >已采用</el-tag>
          </div>
          <div v-if="c.article_no" class="evidence-article">{{ c.article_no }}</div>
          <div class="cite-snippet">{{ c.snippet }}</div>
          <div class="cite-foot">
            <span v-if="c.page_no != null">第 {{ c.page_no }} 页</span>
            <span v-if="c.timeliness">{{ TIMELINESS_MAP[c.timeliness]?.label || c.timeliness }}</span>
            <a v-if="c.page_no != null" class="cite-page" href="javascript:;" @click.stop="downloadCitation(c)">
              下载原文
            </a>
          </div>
        </div>
      </div>
    </aside>

    <!-- ============ 点踩反馈弹窗 ============ -->
    <el-dialog v-model="feedbackDlg" title="答案纠错反馈" width="440px">
      <div class="form-label">问题类型</div>
      <el-select v-model="feedbackForm.reason" class="dialog-select" clearable placeholder="请选择（可不选）">
        <el-option v-for="r in FEEDBACK_REASONS" :key="r.value" :label="r.label" :value="r.value" />
      </el-select>
      <div class="form-label">补充说明</div>
      <el-input
        v-model="feedbackForm.comment"
        type="textarea"
        :rows="4"
        placeholder="请描述答案存在的问题，帮助改进检索与生成质量（可选）"
      />
      <template #footer>
        <el-button @click="feedbackDlg = false">取消</el-button>
        <el-button type="primary" @click="submitNegativeFeedback">提交反馈</el-button>
      </template>
    </el-dialog>
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
  opacity: 0;
  transition: opacity 0.15s;
}

.session-item:hover .session-del {
  opacity: 1;
}

/* ---------------- 消息区 ---------------- */
.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  position: relative;
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
  width: 100%;
  justify-content: flex-start;
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

.kb-picker .el-select {
  max-width: 320px;
}

.settings-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.mini-select {
  width: 88px;
}

.composer-input {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}

.composer-input :deep(.el-textarea) {
  flex: 1;
}

.send-btn {
  height: 58px;
  min-width: 84px;
  font-size: 15px;
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

/* ---------------- 反馈与收藏 ---------------- */
.msg-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
}

.act-tip {
  font-size: 12px;
  color: var(--text-3);
}

/* el-button 相邻间距与 flex gap 叠加，重置 */
.examples .el-button + .el-button,
.suggestions .el-button + .el-button,
.msg-actions .el-button + .el-button {
  margin-left: 0;
}

/* ---------------- 反馈弹窗 ---------------- */
.form-label {
  display: block;
  font-size: 13px;
  color: var(--text-2);
  margin: 14px 0 6px;
}

.form-label:first-child {
  margin-top: 0;
}

.dialog-select {
  width: 100%;
}

/* ---------------- 右侧证据面板 ---------------- */
.evidence-toggle {
  position: absolute;
  top: 10px;
  right: 12px;
  z-index: 5;
}

.evidence-panel {
  width: 380px;
  flex-shrink: 0;
  border-left: 1px solid var(--border);
  background: var(--surface-2);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.evidence-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 14px 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  border-bottom: 1px solid var(--border);
}

.evidence-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.evidence-card {
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.evidence-card:hover {
  border-color: var(--primary);
}

.evidence-card.hl {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-soft);
}

.evidence-card.dim {
  opacity: 0.55;
}

.evidence-article {
  font-size: 12px;
  color: var(--primary);
  margin-bottom: 4px;
}
</style>
