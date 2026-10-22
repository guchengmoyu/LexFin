/**
 * 统一请求封装（Axios）：后端响应结构 {code, message, data, request_id}（docs/06 §2）。
 * 成功 code === 0；40101 未认证 → 清除本地态并跳登录（history 模式路由）。
 */
import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import type { UserInfo } from '../types'

const TOKEN_KEY = 'lexfin_token'
const USER_KEY = 'lexfin_user'

const instance = axios.create({ baseURL: '' })

instance.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string): void {
  token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY)
}

export function getSavedUser(): UserInfo | null {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function setSavedUser(user: UserInfo | null): void {
  user
    ? localStorage.setItem(USER_KEY, JSON.stringify(user))
    : localStorage.removeItem(USER_KEY)
}

export function clearAuth(): void {
  setToken('')
  setSavedUser(null)
}

export class ApiError extends Error {
  code: number
  requestId?: string

  constructor(code: number, message: string, requestId?: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.requestId = requestId
  }
}

/** 未认证：清态并跳登录（懒加载 router 避免循环依赖） */
let redirecting = false
function handleUnauthorized(): void {
  clearAuth()
  if (redirecting || location.pathname === '/login') return
  redirecting = true
  import('../router')
    .then(({ default: router }) => router.push({ name: 'login' }))
    .finally(() => {
      redirecting = false
    })
}

interface Envelope<T = any> {
  code: number
  message?: string
  data: T
  request_id?: string
}

/** 解包统一响应：code===0 返回 data，否则抛 ApiError */
function unwrap<T>(payload: any, httpStatus: number): T {
  if (payload && typeof payload === 'object' && 'code' in payload) {
    const env = payload as Envelope<T>
    if (env.code === 40101) handleUnauthorized()
    if (env.code !== 0) throw new ApiError(env.code, env.message || '请求失败', env.request_id)
    return env.data
  }
  if (httpStatus >= 400) throw new ApiError(httpStatus, `请求失败（HTTP ${httpStatus}）`)
  return payload as T
}

function toApiError(err: unknown): never {
  if (err instanceof ApiError) throw err
  const axErr = err as AxiosError
  const resp = axErr?.response
  const payload = resp?.data as any
  // blob 错误响应（下载失败）先解析内容
  if (payload instanceof Blob) {
    throw new ApiError(resp?.status ?? -1, `请求失败（HTTP ${resp?.status}）`)
  }
  if (resp && (resp.status === 401 || payload?.code === 40101)) handleUnauthorized()
  throw new ApiError(
    payload?.code ?? resp?.status ?? -1,
    payload?.message || (resp ? `请求失败（HTTP ${resp.status}）` : '网络错误，请检查连接'),
    payload?.request_id,
  )
}

export interface RequestOptions {
  method?: string
  body?: any
  headers?: Record<string, string>
  [key: string]: any
}

export async function request<T = any>(
  path: string,
  { method = 'GET', body, headers = {}, ...rest }: RequestOptions = {},
): Promise<T> {
  const isForm = body instanceof FormData
  const config: AxiosRequestConfig = {
    url: path,
    method,
    headers: { ...headers },
    ...rest,
  }
  if (body !== undefined) {
    config.data = body
    if (!isForm) config.headers!['Content-Type'] = 'application/json'
  }
  try {
    const resp = await instance.request<T>(config)
    return unwrap<T>(resp.data, resp.status)
  } catch (err) {
    toApiError(err)
  }
}

/** multipart 上传：可选上传进度回调 */
export async function uploadMultipart<T = any>(
  path: string,
  formData: FormData,
  onUploadProgress?: (e: any) => void,
): Promise<T> {
  try {
    const resp = await instance.request<T>({
      url: path,
      method: 'POST',
      data: formData,
      onUploadProgress,
    })
    return unwrap<T>(resp.data, resp.status)
  } catch (err) {
    toApiError(err)
  }
}

/** 文件下载（带鉴权） */
export async function downloadFile(path: string, fallbackName = 'download'): Promise<void> {
  let resp
  try {
    resp = await instance.get<Blob>(path, { responseType: 'blob' })
  } catch (err) {
    const axErr = err as AxiosError
    const data: any = axErr?.response?.data
    if (data instanceof Blob) {
      try {
        const j = JSON.parse(await data.text())
        if (j.code === 40101) handleUnauthorized()
        throw new ApiError(j.code ?? axErr.response?.status ?? -1, j.message || '下载失败', j.request_id)
      } catch (pe) {
        if (pe instanceof ApiError) throw pe
        throw new ApiError(axErr.response?.status ?? -1, '下载失败')
      }
    }
    throw err instanceof ApiError ? err : new ApiError(-1, '下载失败')
  }
  const blob = resp.data
  const dispo: string = (resp.headers['content-disposition'] as string) || ''
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
