<template>
  <div class="page-stack">
    <section class="page-intro">
      <div><h2>用户画像</h2><p>聚合基础属性、风险偏好、投资经验和行为信号。</p></div>
      <form v-if="auth.user?.role !== '客户'" class="inline-search" @submit.prevent="load">
        <input v-model.number="customerId" type="number" min="1" placeholder="客户 ID" />
        <button class="primary-button">查询画像</button>
      </form>
      <div v-else class="profile-lock">当前登录用户 · ID {{ customerId }}<i /> 数据已锁定</div>
    </section>
    <ErrorAlert :message="error" />
    <LoadingPanel v-if="loading" />
    <template v-else-if="profile">
      <section class="profile-hero">
        <div class="avatar-orbit"><span>{{ String(profile.customer_id).padStart(2, '0') }}</span></div>
        <div><h2>{{ formatRiskLevel(profile.risk_level) }}</h2><p>{{ profile.investment_experience || '暂无' }}投资经验 · 年收入 {{ profile.annual_income_range || '待补充' }}</p></div>
        <div class="risk-seal" :data-level="profile.risk_flag"><span>风险标记</span><strong>{{ riskFlagLabel }}</strong></div>
      </section>
      <section class="metric-grid profile-metric-grid">
        <article><span>综合风险分</span><strong>{{ profile.risk_score ?? '—' }}</strong><small>/ 100</small></article>
        <article><span>画像置信度</span><strong>{{ percent(profile.confidence_score) }}</strong><small>证据融合</small></article>
        <article><span>资产规模</span><strong>{{ money(profile.total_assets) }}</strong><small>总资产估值</small></article>
        <article><span>适配等级</span><strong>{{ riskProductLevel }}</strong><small>产品风险上限</small></article>
        <article class="aml-risk-card" :data-aml-level="profile.aml_risk_level">
          <span>AML风险等级</span>
          <strong>{{ amlRiskLabel }}</strong>
          <small>近30天预警: {{ profile.alert_count_30d ?? 0 }}条</small>
        </article>
      </section>
      <section class="two-column">
        <div class="surface-card">
          <div class="card-heading"><h3>四维度能力雷达</h3></div>
          <div ref="radarChartEl" class="radar-chart" />
        </div>
        <div class="surface-card">
          <div class="card-heading"><h3>关键研判标签</h3></div>
          <div class="tag-cloud">
            <span>{{ formatRiskLevel(profile.risk_level) }}</span>
            <span>{{ profile.investment_experience || '经验待补充' }}</span>
            <span>{{ profile.annual_income_range || '收入待补充' }}</span>
            <span>{{ Number(profile.total_assets || 0) >= 6_000_000 ? '高净值客户' : '零售客户' }}</span>
          </div>
          <div class="confidence-note"><strong>置信度说明</strong><p>画像由问卷、账户属性、历史持仓和交易行为共同校准。</p></div>
        </div>
      </section>
      <RiskScoreTrendChart :records="scoreHistory" />
    </template>
    <EmptyState v-else title="尚未加载画像" description="输入客户 ID 查询，或先完成风险测评。" />
  </div>
</template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { get } from '../api/http'
import EmptyState from '../components/EmptyState.vue'
import ErrorAlert from '../components/ErrorAlert.vue'
import LoadingPanel from '../components/LoadingPanel.vue'
import RiskScoreTrendChart, { type RiskScoreHistoryRecord } from '../components/RiskScoreTrendChart.vue'
import { useAuthStore } from '../stores/auth'
import { onProfileUpdated } from '../utils/profile-events'

const auth = useAuthStore()
const customerId = ref(auth.user?.role === '客户' ? auth.user.user_id : 3)
const isCustomer = computed(() => auth.user?.role === '客户')
const loading = ref(false)
const error = ref('')
const profile = ref<Record<string, any> | null>(null)
const scoreHistory = ref<RiskScoreHistoryRecord[]>([])
const radarChartEl = ref<HTMLElement>()
let radarChart: echarts.ECharts | undefined
const riskFlagLabel = computed(() => {
  const labels: Record<string, string> = { high: '高关注', warning: '需关注', normal: '正常' }
  return labels[String(profile.value?.risk_flag || '')] || '正常'
})
const amlRiskLabel = computed(() => {
  const labels: Record<string, string> = { high: '高', medium: '中', low: '低' }
  return labels[String(profile.value?.aml_risk_level || '')] || '低'
})
const riskProductLevel = computed(() => {
  const levels: Record<string, string> = {
    c1: 'R1', C1: 'R1',
    c2: 'R2', C2: 'R2',
    c3: 'R3', C3: 'R3',
    c4: 'R4', C4: 'R4',
    c5: 'R5', C5: 'R5',
    保守型: 'R1', 稳健型: 'R2', 平衡型: 'R3', 进取型: 'R4', 激进型: 'R5',
  }
  return levels[String(profile.value?.risk_level || '')] || '—'
})

