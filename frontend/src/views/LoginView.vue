<template>
  <div class="login-page">
    <section class="login-story">
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
    <section class="login-panel">
      <form class="login-form" @submit.prevent="submit">
        <span class="eyebrow">安全工作区</span>
        <h2>欢迎回来</h2>
        <p class="muted">选择演示身份，或输入已有账号。</p>
        <div class="demo-roles">
          <button
            v-for="account in demoAccounts"
            :key="account.username"
            type="button"
            :class="{ active: form.username === account.username }"
            @click="selectAccount(account.username)"
          >
            <span>{{ account.icon }}</span>{{ account.label }}
          </button>
        </div>
        <label>用户名<input v-model.trim="form.username" autocomplete="username" /></label>
        <label>密码<input v-model="form.password" type="password" autocomplete="current-password" /></label>
        <ErrorAlert :message="error" />
        <button class="primary-button login-submit" :disabled="loading">
          {{ loading ? '正在验证身份…' : '进入工作台' }}
        </button>
        <p class="demo-tip">演示账号统一密码：<code>Demo@123</code></p>
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
const form = reactive({ username: 'demo_customer_01', password: 'Demo@123' })
const demoAccounts = [
  { label: '客户', username: 'demo_customer_01', icon: '客' },
  { label: '理财顾问', username: 'demo_advisor', icon: '顾' },
  { label: '客户经理', username: 'demo_manager', icon: '经' },
  { label: '风控专员', username: 'demo_risk', icon: '风' },
  { label: '管理员', username: 'demo_admin', icon: '管' },
]

function selectAccount(username: string) {
  form.username = username
  form.password = 'Demo@123'
}

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await auth.login(form.username, form.password)
    router.push(homeForRole(auth.user?.role || ''))
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '登录失败'
  } finally {
    loading.value = false
  }
}
</script>
