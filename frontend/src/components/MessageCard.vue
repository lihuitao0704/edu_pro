<template>
  <article class="message-card" :class="message.role">
    <div class="message-avatar">{{ message.role === 'user' ? '您' : 'AI' }}</div>
    <div class="message-content">
      <div class="message-meta">
        <strong>{{ message.role === 'user' ? '您的提问' : 'AI 财富助手' }}</strong>
        <span v-if="message.response">{{ agentName }} · 置信度 {{ confidence }}%</span>
      </div>
      <p>{{ message.content }}</p>
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

const props = defineProps<{ message: ChatMessage }>()
const agentNames: Record<string, string> = {
  investment: '投资建议引擎',
  risk: '风险评估引擎',
  operations: '账户服务引擎',
  service: '产品服务引擎',
}
const agentName = computed(() => agentNames[props.message.response?.agent || ''] || '金融智能引擎')
const confidence = computed(() => Math.round((props.message.response?.confidence || 0) * 100))
</script>
