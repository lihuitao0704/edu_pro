<template>
  <section class="chat-window">
    <header class="chat-window-header">
      <div>
        <span class="section-kicker"><i /> AI 财富助手</span>
        <h2>智慧财富决策空间</h2>
      </div>
      <div class="conversation-status"><span>{{ messages.length }} 条对话</span><b>受监管模式</b></div>
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
      <MessageCard v-for="(message, index) in messages" :key="index" :message="message" />
      <div v-if="loading" class="assistant-loading"><i /> 正在协调金融智能服务…</div>
    </div>

    <p v-if="error" class="chat-error">{{ error }}，已提供演示建议供您继续体验。</p>
    <form class="chat-composer" @submit.prevent="send">
      <textarea v-model="input" rows="2" placeholder="例如：我有 50 万闲置资金，希望稳健增值" @keydown.enter.exact.prevent="send" />
      <div>
        <span>建议仅供参考，具体投资请以适当性评估与产品文件为准</span>
        <button class="finance-primary" :disabled="!input.trim() || loading">{{ loading ? '分析中' : '发送咨询' }}</button>
      </div>
    </form>
  </section>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'

import { createMockChatResponse, sendChat } from '../api/chat'
import MessageCard, { type ChatMessage } from './MessageCard.vue'

const props = withDefaults(defineProps<{ userId?: string | number; userRole?: string }>(), { userId: 0, userRole: '客户' })
const conversationId = ref(`wealth-${Date.now().toString(36)}`)
const mockEnabled = import.meta.env.DEV && import.meta.env.VITE_ENABLE_CHAT_MOCK === 'true'
const prompts = ['我有 50 万，如何稳健配置？', '帮我评估当前投资风险', '有哪些适合长期持有的产品？', '我想了解账户赎回流程']
const messages = ref<ChatMessage[]>([])
const input = ref('')
const loading = ref(false)
const error = ref('')
const scrollArea = ref<HTMLElement>()

function ask(prompt: string) {
  input.value = prompt
  void send()
}

async function send() {
  const message = input.value.trim()
  if (!message || loading.value) return
  messages.value.push({ role: 'user', content: message })
  input.value = ''
  loading.value = true
  error.value = ''
  await scrollToBottom()

  try {
    const response = await sendChat({ user_id: props.userId, user_role: props.userRole, conversation_id: conversationId.value, message })
    if (response.metadata.session_id) conversationId.value = response.metadata.session_id
    messages.value.push({ role: 'assistant', content: response.answer, response })
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '金融服务暂时不可用'
    if (mockEnabled) {
      const response = createMockChatResponse(message)
      messages.value.push({ role: 'assistant', content: response.answer, response, isMock: true })
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
</script>
