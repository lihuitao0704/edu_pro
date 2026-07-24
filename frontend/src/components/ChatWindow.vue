<template>
  <section class="chat-window">
    <header class="chat-window-header">
      <div class="header-left">
        <span class="header-dot" />
        <span class="header-title">AI 财富助手</span>
      </div>
      <div class="header-right">
        <span class="header-status">{{ customerName ? `${customerName}` : `${messages.length} 条对话` }}</span>
        <button class="new-chat-btn" @click="newChat" title="开始新对话">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
          新聊天
        </button>
      </div>
    </header>

    <div ref="scrollArea" class="chat-scroll-area">
      <div v-if="!messages.length" class="chat-empty-state">
        <span class="empty-orb">AI</span>
        <h3>从一个财富目标开始</h3>
        <p>平台将综合产品信息、风险规则与您的交互上下文，形成可解释的专业建议。</p>
        <div class="quick-prompts">
          <button v-for="prompt in prompts" :key="prompt" type="button" @click="ask(prompt)">{{ prompt }}</button>
        </div>
      </div>
      <MessageCard v-for="(message, index) in messages" :key="index" :message="message" @open-assessment="emit('open-assessment')" />
      <div v-if="loading" class="assistant-loading"><i /> 正在协调金融智能服务…</div>
    </div>

    <p v-if="error" class="chat-error">{{ error }}</p>
    <form class="chat-composer" @submit.prevent="send">
      <div class="composer-row">
        <textarea v-model="input" rows="1" placeholder="例如：我有 50 万闲置资金，希望稳健增值" @keydown.enter.exact.prevent="send" />
        <button class="finance-primary" :disabled="!input.trim() || loading">{{ loading ? '分析中' : '发送咨询' }}</button>
      </div>
      <span class="composer-hint">建议仅供参考，具体投资请以适当性评估与产品文件为准</span>
    </form>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'

import { createMockChatResponse, getChatHistory, sendChat } from '../api/chat'
import MessageCard from './MessageCard.vue'
import { useConversationStore } from '../stores/conversation'

const props = withDefaults(defineProps<{ userId?: string | number; userRole?: string; customerName?: string }>(), { userId: 0, userRole: '客户', customerName: '' })
const emit = defineEmits<{ 'open-assessment': [] }>()
const conversations = useConversationStore()
const userKey = computed(() => String(props.userId))
const session = computed(() => conversations.sessionFor(userKey.value))
const messages = computed(() => session.value.messages)
const mockEnabled = import.meta.env.DEV && import.meta.env.VITE_ENABLE_CHAT_MOCK === 'true'
const prompts = ['我有 50 万，如何稳健配置？', '帮我评估当前投资风险', '有哪些适合长期持有的产品？', '我想了解账户赎回流程']
const input = ref('')
const loading = ref(false)
const error = ref('')
const scrollArea = ref<HTMLElement>()

async function hydrateHistory() {
  try {
    const history = await getChatHistory()
    conversations.hydrateUserSession(userKey.value, history)
    await scrollToBottom()
  } catch {
    // 历史读取失败不阻塞当前会话；发送下一条消息会建立新会话。
  }
}

function ask(prompt: string) {
  input.value = prompt
  void send()
}

async function send() {
  const message = input.value.trim()
  if (!message || loading.value) return
  conversations.appendMessage(userKey.value, { role: 'user', content: message })
  input.value = ''
  loading.value = true
  error.value = ''
  await scrollToBottom()

  try {
    const response = await sendChat({ user_id: props.userId, user_role: props.userRole, conversation_id: session.value.conversationId, message })
    if (response.metadata.session_id) conversations.setSessionId(userKey.value, response.metadata.session_id)
    conversations.appendMessage(userKey.value, { role: 'assistant', content: response.answer, response })
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '金融服务暂时不可用'
    if (mockEnabled) {
      const response = createMockChatResponse(message)
      conversations.appendMessage(userKey.value, { role: 'assistant', content: response.answer, response, isMock: true })
    }
  } finally {
    loading.value = false
    await scrollToBottom()
  }
}

