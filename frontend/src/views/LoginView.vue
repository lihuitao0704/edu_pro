<template>
  <div class="auth-page">
    <section class="auth-hero">
      <div class="story-orbit orbit-one" />
      <div class="story-orbit orbit-two" />
      <div class="login-logo">澄</div>
      <span class="eyebrow light">FINANCIAL INTELLIGENCE, MADE CLEAR</span>
      <h1>让每一次财富决策<br />都有据可循。</h1>
      <p>多 Agent 协同分析客户、产品与风险，把复杂金融服务变成清晰可执行的下一步。</p>
      <div class="story-stats">
        <div><strong>5</strong><span>专业角色</span></div>
        <div><strong>20</strong><span>AML 规则</span></div>
        <div><strong>360°</strong><span>客户画像</span></div>
      </div>
    </section>
    <section class="auth-panel">
      <form class="auth-form" @submit.prevent="submit">
        <span class="eyebrow">安全工作区</span>
        <h2>欢迎回来</h2>
        <p class="muted">输入账号密码，系统将自动识别您的身份。</p>
        <label>用户名<input v-model.trim="form.username" autocomplete="username" placeholder="请输入用户名" /></label>
        <label>密码<input v-model="form.password" type="password" autocomplete="current-password" placeholder="请输入密码" /></label>
        <ErrorAlert :message="error" />
        <button class="primary-button login-submit" :disabled="loading">
          {{ loading ? '正在验证身份…' : '登录' }}
        </button>
        <p class="auth-switch">还没有账户？<a href="/register">立即注册</a></p>
      </form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import ErrorAlert from '../components/ErrorAlert.vue'
import { useAuthStore } from '../stores/auth'
import { homeForRole } from '../navigation'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const error = ref('')
const form = reactive({ username: '', password: '' })

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await auth.login(form.username, form.password)
    await router.push(homeForRole(auth.user?.role || ''))
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '登录失败'
  } finally {
    loading.value = false
  }
}
</script>
