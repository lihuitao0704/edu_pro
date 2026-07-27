<template>
  <div class="page-stack">
    <section class="page-intro">
      <div><h2>业务办理与审批</h2><p>仅处理会修改业务数据的指令；查询、推荐与分析请使用 AI 财富助手。</p></div>
      <div class="ops-intro-actions">
        <router-link class="quiet-button" to="/chat">前往 AI 财富助手</router-link>
        <span class="security-chip">JWT 角色已绑定</span>
      </div>
    </section>
    <section class="ops-chat-window">
      <header class="ops-chat-header">
        <span><i /> OPERATION APPROVAL CENTER</span>
        <b>受监管 · 可审计</b>
      </header>
      <div ref="bodyRef" class="ops-chat-body">
        <div v-if="!history.length" class="ops-empty-state">
          <span class="ops-orb">OP</span>
          <h3>发起一项业务办理</h3>
          <p>系统将校验权限和参数；高金额操作会暂停并等待明确确认。</p>
          <div class="ops-quick-prompts">
            <button v-for="hint in hints" :key="hint" type="button" @click="sendHint(hint)">{{ hint }}</button>
          </div>
        </div>
        <div v-else class="ops-history">
          <article v-for="(entry, index) in history" :key="index" :class="entry.role">
            <div class="ops-msg-avatar">{{ entry.role === 'user' ? 'YOU' : 'OP' }}</div>
            <div class="ops-msg-body">
              <div class="ops-msg-meta">
                <strong>{{ entry.role === 'user' ? '您的指令' : agentLabel(entry.agent) }}</strong>
                <span v-if="entry.status" class="ops-status" :class="entry.status">{{ statusLabel(entry.status) }}</span>
              </div>
              <p>{{ entry.text }}</p>
              <div v-if="entry.role === 'assistant' && (entry.intent || entry.action)" class="ops-result-meta">
                <span v-if="entry.intent">识别意图：{{ entry.intent }}</span>
                <span v-if="entry.action">业务动作：{{ entry.action }}</span>
              </div>
              <pre v-if="entry.params && Object.keys(entry.params).length">待办参数：{{ JSON.stringify(entry.params, null, 2) }}</pre>
            </div>
          </article>
        </div>
      </div>
      <ErrorAlert v-if="error" :message="error" class="ops-error" />
      <form class="ops-composer" @submit.prevent="send">
        <div class="composer-row">
          <textarea v-model="message" rows="1" placeholder="例如：给客户ID 1申购10万元产品 PROD-0001" @keydown.enter.exact.prevent="send" />
          <button class="finance-primary" :disabled="!message.trim() || loading">{{ loading ? '处理中' : '提交办理' }}</button>
        </div>
        <span class="composer-hint">申购、赎回、转账等高风险操作必须在同一会话中二次确认</span>
      </form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import { post } from '../api/http'
import ErrorAlert from '../components/ErrorAlert.vue'
import { useAuthStore } from '../stores/auth'

interface OperationEntry {
  role: 'user' | 'assistant'
  text: string
  agent?: string
  intent?: string
  action?: string
  status?: string
  params?: Record<string, unknown>
}

const sessionId = ref('')
const history = ref<OperationEntry[]>([])

const auth = useAuthStore()
const message = ref('')
const loading = ref(false)
const error = ref('')
const bodyRef = ref<HTMLElement>()
const hints = [
  '给客户ID 1申购10万元产品 PROD-0001',
  '帮客户ID 1赎回产品 PROD-0001 1000份',
  '为客户ID 1创建咨询工单',
  '确认',
]
const OPERATION_PATTERN = /(申购|赎回|转账|开户|创建.{0,8}工单|关闭.{0,8}工单|处理.{0,8}工单|更新.{0,8}(手机|邮箱|联系方式)|修改.{0,8}(手机|邮箱|联系方式)|风评重做|重新风险评估|批量更新|批量评估|上报.{0,6}(可疑|异常)|确认|确定|同意|取消|放弃)/
const AGENT_LABELS: Record<string, string> = {
  operator: '业务办理 Agent',
  router: '需求澄清助手',
  safety_guard: '安全与合规拦截',
}
const STATUS_LABELS: Record<string, string> = {
  confirm_required: '等待确认',
  note_required: '等待备注',
  ok: '处理完成',
  cancelled: '已取消',
  permission_denied: '权限不足',
  error: '处理失败',
}

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

function agentLabel(agent?: string) {
  return AGENT_LABELS[agent || ''] || agent || '业务协调器'
}

function statusLabel(status: string) {
  return STATUS_LABELS[status] || status
}

async function send() {
  const text = message.value.trim()
  if (!text || loading.value) return
  if (!OPERATION_PATTERN.test(text)) {
    error.value = '该页面仅办理会修改数据的业务。查询、推荐和分析请前往 AI 财富助手。'
    return
  }
  if (/^(确认|确定|同意|取消|放弃)$/.test(text) && !sessionId.value) {
    error.value = '当前没有待确认的业务，请先提交一项办理指令。'
    return
  }
  history.value.push({ role: 'user', text })
  message.value = ''
  loading.value = true
  error.value = ''
  try {
    const result = await post<Record<string, any>>('/chat', {
      message: text,
      session_id: sessionId.value,
      user_id: auth.user?.user_id,
      user_role: auth.user?.role || '理财顾问',
    })
    const reply = result.reply || '操作完成'
    const data = result.data && typeof result.data === 'object' ? result.data : {}
    if (result.session_id) sessionId.value = result.session_id
    history.value.push({
      role: 'assistant',
      text: reply,
      agent: result.agent,
      intent: result.intent,
      action: data.action,
      status: data.status,
      params: data.params,
    })
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
.ops-intro-actions { display: flex; align-items: center; gap: 10px; }
.ops-intro-actions .quiet-button { text-decoration: none; }
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.ops-msg-meta strong {
  color: #dce9f9;
  font-size: 11px;
}
.ops-status {
  padding: 2px 7px;
  border-radius: 99px;
  color: #a7f3d0;
  background: rgba(16, 185, 129, .12);
  font-size: 10px;
}
.ops-status.confirm_required,
.ops-status.note_required { color: #fde68a; background: rgba(245, 158, 11, .12); }
.ops-status.error,
.ops-status.permission_denied { color: #fecaca; background: rgba(239, 68, 68, .12); }
.ops-result-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin: 7px 0 0;
  color: #7f91a8;
  font-size: 10px;
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
