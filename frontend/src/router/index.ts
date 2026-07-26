import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

import { homeForRole, navigationForRole } from '../navigation'

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({
    history,
    routes: [
      { path: '/login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
      { path: '/register', component: () => import('../views/RegisterView.vue'), meta: { public: true } },
      {
        path: '/',
        component: () => import('../layouts/AppLayout.vue'),
        children: [
          { path: '', redirect: '/chat' },
          { path: 'chat', component: () => import('../views/ChatView.vue'), meta: { requiresAuth: true, title: 'AI \u8d22\u5bcc\u52a9\u624b' } },
          { path: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { requiresAuth: true, title: '\u667a\u80fd\u8fd0\u8425\u4e2d\u5fc3' } },
          { path: 'profile', component: () => import('../views/ProfileView.vue'), meta: { requiresAuth: true, title: '\u5ba2\u6237\u753b\u50cf' } },
          { path: 'advisor', component: () => import('../views/AdvisorWorkspaceView.vue'), meta: { requiresAuth: true, title: '\u987e\u95ee\u5de5\u4f5c\u53f0' } },
          { path: 'operations', component: () => import('../views/OperationsView.vue'), meta: { requiresAuth: true, title: '\u4e1a\u52a1\u529e\u7406\u4e0e\u5ba1\u6279' } },
          { path: 'risk', component: () => import('../views/RiskManagementView.vue'), meta: { requiresAuth: true, title: '\u98ce\u9669\u7ba1\u7406' } },
          { path: 'analytics', component: () => import('../views/AnalyticsView.vue'), meta: { requiresAuth: true, title: '\u6570\u636e\u5206\u6790' } },
          { path: 'knowledge', component: () => import('../views/KnowledgeView.vue'), meta: { requiresAuth: true, title: '\u77e5\u8bc6\u5e93' } },
        ],
      },
      { path: '/:pathMatch(.*)*', redirect: '/' },
    ],
  })

  router.beforeEach((to) => {
    const token = localStorage.getItem('wealth-token')
    const savedUser = localStorage.getItem('wealth-user')
    const role = savedUser ? JSON.parse(savedUser).role || '' : ''

    if (to.meta.public) {
      return token && savedUser ? homeForRole(role) : true
    }

    if (!token || !savedUser) return '/login'
    if (to.path === '/') return homeForRole(role)
    const allowed = navigationForRole(role).some((item) => item.path === to.path)
    return allowed ? true : homeForRole(role)
  })

  return router
}

export default createAppRouter()
