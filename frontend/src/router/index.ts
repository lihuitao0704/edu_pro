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
          { path: 'chat', component: () => import('../views/ChatView.vue') },
          { path: 'profile', component: () => import('../views/ProfileView.vue') },
          { path: 'advisor', component: () => import('../views/AdvisorWorkspaceView.vue') },
          { path: 'operations', component: () => import('../views/OperationsView.vue') },
          { path: 'risk', component: () => import('../views/RiskManagementView.vue') },
          { path: 'analytics', component: () => import('../views/AnalyticsView.vue') },
          { path: 'knowledge', component: () => import('../views/KnowledgeView.vue') },
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