async function scrollToBottom() {
  await nextTick()
  scrollArea.value?.scrollTo({ top: scrollArea.value.scrollHeight, behavior: 'smooth' })
}

function newChat() {
  // 清空可见消息，但保留 session 和 conversationId（后端上下文记忆）
  session.value.messages = []
  input.value = ''
  error.value = ''
}

onMounted(() => {
  void hydrateHistory()
})
</script>

<style scoped>
.chat-window {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* Header — 极简一行 */
.chat-window-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  min-height: 48px;
  flex-shrink: 0;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--finance-green, #34d399);
  box-shadow: 0 0 0 4px rgba(52, 211, 153, 0.1);
}
.header-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--finance-text, #e7eef9);
  letter-spacing: 0.02em;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 11px;
}
.header-status {
  color: var(--finance-muted, #8d9bb1);
  font-size: 12px;
}
.new-chat-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border: 1px solid var(--finance-line, #263247);
  border-radius: 8px;
  color: #a9b8ca;
  background: transparent;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.new-chat-btn:hover {
  color: #e1f3ff;
  border-color: #38bdf8;
  background: rgba(56, 189, 248, 0.08);
}

/* Scroll area */
.chat-scroll-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px clamp(16px, 4vw, 64px);
}

/* Empty state */
.chat-empty-state {
  max-width: 560px;
  margin: 10vh auto 0;
  text-align: center;
}
.empty-orb {
  width: 56px;
  height: 56px;
  margin: auto;
  display: grid;
  place-items: center;
  border: 1px solid #3174a5;
  border-radius: 16px;
  color: #bae6fd;
  background: linear-gradient(135deg, #102b4a, #192155);
  font-weight: 800;
  font-size: 16px;
  letter-spacing: 0.06em;
}
.chat-empty-state h3 {
  margin: 20px 0 8px;
  color: #eef6ff;
  font-size: 22px;
  font-weight: 600;
}
.chat-empty-state p {
  margin: 0;
  color: var(--finance-muted, #8d9bb1);
  font-size: 13px;
  line-height: 1.7;
}
.quick-prompts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: 24px;
}
.quick-prompts button {
  min-height: 44px;
  padding: 10px 14px;
  border: 1px solid var(--finance-line, #263247);
  border-radius: 10px;
  color: #b7c6d9;
  background: #121c2c;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s, background 0.2s;
}
.quick-prompts button:hover {
  border-color: #397ca9;
  color: #e1f3ff;
  background: #16263c;
}

/* Composer */
.chat-composer {
  padding: 12px 24px;
  flex-shrink: 0;
}
.composer-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.composer-row textarea {
  flex: 1;
  min-height: 40px;
  max-height: 80px;
  border: 1px solid #334155;
  border-radius: 10px;
  color: #e5edf9;
  background: #0f172a;
  padding: 10px 14px;
  resize: none;
  outline: none;
  font-size: 13px;
}
.composer-row textarea:focus {
  border-color: #38bdf8;
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.12);
}
.composer-row button {
  flex: 0 0 auto;
  white-space: nowrap;
  padding: 10px 20px;
}
.composer-hint {
  display: block;
  margin-top: 6px;
  color: #71819a;
  font-size: 10px;
}

/* Loading */
.assistant-loading {
  max-width: 820px;
  margin: 0 auto;
  color: #91a8c0;
  font-size: 12px;
}
.assistant-loading i {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 7px;
  border-radius: 50%;
  background: var(--finance-blue, #38bdf8);
  animation: glow 1s infinite alternate;
}
@keyframes glow {
  to { box-shadow: 0 0 13px var(--finance-blue, #38bdf8); }
}

/* Error */
.chat-error {
  margin: 0;
  padding: 8px 24px;
  color: #fdba74;
  background: rgba(180, 83, 9, 0.12);
  font-size: 11px;
}

@media (max-width: 760px) {
  .quick-prompts {
    grid-template-columns: 1fr;
  }
  .chat-scroll-area {
    padding: 16px 12px;
  }
  .chat-window-header {
    padding: 10px 14px;
  }
  .chat-composer {
    padding: 10px 14px;
  }
}
</style>
