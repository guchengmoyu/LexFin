/**
 * 后端接口封装（契约见 docs/06-后端接口设计.md，与 apifox/FinRAG-collection.json 一一对应）。
 */
import { request, uploadMultipart, downloadFile } from './http'

const PREFIX = '/api/v1'

// ---------------------------------------------------------------- 认证
export const authApi = {
  login: (username, password) =>
    request(`${PREFIX}/auth/login`, { method: 'POST', body: { username, password } }),
  register: (payload) => request(`${PREFIX}/auth/register`, { method: 'POST', body: payload }),
  me: () => request(`${PREFIX}/auth/me`),
  logout: () => request(`${PREFIX}/auth/logout`, { method: 'POST' }),
}

// ---------------------------------------------------------------- 知识库
export const kbApi = {
  list: () => request(`${PREFIX}/kb`),
  detail: (kbId) => request(`${PREFIX}/kb/${kbId}`),
  stats: (kbId) => request(`${PREFIX}/kb/${kbId}/stats`),
}

// ---------------------------------------------------------------- 文档
export const documentApi = {
  list: (params) => {
    const qs = new URLSearchParams()
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return request(`${PREFIX}/documents?${qs.toString()}`)
  },
  detail: (docId) => request(`${PREFIX}/documents/${docId}`),
  update: (docId, payload) =>
    request(`${PREFIX}/documents/${docId}`, { method: 'PUT', body: payload }),
  remove: (docId, hard = false) =>
    request(`${PREFIX}/documents/${docId}?hard=${hard}`, { method: 'DELETE' }),
  reparse: (docId) => request(`${PREFIX}/documents/${docId}/reparse`, { method: 'POST' }),
  chunks: (docId, page = 1, size = 20) =>
    request(`${PREFIX}/documents/${docId}/chunks?page=${page}&size=${size}`),
  download: (docId, name) => downloadFile(`${PREFIX}/documents/${docId}/download`, name),
  upload: (formData) => uploadMultipart(`${PREFIX}/documents/upload`, formData),
}

// ---------------------------------------------------------------- 入库任务
export const taskApi = {
  detail: (taskNo) => request(`${PREFIX}/tasks/${taskNo}`),
  list: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return request(`${PREFIX}/tasks?${qs.toString()}`)
  },
}

// ---------------------------------------------------------------- 问答与会话
export const qaApi = {
  ask: (payload) => request(`${PREFIX}/qa/ask`, { method: 'POST', body: payload }),
  sessions: (page = 1, size = 50) => request(`${PREFIX}/qa/sessions?page=${page}&size=${size}`),
  sessionDetail: (sessionNo) => request(`${PREFIX}/qa/sessions/${sessionNo}`),
  deleteSession: (sessionNo) => request(`${PREFIX}/qa/sessions/${sessionNo}`, { method: 'DELETE' }),
  messageDetail: (messageId) => request(`${PREFIX}/qa/messages/${messageId}`),
}

// ---------------------------------------------------------------- 检索（docs/06 §5.7）
export const retrieveApi = {
  retrieve: (payload) => request(`${PREFIX}/retrieve`, { method: 'POST', body: payload }),
  search: (params) => {
    const qs = new URLSearchParams()
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return request(`${PREFIX}/search?${qs.toString()}`)
  },
}

// ---------------------------------------------------------------- 知识点（docs/06 §5.6）
export const kpApi = {
  list: (params) => {
    const qs = new URLSearchParams()
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return request(`${PREFIX}/knowledge-points?${qs.toString()}`)
  },
  create: (payload) => request(`${PREFIX}/knowledge-points`, { method: 'POST', body: payload }),
  detail: (id) => request(`${PREFIX}/knowledge-points/${id}`),
  update: (id, payload) => request(`${PREFIX}/knowledge-points/${id}`, { method: 'PUT', body: payload }),
  remove: (id) => request(`${PREFIX}/knowledge-points/${id}`, { method: 'DELETE' }),
  verify: (id, payload) => request(`${PREFIX}/knowledge-points/${id}/verify`, { method: 'POST', body: payload }),
  stats: () => request(`${PREFIX}/knowledge-points/stats`),
  related: (id) => request(`${PREFIX}/knowledge-points/${id}/related`),
  sources: (id) => request(`${PREFIX}/knowledge-points/${id}/sources`),
  importFile: (formData) => uploadMultipart(`${PREFIX}/knowledge-points/import`, formData),
  exportCsv: (kbId) =>
    downloadFile(`${PREFIX}/knowledge-points/export${kbId ? `?kb_id=${kbId}` : ''}`, 'knowledge_points.csv'),
}

// ---------------------------------------------------------------- 收藏（docs/06 §5.10）
export const favoriteApi = {
  list: (page = 1, size = 20) => request(`${PREFIX}/favorites?page=${page}&size=${size}`),
  add: (messageId, note) => request(`${PREFIX}/favorites`, { method: 'POST', body: { message_id: messageId, note } }),
  remove: (messageId) => request(`${PREFIX}/favorites/${messageId}`, { method: 'DELETE' }),
}

// ---------------------------------------------------------------- 反馈与人工校验（docs/06 §5.11）
export const feedbackApi = {
  submit: (messageId, payload) =>
    request(`${PREFIX}/qa/messages/${messageId}/feedback`, { method: 'POST', body: payload }),
  list: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return request(`${PREFIX}/qa/feedback?${qs.toString()}`)
  },
  review: (payload) => request(`${PREFIX}/qa/reviews`, { method: 'POST', body: payload }),
  reviewStats: (batchNo, targetType = 'answer') =>
    request(`${PREFIX}/qa/reviews/stats?batch_no=${encodeURIComponent(batchNo)}&target_type=${targetType}`),
}
