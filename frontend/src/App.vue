<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useKbStore } from './stores/kb'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const kbStore = useKbStore()

const isLogin = computed(() => route.name === 'login')

const navs = [
  { name: 'chat', label: '智能问答', icon: '💬' },
  { name: 'search', label: '检索中心', icon: '🔍' },
  { name: 'documents', label: '文档管理', icon: '📁' },
  { name: 'knowledge-points', label: '知识点库', icon: '📚' },
  { name: 'favorites', label: '我的收藏', icon: '⭐' },
]

async function handleLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}

if (auth.isLoggedIn) kbStore.ensureLoaded()
</script>

<template>
  <!-- 登录页独立全屏布局 -->
  <router-view v-if="isLogin" />

  <div v-else class="app-shell">
    <aside class="app-nav">
      <div class="brand">
        <div class="brand-logo">LF</div>
        <div class="brand-text">
          <div class="brand-name">LexFin</div>
          <div class="brand-sub">金融制度知识问答</div>
        </div>
      </div>

      <nav class="nav-list">
        <router-link
          v-for="n in navs"
          :key="n.name"
          :to="{ name: n.name }"
          class="nav-item"
          active-class="active"
        >
          <span class="nav-icon">{{ n.icon }}</span>
          <span>{{ n.label }}</span>
        </router-link>
      </nav>

      <div class="nav-footer">
        <div class="user-card">
          <div class="avatar">{{ auth.displayName.slice(0, 1).toUpperCase() }}</div>
          <div class="user-meta">
            <div class="user-name">{{ auth.displayName }}</div>
            <div class="user-role">{{ auth.canManage ? '编辑者' : '查看者' }}</div>
          </div>
        </div>
        <button class="btn-ghost logout-btn" @click="handleLogout">退出登录</button>
      </div>
    </aside>

    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>
