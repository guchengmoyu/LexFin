<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useKbStore } from './stores/kb'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const kbStore = useKbStore()

const isLogin = computed(() => route.name === 'login')

interface NavItem {
  name: string
  label: string
  icon: string
  base: string
  group: 'main' | 'admin'
  roles?: string[]
}

/** 侧边菜单（docs/07 §3）：按角色条件渲染，管理组仅编辑/管理员可见 */
const NAVS: NavItem[] = [
  { name: 'chat', label: '智能问答', icon: '💬', base: '/chat', group: 'main' },
  { name: 'search', label: '检索条文', icon: '🔍', base: '/search', group: 'main' },
  { name: 'documents', label: '文档管理', icon: '📄', base: '/documents', group: 'main' },
  { name: 'knowledge-base', label: '知识库', icon: '📚', base: '/knowledge-base', group: 'main' },
  { name: 'knowledge-points', label: '知识点', icon: '🧩', base: '/knowledge-points', group: 'main' },
  { name: 'favorites', label: '我的收藏', icon: '⭐', base: '/favorites', group: 'main' },
  { name: 'history', label: '问答历史', icon: '🕘', base: '/history', group: 'main' },
  { name: 'dashboard', label: '数据概览', icon: '📊', base: '/dashboard', group: 'main' },
  { name: 'tasks', label: '入库任务', icon: '📥', base: '/tasks', group: 'admin', roles: ['editor', 'admin'] },
  { name: 'review', label: '人工校验', icon: '✍️', base: '/review', group: 'admin', roles: ['editor', 'admin'] },
  { name: 'feedback', label: '反馈处理', icon: '🗣', base: '/feedback', group: 'admin', roles: ['editor', 'admin'] },
]

const navs = computed<NavItem[]>(() => NAVS.filter((n) => !n.roles || auth.hasRole(...n.roles)))

const collapsed = ref(localStorage.getItem('lexfin_nav_collapsed') === '1')
function toggleNav() {
  collapsed.value = !collapsed.value
  localStorage.setItem('lexfin_nav_collapsed', collapsed.value ? '1' : '0')
}

function isActive(n: NavItem): boolean {
  return route.path === n.base || route.path.startsWith(`${n.base}/`)
}

async function handleLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}

if (auth.isLoggedIn) kbStore.ensureLoaded()
</script>

<template>
  <!-- 登录页独立全屏布局 -->
  <router-view v-if="isLogin" />

  <div v-else class="app-shell" :class="{ 'nav-collapsed': collapsed }">
    <aside class="app-nav">
      <div class="brand">
        <div class="brand-logo">LF</div>
        <div v-if="!collapsed" class="brand-text">
          <div class="brand-name">LexFin</div>
          <div class="brand-sub">金融制度知识问答</div>
        </div>
      </div>

      <nav class="nav-list">
        <template v-for="(n, i) in navs" :key="n.name">
          <div
            v-if="n.group === 'admin' && (i === 0 || navs[i - 1].group !== 'admin') && !collapsed"
            class="nav-group"
          >
            管理
          </div>
          <router-link
            :to="{ name: n.name }"
            class="nav-item"
            :class="{ active: isActive(n) }"
            :title="collapsed ? n.label : ''"
          >
            <span class="nav-icon">{{ n.icon }}</span>
            <span v-if="!collapsed" class="nav-text">{{ n.label }}</span>
          </router-link>
        </template>
      </nav>

      <div class="nav-footer">
        <button class="collapse-btn" :title="collapsed ? '展开菜单' : '收起菜单'" @click="toggleNav">
          {{ collapsed ? '»' : '«' }}
        </button>
        <div class="user-card">
          <div class="avatar">{{ auth.displayName.slice(0, 1).toUpperCase() }}</div>
          <div v-if="!collapsed" class="user-meta">
            <div class="user-name">{{ auth.displayName }}</div>
            <div class="user-role">{{ auth.isAdmin ? '管理员' : auth.canManage ? '编辑者' : '查看者' }}</div>
          </div>
        </div>
        <button v-if="!collapsed" class="btn-ghost logout-btn" @click="handleLogout">退出登录</button>
      </div>
    </aside>

    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>
