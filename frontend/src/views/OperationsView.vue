<template>
  <div class="page-stack">
    <section class="page-intro">
      <div><h2>用自然语言完成业务操作</h2><p>Agent 负责参数提取、角色校验、二次确认和真实业务 API 调用。</p></div>
      <span class="security-chip">JWT 角色已绑定</span>
    </section>
    <section class="ops-chat-window">
      <header class="ops-chat-header">
        <span><i /> BUSINESS OPERATOR AGENT</span>
        <b>受监管模式</b>
      </header>
      <div ref="bodyRef" class="ops-chat-body">
        <div v-if="!history.length" class="ops-empty-state">
          <span class="ops-orb">OP</span>
          <h3>输入业务指令开始操作</h3>
          <p>高金额操作会暂停并等待明确确认。</p>
          <div class="ops-quick-prompts">
            <button v-for="hint in hints" :key="hint" type="button" @click="sendHint(hint)">{{ hint }}</button>
          </div>
        </div>
        <div v-else class="ops-history">
          <article v-for="(entry, index) in history" :key="index" :class="entry.role">
            <div class="ops-msg-avatar">{{ entry.role === 'user' ? 'YOU' : 'OP' }}</div>
            <div class="ops-msg-body">
              <div class="ops-msg-meta">
                <strong>{{ entry.role === 'user' ? '您的指令' : 'Operator Agent' }}</strong>
              </div>
              <p>{{ entry.text }}</p>
              <pre v-if="entry.meta">{{ JSON.stringify(entry.meta, null, 2) }}</pre>
            </div>
          </article>
        </div>
      </div>
      <ErrorAlert v-if="error" :message="error" class="ops-error" />
      <form class="ops-composer" @submit.prevent="send">
        <div class="composer-row">
          <textarea v-model="message" rows="1" placeholder="输入业务指令…" @keydown.enter.exact.prevent="send" />
          <button class="finance-primary" :disabled="!message.trim() || loading">{{ loading ? '执行中' : '发送指令' }}</button>
        </div>
        <span class="composer-hint">高金额操作需二次确认 · JWT 角色已绑定</span>
      </form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import { post } from '../api/http'
import ErrorAlert from '../components/ErrorAlert.vue'
import { useAuthStore } from '../stores/auth'

// ---- 模块级状态：跨路由导航保持会话记忆 ----
const sessionId = `operator-${Date.now().toString(36)}`
const history = ref<Array<{ role: 'user' | 'assistant'; text: string; meta?: unknown }>>([])

const auth = useAuthStore()
const message = ref('')
const loading = ref(false)
const error = ref('')
const bodyRef = ref<HTMLElement>()
const hints = ['查询R2风险等级的产品', '查询演示客户01的持仓', '为演示客户02创建咨询工单', '确认']

// 自动滚动到底部
watch(history, () => {
  nextTick(() => {
    bodyRef.value?.scrollTo({ top: bodyRef.value.scrollHeight, behavior: 'smooth' })
  })
}, { deep: true })

function sendHint(hint: string) {
  message.value = hint
  send()
}

