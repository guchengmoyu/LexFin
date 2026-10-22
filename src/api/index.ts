/**
 * 后端接口封装（契约见 docs/06-后端接口设计.md，与 apifox/FinRAG-collection.json 一一对应）。
 */
import { request, uploadMultipart, downloadFile } from './http'
import type {
  LoginResult,
  RegisterPayload,
  UserInfo,
  KbInfo,
  DocItem,
  TaskItem,
  KnowledgePoint,
  KpSource,
  QaAskPayload,
} from '../types'

const PREFIX = '/api/v1'

/** 拼接查询串（跳过 undefined/null/''） */
function buildQuery(base: string, params?: Record<string, any>): string {
  if (!params) return base
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  })
  const s = qs.toString()
  return s ? `${base}?${s}` : base
}

// ---------------------------------------------------------------- 认证
export const authApi = {
  login: (username: string, password: string) =>
    request<LoginResult>(`${PREFIX}/auth/login`, { method: 'POST', body: { username, password } }),
  register: (payload: RegisterPayload) =>
    request(`${PREFIX}/auth/register`, { method: 'POST', body: payload }),
  me: () => request<UserInfo>(`${PREFIX}/auth/me`),
  logout: () => request(`${PREFIX}/auth/logout`, { method: 'POST' }),
}

// ---------------------------------------------------------------- 系统与统计（docs/06 §5.2）
export const systemApi = {
  config: () => request<Record<string, any>>(`${PREFIX}/system/config`),
}

export const statsApi = {
  overview: () => request<Record<string, any>>(`${PREFIX}/stats/overview`),
}

// ---------------------------------------------------------------- 知识库
export const kbApi = {
  list: () => request<KbInfo[]>(`${PREFIX}/kb`),
  detail: (kbId: number | string) => request<KbInfo>(`${PREFIX}/kb/${kbId}`),
  stats: (kbId: number | string) => request<Record<string, any>>(`${PREFIX}/kb/${kbId}/stats`),
  create: (payload: Partial<KbInfo>) => request(`${PREFIX}/kb`, { method: 'POST', body: payload }),
  update: (kbId: number | string, payload: Partial<KbInfo>) =>
    request(`${PREFIX}/kb/${kbId}`, { method: 'PUT', body: payload }),
  remove: (kbId: number | string) => request(`${PREFIX}/kb/${kbId}`, { method: 'DELETE' }),
}

// ---------------------------------------------------------------- 文档
export const documentApi = {
  list: (params?: Record<string, any>) => request(buildQuery(`${PREFIX}/documents`, params)),
  detail: (docId: number | string) => request<DocItem>(`${PREFIX}/documents/${docId}`),
  update: (docId: number | string, payload: Partial<DocItem>) =>
    request(`${PREFIX}/documents/${docId}`, { method: 'PUT', body: payload }),
  remove: (docId: number | string, hard = false) =>
    request(`${PREFIX}/documents/${docId}?hard=${hard}`, { method: 'DELETE' }),
  reparse: (docId: number | string) =>
    request(`${PREFIX}/documents/${docId}/reparse`, { method: 'POST' }),
  chunks: (docId: number | string, page = 1, size = 20) =>
    request(`${PREFIX}/documents/${docId}/chunks?page=${page}&size=${size}`),
  download: (docId: number | string, name?: string) =>
    downloadFile(`${PREFIX}/documents/${docId}/download`, name || 'download'),
  upload: (formData: FormData, onUploadProgress?: (e: any) => void) =>
    uploadMultipart(`${PREFIX}/documents/upload`, formData, onUploadProgress),
}

// ---------------------------------------------------------------- 入库任务
export const taskApi = {
  detail: (taskNo: string) => request<TaskItem>(`${PREFIX}/tasks/${taskNo}`),
  list: (params: Record<string, any> = {}) => request(buildQuery(`${PREFIX}/tasks`, params)),
}

