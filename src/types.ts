/**
 * 集中类型定义（契约见 docs/06-后端接口设计.md，与 apifox/FinRAG-collection.json 一一对应）。
 */

// ---------------- 通用 ----------------
export type UserRole = 'admin' | 'editor' | 'viewer'

export interface UserInfo {
  id: number
  username: string
  real_name: string
  role: UserRole
  [key: string]: any
}

export interface LoginResult {
  access_token: string
  token_type: string
  expires_in: number
  user: UserInfo
}

export interface RegisterPayload {
  username: string
  password: string
  real_name: string
  invite_code?: string
  [key: string]: any
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  size: number
}

// ---------------- 知识库 ----------------
export interface KbInfo {
  id: number
  code: string
  name: string
  category?: string
  description?: string | null
  status?: string | number
  document_count?: number
  chunk_count?: number
  kp_count?: number
  created_at?: string
  [key: string]: any
}

// ---------------- 文档 ----------------
export type DocStatus = 'pending' | 'parsing' | 'embedding' | 'ready' | 'error' | 'archived'
export type ParseMode = 'text' | 'ocr' | 'mixed'
export type Timeliness = 'current' | 'revised' | 'repealed'

export interface DocItem {
  id: number
  title: string
  doc_no?: string
  kb_id?: number
  category?: string
  timeliness?: Timeliness
  status: DocStatus
  parse_mode?: ParseMode
  page_count?: number
  chunk_count?: number
  remark?: string
  created_at?: string
  updated_at?: string
  [key: string]: any
}

export interface DocChunk {
  id: number
  doc_id?: number
  seq?: number
  article_no?: string
  page_start?: number
  page_end?: number
  raw_content?: string
  char_count?: number
  [key: string]: any
}

// ---------------- 入库任务 ----------------
export type TaskStatus =
  | 'queued'
  | 'parsing'
  | 'cleaning'
  | 'chunking'
  | 'embedding'
  | 'indexing'
  | 'success'
  | 'failed'

export interface TaskItem {
  task_no: string
  doc_id?: number
  doc_title?: string
  kb_id?: number
  status: TaskStatus
  error_message?: string
  created_at?: string
  updated_at?: string
  [key: string]: any
}

// ---------------- 知识点 ----------------
export type KpStatus = 'draft' | 'published' | 'archived'
export type VerifyStatus = 'unverified' | 'pending' | 'passed' | 'rejected'
export type KpDifficulty = 1 | 2 | 3

export interface KpSource {
  id?: number
  doc_id?: number
  doc_title?: string
  doc_no?: string
  chunk_id?: number
  article_no?: string
  page_start?: number
  page_end?: number
  snippet?: string
  [key: string]: any
}

export interface KnowledgePoint {
  id: number
  code?: string
  title: string
  content: string
  category?: string
  subcategory?: string
  difficulty?: number
  timeliness?: string
  status?: string
  verify_status?: string
  confidence?: number
  kb_id?: number
  keywords?: string[] | string | null
  doc_no?: string | null
  org?: string | null
  article_no?: string | null
  issue_date?: string | null
  sources?: KpSource[]
  updated_at?: string
  [key: string]: any
}

// ---------------- 检索 ----------------
export type RetrieveMode = 'keyword' | 'vector' | 'hybrid'

export interface SearchHit {
  chunk_id?: number
  doc_id?: number
  doc_title?: string
  doc_no?: string
  article_no?: string
  page_start?: number
  page_end?: number
  content?: string
  snippet?: string
  highlight?: string
  timeliness?: Timeliness
  score?: number
  kb_id?: number
  [key: string]: any
}

// ---------------- 问答 ----------------
export interface Citation {
  index?: number
  chunk_id?: number
  doc_id?: number
  doc_title?: string
  doc_no?: string
  article_no?: string
  page_start?: number
  page_end?: number
  snippet?: string
  timeliness?: Timeliness
  score?: number
  kb_id?: number
  [key: string]: any
}

export interface RelatedKp {
  id: number
  title?: string
  category?: string
  [key: string]: any
}

export interface QaAskPayload {
  question: string
  session_no?: string
  kb_ids?: number[]
  mode?: RetrieveMode
  top_k?: number
  use_history?: boolean
}

export interface QaMetaEvent {
  session_no?: string
  message_id?: number
  answer_id?: number
  citations?: Citation[]
  related_kps?: RelatedKp[]
  [key: string]: any
}

export interface QaDoneEvent {
  answer?: string
  used_citations?: number[]
  confidence?: number
  latency_ms?: number
  followup_questions?: string[]
  [key: string]: any
}

export interface ChatMessage {
  id?: number
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  used_citations?: number[]
  related_kps?: RelatedKp[]
  confidence?: number
  latency_ms?: number
  feedback?: string
  favorited?: boolean
  streaming?: boolean
  stopped?: boolean
  error?: boolean
  [key: string]: any
}

export interface SessionSummary {
  session_no: string
  title?: string
  message_count?: number
  created_at?: string
  updated_at?: string
  [key: string]: any
}

// ---------------- 收藏 / 反馈 ----------------
export interface FavoriteItem {
  id?: number
  message_id: number
  question?: string
  answer?: string
  note?: string
  session_no?: string
  created_at?: string
  [key: string]: any
}

export type FeedbackReason = 'inaccurate' | 'incomplete' | 'outdated' | 'wrong_citation' | 'other'
export type FeedbackStatus = 'open' | 'handled' | 'ignored'

export interface FeedbackItem {
  id?: number
  message_id?: number
  type?: 'like' | 'dislike'
  reason?: FeedbackReason
  comment?: string
  status?: FeedbackStatus
  created_at?: string
  [key: string]: any
}
