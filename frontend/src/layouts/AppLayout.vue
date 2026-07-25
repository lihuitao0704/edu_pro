<template>
  <div class="app-shell finance-shell" :class="{ 'chat-route': route.path === '/chat' }">
    <aside class="sidebar" :class="{ open: mobileOpen }">
      <div class="brand"><div class="brand-mark">F</div><div><strong>FINTELLIGENCE</strong><span>FINANCIAL AGENT PLATFORM</span></div></div>
      <div class="role-card"><span class="eyebrow">CURRENT ROLE</span><strong>{{ auth.user?.role }}</strong><span>{{ auth.user?.real_name || auth.user?.username }}</span></div>
      <nav><router-link v-for="item in navigation" :key="item.path" :to="item.path" @click="mobileOpen = false"><span class="nav-icon">{{ item.icon }}</span><span>{{ item.label }}</span></router-link></nav>
      <div class="sidebar-footer"><div class="service-state"><i /> 金融智能服务已连接</div><button class="quiet-button" @click="logout">退出当前会话</button></div>
    </aside>
    <main class="main-area"><section class="content-area"><router-view /></section></main>
    <div v-if="mobileOpen" class="scrim" @click="mobileOpen = false" />
    <div v-if="showExpiryNotice" class="risk-expiry-overlay">
      <section class="risk-expiry-dialog"><span class="section-kicker">RISK ASSESSMENT REQUIRED</span><h2>您的风险评估已失效</h2><p>建议您及时完成风险评测；维持有效的风评状态，更方便购买适配的财富产品。</p><button class="finance-primary" @click="openAssessment">前往风评测试</button></section>
    </div>
    <RiskAssessmentModal v-model:visible="assessmentVisible" :customer-id="auth.user?.user_id || 0" @submitted="showExpiryNotice = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { navigationForRole } from '../navigation'
import { useAuthStore } from '../stores/auth'
import { get } from '../api/http'
import RiskAssessmentModal from '../components/RiskAssessmentModal.vue'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const showExpiryNotice = ref(false)
const assessmentVisible = ref(false)
const navigation = computed(() => navigationForRole(auth.user?.role || ''))
function logout() { auth.logout(); router.push('/login') }
function openAssessment() { showExpiryNotice.value = false; assessmentVisible.value = true }
onMounted(async () => {
  if (auth.user?.role !== '客户') return
  try {
    const status = await get<{ needs_assessment: boolean }>('/risk/assessment-status')
    // 只有当画像无法检索 / 风评完全不存在时才弹窗
    showExpiryNotice.value = status.needs_assessment
  } catch {
    // 接口异常说明画像服务不可用，此时也不弹窗
    showExpiryNotice.value = false
  }
})
</script>
