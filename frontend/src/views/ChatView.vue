<template>
  <div class="finance-chat-page">
    <section class="finance-page-intro">
      <div>
        <h1>AI 财富助手</h1>
        <p>面向产品咨询、投资建议、风险评估与账户业务的一体化智能服务。</p>
      </div>
      <div class="chat-capabilities">
        <span>产品咨询</span><span>投资建议</span><span>风险评估</span><span>账户服务</span>
        <button v-if="auth.user?.role === '客户'" class="assessment-entry-btn" @click="showAssessment = true">📋 风评问卷</button>
      </div>
    </section>
    <ChatWindow
      :user-id="auth.user?.user_id || 0"
      :user-role="auth.user?.role || '客户'"
      :customer-name="auth.user?.real_name || auth.user?.username || ''"
      @open-assessment="showAssessment = true"
    />
    <RiskAssessmentModal
      v-if="auth.user?.user_id"
      :visible="showAssessment"
      :customer-id="auth.user?.user_id"
      @update:visible="showAssessment = $event"
      @submitted="onAssessmentSubmitted"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ChatWindow from '../components/ChatWindow.vue'
import RiskAssessmentModal from '../components/RiskAssessmentModal.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const showAssessment = ref(false)

function onAssessmentSubmitted(result: any) {
  showAssessment.value = false
}
</script>

<style scoped>
.finance-chat-page {
  height: calc(100dvh - 130px);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.finance-page-intro {
  flex: 0 0 auto;
  margin-bottom: 14px;
}
.finance-page-intro p {
  margin: 0;
}
:deep(.chat-window) { flex: 1; min-height: 0; }
:deep(.chat-window-header) { min-height: 48px; padding: 10px 24px; justify-content: flex-end; }
:deep(.chat-window-header > div:first-child) { display: none; }
:deep(.chat-scroll-area) { min-height: 0; max-height: none; }
:deep(.chat-empty-state) { margin-top: 4vh; }
.assessment-entry-btn {
  padding: 7px 12px;
  border: 1px solid #0b7f78;
  border-radius: 99px;
  color: #0b7f78;
  background: rgba(11,127,120,.08);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: background .2s;
}
.assessment-entry-btn:hover {
  background: rgba(11,127,120,.16);
}
@media (max-width: 760px) {
  .finance-chat-page { height: auto; }
  :deep(.chat-window) { min-height: 620px; }
}
</style>
