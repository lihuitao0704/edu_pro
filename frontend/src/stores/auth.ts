import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { post } from '../api/http'
import type { AuthUser } from '../api/types'

interface LoginResult {
  access_token: string
  user: AuthUser
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('wealth-token') || '')
  const saved = localStorage.getItem('wealth-user')
  const user = ref<AuthUser | null>(saved ? JSON.parse(saved) : null)
  const isAuthenticated = computed(() => Boolean(token.value && user.value))

  async function login(username: string, password: string) {
    const result = await post<LoginResult>('/auth/login', { username, password })
    token.value = result.access_token
    user.value = result.user
    localStorage.setItem('wealth-token', token.value)
    localStorage.setItem('wealth-user', JSON.stringify(result.user))
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('wealth-token')
    localStorage.removeItem('wealth-user')
  }

  return { token, user, isAuthenticated, login, logout }
})
