import { defineStore } from 'pinia'
import { kbApi } from '../api'
import type { KbInfo } from '../types'

interface KbState {
  list: KbInfo[]
  loaded: boolean
}

export const useKbStore = defineStore('kb', {
  state: (): KbState => ({
    list: [], // [{id, code, name, category, document_count, chunk_count, kp_count...}]
    loaded: false,
  }),
  getters: {
    kbName: (s) => (id: number | string) =>
      s.list.find((k) => k.id === Number(id))?.name || `知识库 #${id}`,
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
