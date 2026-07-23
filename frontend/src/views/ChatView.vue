<template>
  <div class="chat-workspace">
    <section class="agent-rail">
      <div class="section-heading">
        <span class="eyebrow">AGENT CHANNEL</span>
        <h2>选择智能体</h2>
      </div>
      <button
        v-for="agent in availableAgents"
        :key="agent.key"
        class="agent-card"
        :class="{ active: currentAgent === agent.key }"
        @click="currentAgent = agent.key"
      >
        <span class="agent-glyph">{{ agent.glyph }}</span>
        <span><strong>{{ agent.name }}</strong><small>{{ agent.description }}</small></span>
        <i />
      </button>
      <label v-if="currentAgent === 'advisor'" class="compact-field">
        服务客户 ID
        <input v-model.number="customerId" type="number" min="1" />
      </label>
      <div class="context-note">
        <span>上下文记忆</span>
        <strong>已开启</strong>
        <p>同一会话中的客户意图、引用和建议会被连续追踪。</p>
      </div>
    </section>
    <section class="conversation-panel">
      <header class="conversation-header">
        <div>
          <span class="live-dot" />
          <strong>{{ activeAgent.name }}</strong>
          <span>{{ activeAgent.model }}</span>
        </div>
        <button class="quiet-button" @click="messages = []">清空会话</button>
      </header>
      <div ref="messagePane" class="message-pane">
        <div v-if="!messages.length" class="chat-welcome">
          <span class="agent-glyph large">{{ activeAgent.glyph }}</span>
          <h2>{{ activeAgent.welcome }}</h2>
          <p>{{ activeAgent.prompt }}</p>
          <div class="prompt-grid">
            <button v-for="hint in activeAgent.hints" :key="hint" @click="input = hint">{{ hint }}</button>
          </div>
        </div>
        <article v-for="(message, index) in messages" :key="index" class="message" :class="message.role">
          <div class="message-author">{{ message.role === 'user' ? '我' : activeAgent.name }}</div>
          <div class="message-body">
            <p>{{ message.content }}<span v-if="message.streaming" class="typing-caret" /></p>
            <div v-if="message.sources?.length" class="source-list">
              <span class="eyebrow">引用来源</span>
              <button v-for="source in message.sources" :key="source.title">
                {{ source.title }} <small>{{ Math.round((source.score || 0) * 100) }}%</small>
              </button>
            </div>
          </div>
        </article>
      </div>
      <ErrorAlert :message="error" />
      <form class="composer" @submit.prevent="send">
        <textarea v-model="input" rows="2" :placeholder="activeAgent.placeholder" @keydown.enter.exact.prevent="send" />
        <div>
          <span>SSE 实时传输 · {{ sessionId }}</span>
          <button class="primary-button" :disabled="sending || !input.trim()">
            {{ sending ? '生成中…' : '发送 ↗' }}
          </button>
        </div>
      </form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'

import ErrorAlert from '../components/ErrorAlert.vue'
import { useAuthStore } from '../stores/auth'
import { streamChat } from '../utils/sse'

interface Message {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  sources?: Array<{ title: string; score?: number }>
}

const auth = useAuthStore()
const currentAgent = ref<'customer' | 'advisor'>('customer')
const customerId = ref(auth.user?.role === '客户' ? auth.user.user_id : 3)
const input = ref('')
const sending = ref(false)
const error = ref('')
const messages = ref<Message[]>([])
const messagePane = ref<HTMLElement>()
const sessionId = `web-${Date.now().toString(36)}`
const agents = [
  {
    key: 'customer' as const,
    name: '客服 Agent',
    glyph: '问',
    description: '产品问答与政策解释',
    model: 'RAG · 多轮记忆',
    welcome: '今天想了解什么？',
    prompt: '我会基于公司知识库回答，并明确标注信息来源。',
    placeholder: '例如：我有50万，希望稳健投资…',
    hints: ['我有50万，希望稳健投资', '稳健型产品有哪些风险？', '理财产品和基金有什么区别？'],
  },
  {
    key: 'advisor' as const,
    name: '投顾 Agent',
    glyph: '策',
    description: '画像、持仓与配置建议',
    model: 'GraphRAG · Tool Calling',
    welcome: '开始一轮专业投顾分析',
    prompt: '指定客户后，我会调用画像、持仓、推荐与知识图谱工具。',
    placeholder: '例如：分析客户持仓并生成推荐方案…',
    hints: ['分析该客户的持仓风险', '推荐3款适配产品', '生成一份资产配置建议'],
  },
]
const availableAgents = computed(() =>
  auth.user?.role === '客户' ? agents : agents,
)
const activeAgent = computed(() => agents.find((item) => item.key === currentAgent.value)!)

async function send() {
  const content = input.value.trim()
  if (!content || sending.value) return
  messages.value.push({ role: 'user', content })
  input.value = ''
  error.value = ''
  sending.value = true
  const response: Message = { role: 'assistant', content: '', streaming: true, sources: [] }
  messages.value.push(response)
  await nextTick()
  messagePane.value?.scrollTo({ top: messagePane.value.scrollHeight, behavior: 'smooth' })
  try {
    const path = currentAgent.value === 'customer' ? '/chat/customer/stream' : '/chat/advisor/stream'
    const body =
      currentAgent.value === 'customer'
        ? { session_id: sessionId, user_id: auth.user?.user_id, message: content }
        : { session_id: sessionId, customer_id: customerId.value, user_id: auth.user?.user_id, message: content }
    await streamChat(path, body, (event) => {
      if (event.event === 'delta') response.content += event.data.content || ''
      if (event.event === 'sources') response.sources = event.data.sources || []
      if (event.event === 'done') response.streaming = false
      nextTick(() => messagePane.value?.scrollTo({ top: messagePane.value!.scrollHeight }))
    })
  } catch (reason) {
    response.streaming = false
    error.value = reason instanceof Error ? reason.message : 'Agent 请求失败'
  } finally {
    sending.value = false
  }
}
</script>
