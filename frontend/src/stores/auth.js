import { defineStore } from 'pinia'
import { authApi } from '../api'
import { setToken, getToken, setSavedUser, getSavedUser, clearAuth } from '../api/http'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    user: getSavedUser(), // {id, username, real_name, role}
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    role: (s) => s.user?.role || 'viewer',
    displayName: (s) => s.user?.real_name || s.user?.username || '未登录',
    canManage: (s) => ['admin', 'editor'].includes(s.user?.role),
  },
  actions: {
    async login(username, password) {
      const data = await authApi.login(username, password)
      this.token = data.access_token
      this.user = data.user
      setToken(data.access_token)
      setSavedUser(data.user)
      return data
    },
    async register(payload) {
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
