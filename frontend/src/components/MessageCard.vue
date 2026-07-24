<template>
  <article class="message-card" :class="message.role">
    <div class="message-avatar">{{ message.role === 'user' ? '您' : 'AI' }}</div>
    <div class="message-content">
      <div class="message-meta">
        <strong>{{ message.role === 'user' ? '您的提问' : 'AI 财富助手' }}</strong>
        <span v-if="message.response">{{ agentName }} · 置信度 {{ confidence }}%</span>
      </div>
      <p v-if="message.role === 'user'">{{ message.content }}</p>
      <div v-else class="assistant-markdown" v-html="assistantHtml" />
      <RecommendationCard
        v-if="message.response?.metadata.recommendation"
        :recommendation="message.response.metadata.recommendation"
      />
      <div v-if="message.response?.suggestions.length" class="action-suggestions">
        <span>推荐操作</span>
        <button v-for="suggestion in message.response.suggestions" :key="suggestion" type="button">
          {{ suggestion }}
        </button>
      </div>
      <small v-if="message.isMock" class="mock-notice">演示数据 · 接入金融 Agent 后将显示实时结果</small>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import RecommendationCard from './RecommendationCard.vue'
import type { ChatMessage } from '../stores/conversation'
import { renderAssistantMarkdown } from '../utils/markdown'

const props = defineProps<{ message: ChatMessage }>()
const agentNames: Record<string, string> = {
  investment: '投资建议引擎',
  risk: '风险评估引擎',
  operations: '账户服务引擎',
  service: '产品服务引擎',
}
const agentName = computed(() => agentNames[props.message.response?.agent || ''] || '金融智能引擎')
const confidence = computed(() => Math.round((props.message.response?.confidence || 0) * 100))
const assistantHtml = computed(() => renderAssistantMarkdown(props.message.content))
</script>

<style scoped>
.assistant-markdown :deep(h1),
.assistant-markdown :deep(h2),
.assistant-markdown :deep(h3) { margin: 16px 0 8px; color: #eef6ff; line-height: 1.35; }
.assistant-markdown :deep(h1) { font-size: 18px; }
.assistant-markdown :deep(h2) { font-size: 16px; }
.assistant-markdown :deep(h3) { font-size: 14px; }
.assistant-markdown :deep(p) { margin: 0 0 10px; color: #c9d5e5; font-size: 14px; line-height: 1.8; white-space: pre-wrap; word-break: break-word; }
.assistant-markdown :deep(ul),
.assistant-markdown :deep(ol) { margin: 8px 0 12px; padding-left: 22px; color: #c9d5e5; line-height: 1.8; }
.assistant-markdown :deep(blockquote) { margin: 10px 0; padding-left: 12px; border-left: 3px solid #397ca9; color: #aebfd2; line-height: 1.75; }
.assistant-markdown :deep(code) { padding: 1px 5px; border-radius: 4px; color: #bae6fd; background: #0d263e; font-family: Consolas, monospace; }
.assistant-markdown :deep(hr) { border: 0; border-top: 1px solid #31516d; margin: 14px 0; }
.assistant-markdown :deep(strong) { color: #e1f3ff; }
</style>
