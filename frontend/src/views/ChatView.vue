<template>
  <div class="chat-fullscreen">
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
.chat-fullscreen {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
:deep(.chat-window) {
  flex: 1;
  min-height: 0;
  border: none;
  border-radius: 0;
  box-shadow: none;
  background: transparent;
}
:deep(.chat-window-header) {
  border-bottom: 1px solid var(--finance-line, #263247);
  background: rgba(11, 17, 32, 0.6);
  backdrop-filter: blur(12px);
}
:deep(.chat-scroll-area) {
  max-height: none;
  background: transparent;
}
:deep(.chat-empty-state) {
  margin: 12vh auto 0;
}
:deep(.chat-composer) {
  border-top: 1px solid var(--finance-line, #263247);
  background: rgba(11, 17, 32, 0.6);
  backdrop-filter: blur(12px);
}
@media (max-width: 760px) {
  .chat-fullscreen { height: auto; }
  :deep(.chat-window) { min-height: 70vh; }
}
</style>
