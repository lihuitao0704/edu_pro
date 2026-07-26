<template>
  <div class="app-shell finance-shell" :class="{ 'chat-route': route.path === '/chat' }">
    <aside class="sidebar" :class="{ open: mobileOpen }" aria-label="主导航">
      <div class="brand">
        <div class="brand-mark">F</div>
        <div><strong>FINTELLIGENCE</strong><span>WEALTH INTELLIGENCE</span></div>
      </div>
      <div class="role-card">
        <span class="eyebrow">CURRENT WORKSPACE</span>
        <strong>{{ auth.user?.role }}</strong>
        <span>{{ auth.user?.real_name || auth.user?.username }}</span>
      </div>
      <nav aria-label="工作区导航">
        <router-link v-for="item in navigation" :key="item.path" :to="item.path" @click="mobileOpen = false">
          <span class="nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path :d="iconPath(item.icon)" /></svg></span>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <div class="service-state"><i />智能服务已连接</div>
        <button class="quiet-button" type="button" @click="logout">退出当前会话</button>
      </div>
    </aside>

    <main class="main-area">
      <header class="workspace-topbar">
        <button class="icon-button sidebar-toggle" type="button" aria-label="打开导航" @click="mobileOpen = true"><span /></button>
        <div class="topbar-context"><span>FINTELLIGENCE / WORKSPACE</span><strong>{{ pageTitle }}</strong></div>
        <div class="topbar-actions"><span class="connection-pill"><i />服务已连接</span><button class="avatar-button" type="button" :aria-label="`${auth.user?.real_name || auth.user?.username || '当前用户'}的账户`">{{ userInitial }}</button></div>
      </header>
      <section class="content-area"><router-view /></section>
    </main>

    <div v-if="mobileOpen" class="scrim" @click="mobileOpen = false" />
    <div v-if="showExpiryNotice" class="risk-expiry-overlay">
      <section class="risk-expiry-dialog" role="dialog" aria-modal="true" aria-labelledby="risk-expiry-title">
        <span class="section-kicker">RISK ASSESSMENT REQUIRED</span>
        <h2 id="risk-expiry-title">您的风险评估已失效</h2>
        <p>建议您及时完成风险评测，维持有效的风险评估状态，以便购买适配的财富产品。</p>
        <button class="finance-primary" type="button" @click="openAssessment">前往风险评测</button>
      </section>
    </div>
    <RiskAssessmentModal v-model:visible="assessmentVisible" :customer-id="auth.user?.user_id || 0" @submitted="showExpiryNotice = false" />
    <AppIntro :visible="introVisible" @complete="completeIntro" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { get } from '../api/http'
import AppIntro from '../components/AppIntro.vue'
import RiskAssessmentModal from '../components/RiskAssessmentModal.vue'
import { navigationForRole } from '../navigation'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const showExpiryNotice = ref(false)
const assessmentVisible = ref(false)
const introVisible = ref(false)
let introTimer: ReturnType<typeof setTimeout> | undefined

const navigation = computed(() => navigationForRole(auth.user?.role || ''))
const pageTitle = computed(() => navigation.value.find((item) => item.path === route.path)?.label || '智能投顾工作台')
const userInitial = computed(() => (auth.user?.real_name || auth.user?.username || 'U').slice(0, 1).toUpperCase())

const icons: Record<string, string> = {
  spark: 'm12 3-1.8 5.2L5 10l5.2 1.8L12 17l1.8-5.2L19 10l-5.2-1.8L12 3Z',
  grid: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  user: 'M20 21a8 8 0 0 0-16 0M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z',
  briefcase: 'M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M4 7h16v12H4zM4 12h16',
  workflow: 'M6 3v5M18 16v5M18 3v5M6 16v5M4 8h4v8H4zM16 8h4v8h-4zM8 12h8',
  shield: 'M12 3 5 6v5c0 4.7 3 8.5 7 10 4-1.5 7-5.3 7-10V6l-7-3Z',
  chart: 'M4 19V5M4 19h16M8 16v-5M12 16V7M16 16v-8',
  book: 'M5 4.5A2.5 2.5 0 0 1 7.5 2H20v17H7.5A2.5 2.5 0 0 0 5 21.5zM5 4.5v17M8 6h8M8 10h8',
}

function iconPath(name: string) { return icons[name] || icons.grid }
function logout() { auth.logout(); router.push('/login') }
function openAssessment() { showExpiryNotice.value = false; assessmentVisible.value = true }
function completeIntro() { introVisible.value = false; if (introTimer) clearTimeout(introTimer) }

onMounted(async () => {
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (!reducedMotion) { introVisible.value = true; introTimer = setTimeout(completeIntro, 1200) }
  if (auth.user?.role !== '客户') return
  try {
    const status = await get<{ needs_assessment: boolean }>('/risk/assessment-status')
    showExpiryNotice.value = status.needs_assessment
  } catch {
    showExpiryNotice.value = false
  }
})

onBeforeUnmount(() => { if (introTimer) clearTimeout(introTimer) })
</script>
