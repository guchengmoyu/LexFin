<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Star, StarFilled } from '@element-plus/icons-vue'
import { qaApi, feedbackApi, favoriteApi } from '../api'

/**
 * 意见反馈（用户侧入口）：
 * 1) 反馈指引；2) 从我的最近问答中直接对答案点赞 / 点踩（与问答页同一接口）。
 */
interface AnswerItem {
  messageId: number
  sessionNo: string
  question: string
  answer: string
  createdAt?: string
  feedbackRating: number | null
  favorited: boolean
}

const loading = ref(false)
const items = ref<AnswerItem[]>([])

const REASONS: Record<string, string> = {
  inaccurate: '答案不准确',
  incomplete: '答案不完整',
  outdated: '条文过时',
  wrong_citation: '引用错误',
  other: '其他',
}

async function load() {
  loading.value = true
  try {
    const data: any = await qaApi.sessions(1, 5)
    const sessions: any[] = data.items || []
    const details = await Promise.allSettled(
      sessions.map((s) => qaApi.sessionDetail(s.session_no)),
    )
    const out: AnswerItem[] = []
    details.forEach((d, i) => {
      if (d.status !== 'fulfilled') return
      const msgs: any[] = (d.value as any).messages || (d.value as any).items || []
      let lastQuestion = ''
      msgs.forEach((m) => {
        if (m.role === 'user') {
          lastQuestion = m.content || ''
        } else if (m.role === 'assistant' && m.message_id) {
          out.push({
            messageId: m.message_id,
            sessionNo: sessions[i].session_no,
            question: lastQuestion,
            answer: (m.content || '').replace(/\s+/g, ' ').slice(0, 160),
            createdAt: m.created_at,
            feedbackRating: m.feedback?.rating ?? null,
            favorited: !!m.favorited,
          })
        }
      })
    })
    items.value = out.slice(0, 12)
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------- 反馈提交（与问答页一致）
const dlg = ref(false)
const target = ref<AnswerItem | null>(null)
const form = reactive<{ reason: string; comment: string }>({ reason: '', comment: '' })

async function like(it: AnswerItem) {
  if (it.feedbackRating === 1) return
  try {
    await feedbackApi.submit(it.messageId, { rating: 1 })
    it.feedbackRating = 1
    ElMessage.success('已点赞，感谢反馈')
  } catch (e: any) {
    ElMessage.error(e?.message || '反馈失败')
  }
}

function openDislike(it: AnswerItem) {
  target.value = it
  form.reason = ''
  form.comment = ''
  dlg.value = true
}

async function submitDislike() {
  const it = target.value
  if (!it) return
  try {
    await feedbackApi.submit(it.messageId, {
      rating: -1,
      reason: form.reason || undefined,
      comment: form.comment || undefined,
    })
    it.feedbackRating = -1
    dlg.value = false
    ElMessage.success('反馈已提交，我们会持续改进')
  } catch (e: any) {
    ElMessage.error(e?.message || '反馈失败')
  }
}

async function toggleFavorite(it: AnswerItem) {
  try {
    if (it.favorited) {
      await favoriteApi.remove(it.messageId)
      it.favorited = false
    } else {
      await favoriteApi.add(it.messageId)
      it.favorited = true
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '操作失败')
  }
}

onMounted(load)
</script>

<template>
  <section class="doc-page">
    <div class="doc-header">
      <div>
        <h1>意见反馈</h1>
        <p>对答案质量点赞 / 点踩，反馈将用于统计准确率与迭代优化</p>
      </div>
      <el-button @click="load">刷新</el-button>
    </div>

    <div class="panel guide-panel">
      <div class="guide-step">
        <div class="guide-num">1</div>
        <div>
          <div class="guide-title">在「智能问答」中提问</div>
          <div class="guide-desc">系统基于制度知识库生成带引用出处的答案</div>
        </div>
      </div>
      <div class="guide-step">
        <div class="guide-num">2</div>
        <div>
          <div class="guide-title">对答案点赞 / 点踩</div>
          <div class="guide-desc">答案下方有点赞、点踩与收藏按钮；也可在本页快捷操作</div>
        </div>
      </div>
      <div class="guide-step">
        <div class="guide-num">3</div>
        <div>
          <div class="guide-title">填写原因并提交</div>
          <div class="guide-desc">点踩可选择原因并补充说明，帮助定位问题</div>
        </div>
      </div>
    </div>

    <h3 class="panel-title" style="margin: 18px 0 10px">我的最近问答 · 快捷反馈</h3>

    <div v-if="loading" class="empty-state">加载中…</div>
    <el-empty v-else-if="!items.length" description="暂无问答记录，先去「智能问答」提问吧" />

    <div v-else class="fb-list">
      <div v-for="it in items" :key="it.messageId" class="panel fb-card">
        <div class="fb-q">{{ it.question || '（未命名问题）' }}</div>
        <div class="fb-a">{{ it.answer }}…</div>
        <div class="fb-foot">
          <span class="fb-time">{{ it.createdAt || '' }}</span>
          <span class="spacer"></span>
          <span v-if="it.feedbackRating === 1" class="done-tip">已点赞</span>
          <span v-else-if="it.feedbackRating === -1" class="done-tip">已反馈</span>
          <el-button
            size="small"
            :type="it.feedbackRating === 1 ? 'primary' : 'default'"
            :disabled="it.feedbackRating != null"
            @click="like(it)"
          >👍 点赞</el-button>
          <el-button
            size="small"
            :type="it.feedbackRating === -1 ? 'primary' : 'default'"
            :disabled="it.feedbackRating != null"
            @click="openDislike(it)"
          >👎 点踩</el-button>
          <el-button
            size="small"
            :type="it.favorited ? 'warning' : 'default'"
            :icon="it.favorited ? StarFilled : Star"
            @click="toggleFavorite(it)"
          >{{ it.favorited ? '已收藏' : '收藏' }}</el-button>
        </div>
      </div>
    </div>

    <el-dialog v-model="dlg" title="点踩反馈" width="480px">
      <label class="form-label">问题原因</label>
      <el-select v-model="form.reason" style="width: 100%" placeholder="请选择（可选）">
        <el-option v-for="(label, k) in REASONS" :key="k" :value="k" :label="label" />
      </el-select>
      <label class="form-label">补充说明</label>
      <el-input v-model="form.comment" type="textarea" :rows="4" placeholder="可选，说明答案哪里有问题" />
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" @click="submitDislike">提交反馈</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.guide-panel {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}

.guide-step {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  flex: 1;
  min-width: 220px;
}

.guide-num {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.guide-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-1);
}

.guide-desc {
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
}

.fb-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 900px;
}

.fb-q {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-1);
}

.fb-a {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--text-2);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.fb-foot {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.fb-time {
  font-size: 11.5px;
  color: var(--text-3);
}

.spacer {
  flex: 1;
}

.done-tip {
  font-size: 12px;
  color: var(--text-3);
}

.form-label {
  display: block;
  font-size: 13px;
  color: var(--text-2);
  margin: 12px 0 6px;
}

.form-label:first-child {
  margin-top: 0;
}
</style>
