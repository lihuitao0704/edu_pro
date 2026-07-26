import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '../stores/auth'
import AppLayout from './AppLayout.vue'

describe('AppLayout', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('does not render a top title bar after login', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.$patch({ token: 'token', user: { user_id: 1, username: 'admin', role: '\u7ba1\u7406\u5458' } })
    const routes = ['/', '/chat', '/dashboard', '/profile', '/advisor', '/operations', '/risk', '/analytics', '/knowledge']
      .map((path) => ({ path, component: { template: '<div />' } }))
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/')
    await router.isReady()

    const wrapper = mount(AppLayout, {
      global: {
        plugins: [pinia, router],
        stubs: { AppIntro: true, RiskAssessmentModal: true },
      },
    })

    expect(wrapper.find('.workspace-topbar').exists()).toBe(false)
    wrapper.unmount()
  })
})
