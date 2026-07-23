<template>
  <div class="page-stack">
    <section class="page-intro">
      <div><span class="eyebrow">RISK COMMAND CENTER</span><h2>异常交易与工单联动</h2><p>预警、证据规则、客户风险标记和调查工单保持同步。</p></div>
      <button class="secondary-button" @click="loadAll">刷新数据</button>
    </section>
    <section class="risk-summary">
      <article><span>待处理预警</span><strong>{{ pendingCount }}</strong><i class="red" /></article>
      <article><span>高风险</span><strong>{{ highCount }}</strong><i class="amber" /></article>
      <article><span>处理中工单</span><strong>{{ activeOrders }}</strong><i class="blue" /></article>
    </section>
    <ErrorAlert :message="error" />
    <LoadingPanel v-if="loading" />
    <section v-else class="risk-layout">
      <div class="surface-card alert-table-card">
        <div class="card-heading"><span class="eyebrow">ALERT QUEUE</span><h3>风险预警队列</h3></div>
        <div class="data-table-wrap">
          <table>
            <thead><tr><th>等级</th><th>客户</th><th>触发规则</th><th>状态</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="alert in alerts" :key="alert.alert_id" :class="{ selected: selected?.alert_id === alert.alert_id }" @click="selected = alert">
                <td><span class="level-chip" :data-level="alert.alert_level">{{ levelLabel(alert.alert_level) }}</span></td>
                <td>#{{ alert.customer_id }}</td>
                <td>{{ alert.trigger_rules?.map((rule) => rule.rule_name || rule.rule_id).join('、') || alert.summary }}</td>
                <td>{{ alert.status }}</td>
                <td>{{ alert.created_at?.slice(0, 16).replace('T', ' ') }}</td>
              </tr>
            </tbody>
          </table>
          <EmptyState v-if="!alerts.length" title="当前没有风险预警" description="交易监测保持运行。" />
        </div>
      </div>
      <aside class="surface-card alert-detail">
        <template v-if="selected">
          <span class="eyebrow">ALERT #{{ selected.alert_id }}</span>
          <h3>{{ levelLabel(selected.alert_level) }}预警</h3>
          <p>{{ selected.summary }}</p>
          <div class="rule-stack">
            <span v-for="rule in selected.trigger_rules" :key="rule.rule_id"><b>{{ rule.rule_id }}</b>{{ rule.rule_name }}</span>
          </div>
          <label>处理备注<textarea v-model="handleNote" rows="4" placeholder="记录核实过程和结论" /></label>
          <div class="detail-actions">
            <button class="secondary-button" @click="handle('false_positive')">标记误报</button>
            <button class="primary-button" @click="handle('resolved')">确认处理</button>
          </div>
        </template>
        <EmptyState v-else title="选择一条预警" description="查看证据并推进工单处理。" />
      </aside>
    </section>
    <section class="surface-card">
      <div class="card-heading"><span class="eyebrow">WORK ORDERS</span><h3>关联调查工单</h3></div>
      <div class="workorder-strip">
        <article v-for="order in workorders.slice(0, 6)" :key="order.id">
          <span>{{ order.priority || '普通' }}</span><strong>{{ order.work_order_no }}</strong><p>客户 #{{ order.customer_id }} · {{ order.order_type }}</p><small>{{ order.status }}</small>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { get, put } from '../api/http'
import type { RiskAlert } from '../api/types'
import EmptyState from '../components/EmptyState.vue'
import ErrorAlert from '../components/ErrorAlert.vue'
import LoadingPanel from '../components/LoadingPanel.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const alerts = ref<RiskAlert[]>([])
const workorders = ref<any[]>([])
const selected = ref<RiskAlert | null>(null)
const handleNote = ref('')
const loading = ref(false)
const error = ref('')
const pendingCount = computed(() => alerts.value.filter((item) => !['resolved', 'false_positive'].includes(item.status)).length)
const highCount = computed(() => alerts.value.filter((item) => item.alert_level === 'high').length)
const activeOrders = computed(() => workorders.value.filter((item) => !['已完成', '已关闭'].includes(item.status)).length)
const levelLabel = (level: string) => ({ low: '低', medium: '中', high: '高' }[level] || level)

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [alertData, orderData] = await Promise.all([
      get<{ alerts: RiskAlert[] }>('/risk/alerts?page_size=100'),
      get<{ items: any[] }>('/operation/workorders?page_size=100'),
    ])
    alerts.value = alertData.alerts
    workorders.value = orderData.items
    if (selected.value) selected.value = alerts.value.find((item) => item.alert_id === selected.value?.alert_id) || null
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '风险数据加载失败'
  } finally {
    loading.value = false
  }
}

async function handle(action: 'resolved' | 'false_positive') {
  if (!selected.value) return
  try {
    await put(`/risk/alert/${selected.value.alert_id}/handle`, {
      action,
      handler_id: auth.user?.user_id,
      handle_note: handleNote.value,
    })
    handleNote.value = ''
    await loadAll()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '预警处理失败'
  }
}

onMounted(loadAll)
</script>
