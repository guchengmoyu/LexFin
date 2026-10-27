/**
 * 统一请求封装：后端响应结构 {code, message, data, request_id}（docs/06 §2）。
 * 成功 code === 0；40101 未认证 → 清除本地态并跳登录。
 */

const TOKEN_KEY = 'lexfin_token'
const USER_KEY = 'lexfin_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token) {
  token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY)
}

export function getSavedUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function setSavedUser(user) {
  user
    ? localStorage.setItem(USER_KEY, JSON.stringify(user))
    : localStorage.removeItem(USER_KEY)
}

export function clearAuth() {
  setToken('')
  setSavedUser(null)
}

export class ApiError extends Error {
  constructor(code, message, requestId) {
    super(message)
    this.code = code
    this.requestId = requestId
  }
}

function handleUnauthorized() {
  clearAuth()
  if (!location.hash.includes('/login')) {
    location.hash = '#/login'
  }
}

async function parseEnvelope(resp) {
  let payload = null
  try {
    payload = await resp.json()
  } catch {
    /* 非 JSON（如下载流）*/
  }
  if (!resp.ok) {
    if (resp.status === 401 || (payload && payload.code === 40101)) {
      handleUnauthorized()
    }
    throw new ApiError(
      payload?.code ?? resp.status,
      payload?.message || `请求失败（HTTP ${resp.status}）`,
      payload?.request_id,
    )
  }
  if (payload && typeof payload === 'object' && 'code' in payload) {
    if (payload.code !== 0) {
      if (payload.code === 40101) handleUnauthorized()
      throw new ApiError(payload.code, payload.message || '请求失败', payload.request_id)
    }
    return payload.data
  }
  return payload
}

export async function request(path, { method = 'GET', body, headers = {}, ...rest } = {}) {
  const opts = {
    method,
    headers: { ...headers },
    ...rest,
  }
  const token = getToken()
  if (token) opts.headers.Authorization = `Bearer ${token}`
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const resp = await fetch(path, opts)
  return parseEnvelope(resp)
}

/** multipart 上传：progress 不可用时静默降级为普通 POST */
export async function uploadMultipart(path, formData) {
  const token = getToken()
  const resp = await fetch(path, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  })
  return parseEnvelope(resp)
}

/** 文件下载（带鉴权） */
export async function downloadFile(path, fallbackName = 'download') {
  const token = getToken()
  const resp = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!resp.ok) {
    await parseEnvelope(resp) // 抛出业务错误
    return
  }
  const blob = await resp.blob()
  const dispo = resp.headers.get('Content-Disposition') || ''
  const m = dispo.match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i)
  let name = fallbackName
  if (m) {
    try {
      name = decodeURIComponent(m[1])
    } catch {
      name = m[1]
    }
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}
