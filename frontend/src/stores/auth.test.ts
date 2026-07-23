import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { post } from '../api/http'
import { useAuthStore } from './auth'

vi.mock('../api/http', () => ({ post: vi.fn() }))

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.mocked(post).mockReset()
  })

  it('registers a customer and then logs in with submitted credentials', async () => {
    vi.mocked(post)
      .mockResolvedValueOnce({ user_id: 7, username: 'new_customer', role: '客户' })
      .mockResolvedValueOnce({
        access_token: 'jwt',
        user: { user_id: 7, username: 'new_customer', role: '客户' },
      })
    const auth = useAuthStore()

    await auth.register({
      username: 'new_customer',
      password: 'StrongPass@123',
      real_name: '新客户',
      phone: '13800138000',
    })

    expect(post).toHaveBeenNthCalledWith(1, '/auth/register', expect.objectContaining({ username: 'new_customer' }))
    expect(post).toHaveBeenNthCalledWith(2, '/auth/login', { username: 'new_customer', password: 'StrongPass@123' })
    expect(auth.user?.role).toBe('客户')
  })
})
