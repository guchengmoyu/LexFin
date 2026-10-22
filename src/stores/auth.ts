import { defineStore } from 'pinia'
import { authApi } from '../api'
import { setToken, getToken, setSavedUser, getSavedUser, clearAuth } from '../api/http'
import type { UserInfo, RegisterPayload, LoginResult } from '../types'

interface AuthState {
  token: string
  user: UserInfo | null
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: getToken(),
    user: getSavedUser(), // {id, username, real_name, role}
  }),
  getters: {
    isLoggedIn: (s): boolean => !!s.token,
    role: (s): string => s.user?.role || 'viewer',
    displayName: (s): string => s.user?.real_name || s.user?.username || '未登录',
    canManage: (s): boolean => ['admin', 'editor'].includes(s.user?.role || ''),
    isAdmin: (s): boolean => s.user?.role === 'admin',
    hasRole:
      (s) =>
      (...roles: string[]): boolean =>
        roles.includes(s.user?.role || 'viewer'),
  },
  actions: {
    async login(username: string, password: string): Promise<LoginResult> {
      const data = await authApi.login(username, password)
      this.token = data.access_token
      this.user = data.user
      setToken(data.access_token)
      setSavedUser(data.user)
      return data
    },
    async register(payload: RegisterPayload) {
      return authApi.register(payload)
    },
    async refreshMe() {
      if (!this.token) return
      try {
        const user = await authApi.me()
        this.user = user
        setSavedUser(user)
      } catch {
        /* 401 已由 http 层处理 */
      }
    },
    async logout() {
      try {
        await authApi.logout()
      } catch {
        /* 无状态登出，忽略 */
      }
      this.token = ''
      this.user = null
      clearAuth()
    },
    forceLogout() {
      this.token = ''
      this.user = null
      clearAuth()
    },
  },
})
