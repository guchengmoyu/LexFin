import { defineStore } from 'pinia'
import { kbApi } from '../api'

export const useKbStore = defineStore('kb', {
  state: () => ({
    list: [], // [{id, code, name, category, document_count, chunk_count, kp_count...}]
    loaded: false,
  }),
  getters: {
    kbName: (s) => (id) => s.list.find((k) => k.id === id)?.name || `知识库 #${id}`,
  },
  actions: {
    async ensureLoaded() {
      if (this.loaded) return
      try {
        this.list = (await kbApi.list()) || []
        this.loaded = true
      } catch {
        /* 登录前调用会被路由守卫拦下 */
      }
    },
  },
})
