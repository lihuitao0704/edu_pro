<template>
  <div class="dashboard-page">
    <section class="finance-page-intro dashboard-intro">
      <div>
        <h1>金融智能运营中心</h1>
        <p>业务汇总、服务健康和当前账户可见的 Agent 执行链路均来自实时接口。</p>
      </div>
      <div class="dashboard-live" :class="{ degraded: healthStatus === 'degraded' }">
        <i /> {{ healthLabel }} <small>{{ updatedAt || '等待刷新' }}</small>
      </div>
    </section>

    <section class="dashboard-metrics">
      <DashboardCard v-for="metric in platformMetrics" :key="metric.label" v-bind="metric" />
    </section>

    <section class="agent-directory-section">
      <header class="panel-title-row">
        <div><h2>Agent 能力目录</h2></div>
        <span class="demo-data-badge">演示布局 · 非实时运行指标</span>
      </header>
      <div class="agent-directory"><AgentCard v-for="agent in agentDirectory" :key="agent.code" :agent="agent" /></div>
    </section>

    <section class="dashboard-main-grid">
      <AgentTrace :nodes="executionTrace" />
      <RiskPanel :total-alerts="summary.total_alerts || 0" :distribution="alertDistribution" />
    </section>

    <section class="analytics-section">
      <header class="panel-title-row"><div><h2>经营与服务洞察</h2></div><span class="data-freshness">来源：实时业务库聚合</span></header>
      <div class="chart-grid">
        <ChartPanel title="月度交易趋势" eyebrow="TRANSACTION VOLUME" caption="近 12 月" :option="trendOption" />
        <ChartPanel title="风险预警分布" eyebrow="RISK ALERTS" caption="当前累计" :option="pieOption" />
        <ChartPanel title="在售产品平均收益" eyebrow="PRODUCT SHELF" caption="按风险等级" :option="returnOption" />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { EChartsOption } from 'echarts'
import { computed, onMounted, ref } from 'vue'

import { get } from '../api/http'
import AgentCard from '../components/AgentCard.vue'
import AgentTrace from '../components/AgentTrace.vue'
import ChartPanel from '../components/ChartPanel.vue'
import DashboardCard from '../components/DashboardCard.vue'
import RiskPanel from '../components/RiskPanel.vue'
import { agentDirectory } from '../mocks/platform'

const dashboardData = ref<Record<string, any>>({})
const healthData = ref<Record<string, any>>({})
const traceItems = ref<Array<Record<string, any>>>([])
const updatedAt = ref('')

const summary = computed(() => dashboardData.value.summary || {})
const alertDistribution = computed(() => dashboardData.value.alert_distribution || [])
const returnByRisk = computed(() => dashboardData.value.return_by_risk || [])

const platformMetrics = computed(() => [
  { label: '服务客户', value: Number(summary.value.total_customers || 0).toLocaleString('zh-CN'), trend: '来自客户画像汇总', tone: 'blue' },
  { label: '客户资产', value: formatCurrency(Number(summary.value.total_aum || 0)), trend: '来自当前画像资产', tone: 'violet' },
  { label: '风险预警', value: Number(summary.value.total_alerts || 0).toLocaleString('zh-CN'), trend: '包含全部状态', tone: 'red' },
  { label: '在售产品', value: Number(summary.value.in_sale_products || 0).toLocaleString('zh-CN'), trend: '来自产品货架', tone: 'cyan' },
])

const healthStatus = computed(() => healthData.value.status || 'unknown')
const healthLabel = computed(() => {
  if (healthStatus.value === 'healthy') return '核心服务检查正常'
  if (healthStatus.value === 'degraded') return '部分核心服务异常'
  return '核心服务状态暂不可用'
})

const executionTrace = computed(() => traceItems.value.slice(0, 6).map(item => ({
  name: item.agent_name || 'Agent',
  action: `会话 ${item.session_id || '—'} · ${item.status || 'unknown'}`,
  duration: item.created_time ? new Date(item.created_time).toLocaleTimeString('zh-CN', { hour12: false }) : '—',
  result: item.status === 'processing' ? 'processing' as const : 'success' as const,
})))

function formatCurrency(value: number): string {
  if (value >= 1e8) return `¥${(value / 1e8).toFixed(1)}亿`
  if (value >= 1e4) return `¥${(value / 1e4).toFixed(1)}万`
  return `¥${value.toLocaleString('zh-CN')}`
}

async function loadDashboard() {
  const [businessResult, healthResult, traceResult] = await Promise.allSettled([
    get<Record<string, any>>('/analytics/bi/dashboard'),
    get<Record<string, any>>('/admin/health'),
    get<{ items: Array<Record<string, any>> }>('/analytics/chat/traces'),
  ])
  if (businessResult.status === 'fulfilled') dashboardData.value = businessResult.value?.data || businessResult.value || {}
  if (healthResult.status === 'fulfilled') healthData.value = healthResult.value?.data || healthResult.value || {}
  if (traceResult.status === 'fulfilled') {
    const traceData = traceResult.value
    traceItems.value = traceData.items || []
  }
  updatedAt.value = new Date().toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => { void loadDashboard() })

const axisStyle = { axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: '#1e293b' } } }
const trendOption = computed<EChartsOption>(() => {
  const totals = new Map<string, number>()
  ;(dashboardData.value.monthly_trend || []).forEach((row: Record<string, any>) => {
    totals.set(row.month, (totals.get(row.month) || 0) + Number(row.tx_count || 0))
  })
  return {
    grid: { left: 36, right: 14, top: 20, bottom: 24 },
    tooltip: { trigger: 'axis', backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e2e8f0' } },
    xAxis: { type: 'category', data: [...totals.keys()], ...axisStyle },
    yAxis: { type: 'value', ...axisStyle },
    series: [{ type: 'line', smooth: true, data: [...totals.values()], symbol: 'none', lineStyle: { color: '#38bdf8', width: 3 }, areaStyle: { color: 'rgba(56,189,248,.16)' } }],
  }
})
const pieOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'item', backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e2e8f0' } },
  series: [{
    type: 'pie',
    radius: ['48%', '72%'],
    label: { color: '#94a3b8', formatter: '{b}\n{d}%' },
    labelLine: { lineStyle: { color: '#475569' } },
    itemStyle: { borderColor: '#0f172a', borderWidth: 4 },
    data: alertDistribution.value.map((item: any) => ({ name: item.label || item.name, value: item.count })),
    color: ['#fb7185', '#f59e0b', '#38bdf8'],
  }],
}))
const returnOption = computed<EChartsOption>(() => ({
  grid: { left: 36, right: 14, top: 20, bottom: 24 },
  tooltip: { trigger: 'axis', backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e2e8f0' } },
  xAxis: { type: 'category', data: returnByRisk.value.map((item: any) => item.name), ...axisStyle },
  yAxis: { type: 'value', ...axisStyle },
  series: [{ type: 'bar', data: returnByRisk.value.map((item: any) => Number(item.avg_return || 0)), itemStyle: { color: '#a78bfa' } }],
}))
</script>

<style scoped>
.dashboard-live.degraded {
  color: #fecaca;
  border-color: rgba(248, 113, 113, .35);
  background: rgba(248, 113, 113, .08);
}
.dashboard-live.degraded i { background: #f87171; }
.demo-data-badge { color: #fcd58a; font-size: 11px; }
</style>
