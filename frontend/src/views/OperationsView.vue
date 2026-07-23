<template>
  <div class="page-stack">
    <section class="page-intro">
      <div><span class="eyebrow">NL2API CONTROL</span><h2>用自然语言完成业务操作</h2><p>Agent 负责参数提取、角色校验、二次确认和真实业务 API 调用。</p></div>
      <span class="security-chip">JWT 角色已绑定</span>
    </section>
    <section class="operation-console">
      <div class="operation-examples">
        <span class="eyebrow">快捷示例</span>
        <button v-for="hint in hints" :key="hint" @click="message = hint">{{ hint }}</button>
      </div>
      <div class="terminal-window">
        <header><span /><span /><span /><strong>BUSINESS OPERATOR AGENT</strong></header>
        <div class="terminal-content">
          <article v-for="(entry, index) in history" :key="index" :class="entry.role">
            <span>{{ entry.role === 'user' ? 'YOU' : 'AGENT' }}</span>
            <p>{{ entry.text }}</p>
            <pre v-if="entry.meta">{{ JSON.stringify(entry.meta, null, 2) }}</pre>
          </article>
          <div v-if="!history.length" class="terminal-empty">输入业务指令。高金额操作会暂停并等待明确确认。</div>
        </div>
        <ErrorAlert :message="error" />
        <form @submit.prevent="send"><input v-model="message" placeholder="帮演示客户01申购演示基金01号，金额5000元" /><button :disabled="loading">{{ loading ? '执行中' : '发送指令' }}</button></form>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import { post } from '../api/http'
import ErrorAlert from '../components/ErrorAlert.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const sessionId = `operator-${Date.now().toString(36)}`
const message = ref('')
const loading = ref(false)
const error = ref('')
const history = ref<Array<{ role: 'user' | 'assistant'; text: string; meta?: unknown }>>([])
const hints = ['查询R2风险等级的产品', '查询演示客户01的持仓', '为演示客户02创建咨询工单', '确认']

async function send() {
  const text = message.value.trim()
  if (!text || loading.value) return
  history.value.push({ role: 'user', text })
  message.value = ''
  loading.value = true
  error.value = ''
  try {
    const result = await post<Record<string, any>>('/chat/operator', {
      message: text,
      session_id: sessionId,
      user_id: auth.user?.user_id,
    })
    history.value.push({ role: 'assistant', text: result.reply || '操作完成', meta: result.action ? { action: result.action, params: result.params, status: result.status } : undefined })
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '业务操作失败'
  } finally {
    loading.value = false
  }
}
</script>
