<template>
  <div class="finance-chat-page">
    <section class="finance-page-intro">
      <div>
        <span class="section-kicker">PRIVATE WEALTH INTELLIGENCE</span>
        <h1>AI 财富助手</h1>
        <p>面向产品咨询、投资建议、风险评估与账户业务的一体化智能服务。</p>
      </div>
      <div class="chat-capabilities"><span>产品咨询</span><span>投资建议</span><span>风险评估</span><span>账户服务</span></div>
    </section>
    <ChatWindow :user-id="auth.user?.user_id || 0" :user-role="auth.user?.role || '客户'" :customer-name="auth.user?.real_name || auth.user?.username || ''" />
  </div>
</template>

<script setup lang="ts">
import ChatWindow from '../components/ChatWindow.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
</script>

<style scoped>
.finance-chat-page {
  height: calc(100dvh - 149px);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.finance-page-intro { flex: 0 0 auto; }
:deep(.chat-window) { flex: 1; min-height: 0; }
:deep(.chat-window-header) { min-height: 54px; padding: 12px 24px; justify-content: flex-end; }
:deep(.chat-window-header > div:first-child) { display: none; }
:deep(.chat-scroll-area) { min-height: 0; max-height: none; }
@media (max-width: 760px) {
  .finance-chat-page { height: auto; }
  :deep(.chat-window) { min-height: 620px; }
}
</style>
