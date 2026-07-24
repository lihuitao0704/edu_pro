<template>
  <div class="app-shell finance-shell">
    <aside class="sidebar" :class="{ open: mobileOpen }">
      <div class="brand"><div class="brand-mark">F</div><div><strong>FINTELLIGENCE</strong><span>FINANCIAL AGENT PLATFORM</span></div></div>
      <div class="role-card"><span class="eyebrow">CURRENT ROLE</span><strong>{{ auth.user?.role }}</strong><span>{{ auth.user?.real_name || auth.user?.username }}</span></div>
      <nav><router-link v-for="item in navigation" :key="item.path" :to="item.path" @click="mobileOpen = false"><span class="nav-icon">{{ item.icon }}</span><span>{{ item.label }}</span></router-link></nav>
      <div class="sidebar-footer"><div class="service-state"><i /> 金融智能服务已连接</div><button class="quiet-button" @click="logout">退出当前会话</button></div>
    </aside>
    <main class="main-area"><header class="topbar"><button class="mobile-menu" aria-label="打开菜单" @click="mobileOpen = !mobileOpen">☰</button><div><span class="eyebrow">FINANCIAL AGENT OS</span><h1>{{ currentTitle }}</h1></div><div class="topbar-meta"><span>{{ dateLabel }}</span><b>{{ auth.user?.real_name?.slice(0, 1) || '您' }}</b></div></header><section class="content-area"><router-view /></section></main>
    <div v-if="mobileOpen" class="scrim" @click="mobileOpen = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { navigationForRole } from '../navigation'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const mobileOpen = ref(false)
const navigation = computed(() => navigationForRole(auth.user?.role || ''))
const currentTitle = computed(() => navigation.value.find((item) => item.path === route.path)?.label || '财富管理工作台')
const dateLabel = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' }).format(new Date())
function logout() { auth.logout(); router.push('/login') }
</script>