// ---------------------------------------------------------------- 问答与会话
export const qaApi = {
  ask: (payload: QaAskPayload) => request(`${PREFIX}/qa/ask`, { method: 'POST', body: payload }),
  sessions: (page = 1, size = 50) => request(`${PREFIX}/qa/sessions?page=${page}&size=${size}`),
  sessionDetail: (sessionNo: string) => request(`${PREFIX}/qa/sessions/${sessionNo}`),
  deleteSession: (sessionNo: string) =>
    request(`${PREFIX}/qa/sessions/${sessionNo}`, { method: 'DELETE' }),
  messageDetail: (messageId: number | string) => request(`${PREFIX}/qa/messages/${messageId}`),
}

// ---------------------------------------------------------------- 检索（docs/06 §5.7）
export const retrieveApi = {
  retrieve: (payload: Record<string, any>) =>
    request(`${PREFIX}/retrieve`, { method: 'POST', body: payload }),
  search: (params: Record<string, any>) => request(buildQuery(`${PREFIX}/search`, params)),
}

// ---------------------------------------------------------------- 知识点（docs/06 §5.6）
export const kpApi = {
  list: (params?: Record<string, any>) =>
    request(buildQuery(`${PREFIX}/knowledge-points`, params)),
  create: (payload: Partial<KnowledgePoint>) =>
    request(`${PREFIX}/knowledge-points`, { method: 'POST', body: payload }),
  detail: (id: number | string) => request<KnowledgePoint>(`${PREFIX}/knowledge-points/${id}`),
  update: (id: number | string, payload: Partial<KnowledgePoint>) =>
    request(`${PREFIX}/knowledge-points/${id}`, { method: 'PUT', body: payload }),
  remove: (id: number | string) =>
    request(`${PREFIX}/knowledge-points/${id}`, { method: 'DELETE' }),
  verify: (id: number | string, payload: Record<string, any>) =>
    request(`${PREFIX}/knowledge-points/${id}/verify`, { method: 'POST', body: payload }),
  stats: () => request(`${PREFIX}/knowledge-points/stats`),
  related: (id: number | string) => request(`${PREFIX}/knowledge-points/${id}/related`),
  sources: (id: number | string) => request<KpSource[]>(`${PREFIX}/knowledge-points/${id}/sources`),
  importFile: (formData: FormData) => uploadMultipart(`${PREFIX}/knowledge-points/import`, formData),
  exportCsv: (kbId?: number | string) =>
    downloadFile(
      `${PREFIX}/knowledge-points/export${kbId ? `?kb_id=${kbId}` : ''}`,
      'knowledge_points.csv',
    ),
}

// ---------------------------------------------------------------- 收藏（docs/06 §5.10）
export const favoriteApi = {
  list: (page = 1, size = 20) => request(`${PREFIX}/favorites?page=${page}&size=${size}`),
  add: (messageId: number | string, note?: string) =>
    request(`${PREFIX}/favorites`, { method: 'POST', body: { message_id: messageId, note } }),
  remove: (messageId: number | string) =>
    request(`${PREFIX}/favorites/${messageId}`, { method: 'DELETE' }),
}

// ---------------------------------------------------------------- 反馈与人工校验（docs/06 §5.11）
export const feedbackApi = {
  submit: (messageId: number | string, payload: Record<string, any>) =>
    request(`${PREFIX}/qa/messages/${messageId}/feedback`, { method: 'POST', body: payload }),
  list: (params: Record<string, any> = {}) => request(buildQuery(`${PREFIX}/qa/feedback`, params)),
  review: (payload: Record<string, any>) =>
    request(`${PREFIX}/qa/reviews`, { method: 'POST', body: payload }),
  reviewStats: (batchNo: string, targetType = 'answer') =>
    request(
      `${PREFIX}/qa/reviews/stats?batch_no=${encodeURIComponent(batchNo)}&target_type=${targetType}`,
    ),
}
