<template>
  <div class="auth-page">
    <section class="auth-hero">
      <div class="story-orbit orbit-one" />
      <div class="story-orbit orbit-two" />
      <div class="login-logo">澄</div>
      <span class="eyebrow light">OPEN YOUR ACCOUNT</span>
      <h1>开启智能财富之旅。</h1>
      <p>注册即享 AI 驱动的客户画像、智能投顾与全流程业务协同，让专业金融服务触手可及。</p>
    </section>
    <section class="auth-panel">
      <form class="auth-form" @submit.prevent="submit">
        <span class="eyebrow">客户注册</span>
        <h2>创建新账户</h2>
        <p class="muted">填写以下信息，完成后将自动登录。</p>
        <label>真实姓名<input v-model.trim="form.realName" autocomplete="name" placeholder="请输入真实姓名" /></label>
        <label>用户名<input v-model.trim="form.username" autocomplete="username" placeholder="3-64 位用户名" /></label>
        <label>手机号<input v-model.trim="form.phone" autocomplete="tel" placeholder="选填" /></label>
        <label>密码<input v-model="form.password" type="password" autocomplete="new-password" placeholder="至少 8 位" /></label>
        <label>确认密码<input v-model="form.confirmPassword" type="password" autocomplete="new-password" placeholder="再次输入密码" /></label>
        <ErrorAlert :message="error" />
        <button class="primary-button login-submit" :disabled="loading">
          {{ loading ? '正在创建账户…' : '立即注册' }}
        </button>
        <p class="auth-switch">已有账户？<a href="/login">返回登录</a></p>
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
const form = reactive({
  realName: '',
  username: '',
  phone: '',
  password: '',
  confirmPassword: '',
})

async function submit() {
  error.value = ''
  if (!form.realName || !form.username || !form.password) {
    error.value = '请填写真实姓名、用户名和密码'
    return
  }
  if (form.password !== form.confirmPassword) {
    error.value = '两次输入的密码不一致'
    return
  }
  loading.value = true
  try {
    await auth.register({
      username: form.username,
      password: form.password,
      real_name: form.realName,
      phone: form.phone || undefined,
    })
    await router.push(homeForRole(auth.user?.role || '客户'))
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '注册失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>
