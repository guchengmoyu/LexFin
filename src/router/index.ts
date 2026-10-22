import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    roles?: string[]
  }
}

/**
 * 路由与权限（docs/07 §2 §9，history 模式）。
 * meta.roles：仅这些角色可访问；未声明则登录即可。
 */
const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('../views/ChatView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/chat/:sessionNo',
    name: 'chat-session',
    component: () => import('../views/ChatView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/search',
    name: 'search',
    component: () => import('../views/SearchView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/documents',
    name: 'documents',
    component: () => import('../views/DocumentsView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/documents/:id',
    name: 'document-detail',
    component: () => import('../views/DocumentDetailView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/knowledge-points',
    name: 'knowledge-points',
    component: () => import('../views/KnowledgePointsView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/knowledge-points/:id',
    name: 'knowledge-point-detail',
    component: () => import('../views/KnowledgePointDetailView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/knowledge-base',
    name: 'knowledge-base',
    component: () => import('../views/KnowledgeBaseView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('../views/HistoryView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/favorites',
    name: 'favorites',
    component: () => import('../views/FavoritesView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('../views/DashboardView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/tasks',
    name: 'tasks',
    component: () => import('../views/TaskListView.vue'),
    meta: { requiresAuth: true, roles: ['editor', 'admin'] },
  },
  {
    path: '/review',
    name: 'review',
    component: () => import('../views/ReviewView.vue'),
    meta: { requiresAuth: true, roles: ['editor', 'admin'] },
  },
  {
    path: '/feedback',
    name: 'feedback',
    component: () => import('../views/FeedbackView.vue'),
    meta: { requiresAuth: true, roles: ['editor', 'admin'] },
  },
  {
    path: '/404',
    name: 'not-found',
    component: () => import('../views/NotFoundView.vue'),
  },
  { path: '/', redirect: '/chat' },
  { path: '/:pathMatch(.*)*', redirect: '/404' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.isLoggedIn) {
    return { name: 'chat' }
  }
  // 首次进入（刷新后 user 丢失）先拉取用户信息，再做角色判定
  if (to.meta.requiresAuth && auth.isLoggedIn && !auth.user) {
    await auth.refreshMe()
  }
  if (to.meta.roles && !auth.hasRole(...to.meta.roles)) {
    ElMessage.warning('无访问权限')
    return { name: 'chat' }
  }
  return true
})

export default router