async function send() {
  const text = message.value.trim()
  if (!text || loading.value) return
  history.value.push({ role: 'user', text })
  message.value = ''
  loading.value = true
  error.value = ''
  try {
    const result = await post<Record<string, any>>('/chat', {
      message: text,
      session_id: sessionId,
      user_id: auth.user?.user_id,
      user_role: auth.user?.role || '理财顾问',
    })
    const reply = result.data?.reply || result.reply || '操作完成'
    const meta = result.data?.data || result.data
    // 后端可能返回新的 session_id
    if (result.data?.session_id) Object.assign(window, { _opsSession: result.data.session_id })
    history.value.push({ role: 'assistant', text: reply, meta: meta?.action ? { action: meta.action, params: meta.params, status: meta.status } : undefined })
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '业务操作失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.page-stack {
  height: calc(100vh - 130px);
  display: flex;
  flex-direction: column;
}
.page-intro { flex: 0 0 auto; }
.ops-chat-window {
  flex: 1;
  min-height: 0;
  border: 1px solid var(--finance-line, #263247);
  border-radius: 16px;
  background: linear-gradient(145deg, rgba(21,31,49,.94), rgba(14,22,36,.94));
  box-shadow: 0 20px 55px rgba(0,0,0,.16);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ops-chat-header {
  min-height: 48px;
  padding: 10px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--finance-line, #263247);
  flex-shrink: 0;
}
.ops-chat-header span {
  color: #94a3b8;
  font-size: 11px;
  letter-spacing: .08em;
}
.ops-chat-header i {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 6px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 0 4px rgba(52,211,153,.1);
}
.ops-chat-header b {
  padding: 6px 10px;
  border: 1px solid rgba(52,211,153,.26);
  border-radius: 99px;
  color: #34d399;
  background: rgba(52,211,153,.06);
  font-size: 11px;
  font-weight: 600;
}
.ops-chat-body {
  flex: 1;
  min-height: 0;
  padding: 24px clamp(12px, 3vw, 48px);
  overflow-y: auto;
  background: rgba(6,12,24,.32);
}
.ops-empty-state {
  max-width: 520px;
  margin: 3vh auto 0;
  text-align: center;
}
.ops-orb {
  width: 44px;
  height: 44px;
  margin: auto;
  display: grid;
  place-items: center;
  border: 1px solid #3b82f6;
  border-radius: 13px;
  color: #93c5fd;
  background: linear-gradient(135deg, #1e3a5f, #1e2d50);
  font-weight: 800;
  font-size: 15px;
  letter-spacing: .06em;
}
.ops-empty-state h3 {
  margin: 12px 0 6px;
  color: #eef6ff;
  font-size: 18px;
  font-weight: 600;
}
.ops-empty-state > p {
  margin: 0;
  color: #8d9bb1;
  font-size: 12px;
  line-height: 1.6;
}
.ops-quick-prompts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 14px;
}
.ops-quick-prompts button {
  min-height: 38px;
  padding: 8px 12px;
  border: 1px solid var(--finance-line, #263247);
  border-radius: 8px;
  color: #94a3b8;
  background: #121c2c;
  font-size: 11px;
  text-align: left;
  cursor: pointer;
  transition: border-color .2s, color .2s, background .2s;
}
.ops-quick-prompts button:hover {
  border-color: #3b82f6;
  color: #dbeafe;
  background: #16263c;
}
.ops-history {
  display: grid;
  gap: 16px;
}
.ops-history article {
  max-width: 780px;
  display: flex;
  gap: 10px;
}
.ops-history article.user {
  margin-left: auto;
  flex-direction: row-reverse;
}
.ops-msg-avatar {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 1px solid #32628c;
  border-radius: 8px;
  color: #bae6fd;
  background: #123150;
  font-size: 10px;
  font-weight: 700;
}
.ops-history article.user .ops-msg-avatar {
  border-color: #4a3d74;
  color: #ddd6fe;
  background: #2c2350;
}
.ops-msg-body {
  flex: 1;
  padding: 11px 14px;
  border: 1px solid var(--finance-line, #263247);
  border-radius: 4px 12px 12px;
  background: #131d2d;
}
.ops-history article.user .ops-msg-body {
  border-radius: 12px 4px 12px 12px;
  background: #1a2840;
}
.ops-msg-meta {
  margin-bottom: 4px;
}
.ops-msg-meta strong {
  color: #dce9f9;
  font-size: 11px;
}
.ops-msg-body > p {
  margin: 0;
  color: #c9d5e5;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.ops-msg-body pre {
  margin: 8px 0 0;
  padding: 8px;
  overflow: auto;
  border-radius: 6px;
  color: #94a3b8;
  background: rgba(255,255,255,.04);
  font-size: 10px;
  max-height: 160px;
}
.ops-error {
  margin: 0 16px;
  flex-shrink: 0;
}
.ops-composer {
  padding: 10px 16px;
  border-top: 1px solid var(--finance-line, #263247);
  background: #101827;
  flex-shrink: 0;
}
</style>
