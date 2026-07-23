import { createRouter, createWebHistory } from 'vue-router'

import { homeForRole, navigationForRole } from '../navigation'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
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
  if (to.meta.public) return true
  const token = localStorage.getItem('wealth-token')
  const savedUser = localStorage.getItem('wealth-user')
  if (!token || !savedUser) return '/login'
  const role = JSON.parse(savedUser).role || ''
  if (to.path === '/') return homeForRole(role)
  const allowed = navigationForRole(role).some((item) => item.path === to.path)
  if (!allowed) return homeForRole(role)
  return true
})

export default router
