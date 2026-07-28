<template>
  <article class="message-card" :class="message.role">
    <div class="message-avatar">{{ message.role === 'user' ? '您' : 'AI' }}</div>
    <div class="message-content">
      <div class="message-meta">
        <span v-if="message.response">{{ agentName }} · 置信度 {{ confidence }}%</span>
      </div>
      <p v-if="message.role === 'user'">{{ message.content }}</p>
      <div v-else class="assistant-markdown" v-html="assistantHtml" />
      <!-- 风评问卷入口：回复中包含 profile_not_found 或 notice 文案时渲染 -->
      <div v-if="showAssessmentCta" class="assessment-inline-cta">
        <span>您的风评问卷不存在，请尽快填写风评，以便获得更精准的推荐</span>
        <button @click="emit('open-assessment')">填写风评问卷</button>
      </div>
      <!-- 数据查询结果表格 -->
      <div v-if="queryResult.length" class="data-table-preview">
        <div class="dt-preview-header">
          <span class="eyebrow">QUERY RESULT</span>
          <button class="text-button" @click="showTable = true">📋 查看全部 {{ queryResult.length }} 条</button>
        </div>
        <div class="dt-preview-table-wrap">
          <table>
            <thead><tr><th v-for="col in previewColumns" :key="col">{{ colLabel(col) }}</th></tr></thead>
            <tbody>
              <tr v-for="(row, i) in previewRows" :key="i">
                <td v-for="col in previewColumns" :key="col">{{ formatTableCell(row[col], col) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="queryResult.length > 5" class="dt-preview-more">
          … 还有 {{ queryResult.length - 5 }} 条
        </div>
      </div>
      <DataTableModal
        v-if="showTable"
        :rows="queryResult"
        :sql="querySql"
        title="数据查询结果"
        @close="showTable = false"
      />

      <!-- 风评失效：只有画像无法检索时后端才会返回 needs_assessment=true -->
      <!-- 此处不在聊天消息中展示该提示，统一由 AppLayout 的全局弹窗处理 -->
      <div v-if="message.response?.suggestions.length" class="action-suggestions">
        <span>{{ message.response.agent === 'router' ? '请选择你的目标' : '推荐操作' }}</span>
        <button
          v-for="suggestion in message.response.suggestions"
          :key="suggestion"
          type="button"
          @click="emit('select-suggestion', suggestion)"
        >
          {{ suggestion }}
        </button>
      </div>
      <small v-if="message.isMock" class="mock-notice">演示数据 · 接入金融 Agent 后将显示实时结果</small>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import DataTableModal from './DataTableModal.vue'
import type { ChatMessage } from '../stores/conversation'
import { renderAssistantMarkdown } from '../utils/markdown'
import { formatTableCell } from '../utils/table-format'

const props = defineProps<{ message: ChatMessage }>()
const emit = defineEmits<{
  'open-assessment': []
  'select-suggestion': [suggestion: string]
}>()

const agentNames: Record<string, string> = {
  investment: '投资建议引擎',
  risk: '风险评估引擎',
  operations: '账户服务引擎',
  service: '产品服务引擎',
  router: '需求澄清助手',
  router_supervisor: '多任务协调器',
}
const agentName = computed(() => agentNames[props.message.response?.agent || ''] || '金融智能引擎')
const confidence = computed(() => Math.round((props.message.response?.confidence || 0) * 100))
const assistantHtml = computed(() => renderAssistantMarkdown(props.message.content))

// 风评问卷入口：回复中包含 profile_not_found 或"风评问卷入口"文案时显示
const showAssessmentCta = computed(() => {
  const content = props.message.content || ''
  const status = (props.message.response as any)?.status
  const notice = (props.message.response as any)?.notice || ''
  return status === 'profile_not_found'
    || content.includes('风评问卷入口')
    || notice.includes('风评问卷')
})

// 数据查询结果（从 normalizeStreamResponse 透传的 _queryResult / _sql）
const showTable = ref(false)
const queryResult = computed<any[]>(() => (props.message.response as any)?._queryResult || [])
const querySql = computed(() => (props.message.response as any)?._sql || '')

const COLUMN_ALIAS: Record<string, string> = {
  id: '编号', username: '用户名', real_name: '姓名', user_type: '客户类型',
  employee_role: '员工角色', customer_level: '客户等级', phone: '手机号',
  email: '邮箱', status: '状态', balance: '账户余额', age: '年龄',
  education: '学历', occupation: '职业', create_time: '创建时间',
  update_time: '更新时间', total_assets: '总资产', risk_level: '风险等级',
  product_name: '产品名称', product_type: '产品类型', shares: '持有份额',
  current_value: '当前市值', profit_loss: '盈亏', profit_ratio: '收益率',
  transaction_type: '交易类型', amount: '交易金额',
}

function colLabel(key: string): string {
  return COLUMN_ALIAS[key] || key.replace(/_/g, ' ')
}

const previewColumns = computed(() => {
  if (!queryResult.value.length) return []
  return Object.keys(queryResult.value[0]).filter(k => !['password_hash', 'password', 'salt', 'secret'].includes(k)).slice(0, 6)
})
const previewRows = computed(() => queryResult.value.slice(0, 5))
</script>

<style scoped>
.assistant-markdown :deep(h1),
.assistant-markdown :deep(h2),
.assistant-markdown :deep(h3) { margin: 16px 0 8px; color: #eef6ff; line-height: 1.35; }
.assistant-markdown :deep(h1) { font-size: 16px; }
.assistant-markdown :deep(h2) { font-size: 15px; }
.assistant-markdown :deep(h3) { font-size: 13px; }
.assistant-markdown :deep(p) { margin: 0 0 8px; color: #c9d5e5; font-size: 13px; line-height: 1.75; white-space: pre-wrap; word-break: break-word; }
.assistant-markdown :deep(ul),
.assistant-markdown :deep(ol) { margin: 8px 0 12px; padding-left: 22px; color: #c9d5e5; line-height: 1.8; }
.assistant-markdown :deep(blockquote) { margin: 10px 0; padding-left: 12px; border-left: 3px solid #397ca9; color: #aebfd2; line-height: 1.75; }
.assistant-markdown :deep(code) { padding: 1px 5px; border-radius: 4px; color: #bae6fd; background: #0d263e; font-family: Consolas, monospace; }
.assistant-markdown :deep(hr) { border: 0; border-top: 1px solid #31516d; margin: 14px 0; }
.assistant-markdown :deep(strong) { color: #e1f3ff; }

/* 风评失效/不存在入口 */
.assessment-inline-cta {
  margin-top: 14px;
  padding: 14px 16px;
  border: 1px solid rgba(245,158,11,.35);
  border-radius: 10px;
  background: rgba(245,158,11,.07);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.assessment-inline-cta span {
  color: #fcd58a;
  font-size: 13px;
  font-weight: 500;
}
.assessment-inline-cta button {
  padding: 8px 14px;
  border: 1px solid #0b7f78;
  border-radius: 8px;
  color: #fff;
  background: #0b7f78;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: background .2s;
}
.assessment-inline-cta button:hover {
  background: #086f69;
}

/* 数据表格预览 */
.data-table-preview {
  margin-top: 14px;
  border: 1px solid #1e293b;
  border-radius: 10px;
  overflow: hidden;
}
.dt-preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: #0a1525;
  border-bottom: 1px solid #1e293b;
}
.dt-preview-header .eyebrow { font-size: 9px; }
.dt-preview-header .text-button {
  padding: 4px 10px;
  border: 1px solid #334155;
  border-radius: 6px;
  color: #94a3b8;
  background: transparent;
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
}
.dt-preview-header .text-button:hover {
  border-color: #38bdf8;
  color: #bae6fd;
}
.dt-preview-table-wrap { overflow-x: auto; }
.dt-preview-table-wrap table { min-width: 600px; width: 100%; border-collapse: collapse; font-size: 11px; }
.dt-preview-table-wrap th {
  padding: 7px 10px; text-align: left;
  color: #64748b; background: #0d1a2a;
  font-weight: 600; white-space: nowrap;
  border-bottom: 1px solid #1e293b;
}
.dt-preview-table-wrap td {
  padding: 6px 10px; color: #c9d5e5;
  border-bottom: 1px solid #1a273a;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dt-preview-more {
  padding: 8px 14px; text-align: center;
  color: #4a5a70; font-size: 11px;
  background: #0a1525;
}
</style>
