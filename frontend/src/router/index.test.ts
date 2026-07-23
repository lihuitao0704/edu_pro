import { createMemoryHistory } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { createAppRouter } from './index'

describe('createAppRouter', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('redirects an authenticated risk specialist from login to risk', async () => {
    localStorage.setItem('wealth-token', 'jwt')
    localStorage.setItem(
      'wealth-user',
      JSON.stringify({ user_id: 3, username: 'risk', role: '风控专员' }),
    )
    const router = createAppRouter(createMemoryHistory())

    await router.push('/login')
    await router.isReady()

    expect(router.currentRoute.value.fullPath).toBe('/risk')
  })

  it('redirects an authenticated customer from register to chat', async () => {
    localStorage.setItem('wealth-token', 'jwt')
    localStorage.setItem(
      'wealth-user',
      JSON.stringify({ user_id: 5, username: 'customer', role: '客户' }),
    )
    const router = createAppRouter(createMemoryHistory())

    await router.push('/register')
    await router.isReady()

    expect(router.currentRoute.value.fullPath).toBe('/chat')
  })

  it('redirects an unauthenticated advisor visitor to login', async () => {
    const router = createAppRouter(createMemoryHistory())

    await router.push('/advisor')
    await router.isReady()

    expect(router.currentRoute.value.fullPath).toBe('/login')
  })

  it('keeps an unauthenticated visitor on the public login page', async () => {
    const router = createAppRouter(createMemoryHistory())

    await router.push('/login')
    await router.isReady()

    expect(router.currentRoute.value.fullPath).toBe('/login')
  })

  it('redirects a customer away from a forbidden employee workbench', async () => {
    localStorage.setItem('wealth-token', 'jwt')
    localStorage.setItem(
      'wealth-user',
      JSON.stringify({ user_id: 5, username: 'customer', role: '客户' }),
    )
    const router = createAppRouter(createMemoryHistory())

    await router.push('/risk')
    await router.isReady()

    expect(router.currentRoute.value.fullPath).toBe('/chat')
  })
})