const money = (value: unknown) => value ? `¥${(Number(value) / 10_000).toFixed(1)}万` : '—'
const percent = (value: unknown) => value ? `${Math.round(Number(value) * 100)}%` : '—'

// 风险等级映射：c1/c2/c3/c4/c5 → C1保守型/C2稳健型/C3平衡型/C4进取型/C5激进型
const RISK_LEVEL_DISPLAY: Record<string, string> = {
  c1: 'C1保守型', C1: 'C1保守型',
  c2: 'C2稳健型', C2: 'C2稳健型',
  c3: 'C3平衡型', C3: 'C3平衡型',
  c4: 'C4进取型', C4: 'C4进取型',
  c5: 'C5激进型', C5: 'C5激进型',
}
function formatRiskLevel(level: unknown): string {
  if (!level) return '待评估'
  return RISK_LEVEL_DISPLAY[String(level)] || String(level)
}

function renderRadarChart() {
  if (!radarChartEl.value || !profile.value) return
  if (!radarChart) {
    radarChart = echarts.init(radarChartEl.value)
  }
  // 容器可能被 v-if/v-else 重建，需检查尺寸
  if (!radarChartEl.value.offsetWidth) return
  const dims = [
    { label: '基础属性', value: Number(profile.value.basic_score || 0) },
    { label: '投资经验', value: Number(profile.value.experience_score || 0) },
    { label: '风险偏好', value: Number(profile.value.risk_pref_score || 0) },
    { label: '行为稳定', value: Number(profile.value.behavior_score || 0) },
  ]
  // 各维度满分不同：基础属性25、投资经验25、风险偏好30、行为稳定20
  const maxScores = [25, 25, 30, 20]
  radarChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: '#111827', borderColor: '#30415a', textStyle: { color: '#e5edf9' },
      formatter: () => dims.map(d => `${d.label}：${d.value}`).join('<br/>'),
    },
    radar: {
      indicator: dims.map((d, i) => ({ name: d.label, max: maxScores[i] })),
      shape: 'polygon',
      splitNumber: 4,
      radius: '65%',
      axisName: { color: '#aebed2', fontSize: 12 },
      splitLine: { lineStyle: { color: '#223047' } },
      splitArea: { show: true, areaStyle: { color: ['rgba(56,189,248,0.02)', 'rgba(56,189,248,0.05)'] } },
      axisLine: { lineStyle: { color: '#31445d' } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: dims.map(d => d.value),
        name: '四维度能力',
        areaStyle: { color: 'rgba(56,189,248,0.25)' },
        lineStyle: { color: '#38bdf8', width: 2 },
        itemStyle: { color: '#7dd3fc' },
        symbol: 'circle',
        symbolSize: 6,
      }],
    }],
  }, true)
  radarChart.resize()
}

async function load() {
  if (isCustomer.value && auth.user?.user_id) customerId.value = auth.user.user_id
  if (!customerId.value) {
    error.value = '未识别当前登录用户，无法加载用户画像'
    return
  }
  loading.value = true
  error.value = ''
  try {
    profile.value = await get(`/profile/${customerId.value}`)
    try {
      scoreHistory.value = await get<RiskScoreHistoryRecord[]>(`/profile/${customerId.value}/score-history`)
    } catch {
      scoreHistory.value = []
    }
  } catch (reason) {
    profile.value = null
    error.value = reason instanceof Error ? reason.message : '画像加载失败'
    scoreHistory.value = []
  } finally {
    loading.value = false
  }
}

let stopProfileUpdates = () => {}
onMounted(() => {
  void load()
  window.addEventListener('resize', () => radarChart?.resize())
  stopProfileUpdates = onProfileUpdated((updatedCustomerId) => {
    if (updatedCustomerId === customerId.value) void load()
  })
})
onBeforeUnmount(() => {
  stopProfileUpdates()
  window.removeEventListener('resize', () => radarChart?.resize())
  radarChart?.dispose()
})
watch(profile, async (newProfile) => {
  if (newProfile) {
    // 等待 DOM 更新（v-else-if="profile" 切换后 radarChartEl 才可用）
    await nextTick()
    renderRadarChart()
    // 兜底：若首次渲染时容器尺寸还未就绪，再尝试一次
    setTimeout(() => renderRadarChart(), 80)
  } else {
    radarChart?.dispose()
    radarChart = undefined
  }
})
</script>

<style scoped>
.profile-hero h2 { font-size: 32px; }
.radar-chart { width: 100%; height: 300px; }
</style>
