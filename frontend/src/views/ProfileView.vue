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
        <div><h2>{{ formatRiskLevelPure(profile.risk_level) }}</h2><p>{{ profile.investment_experience || '暂无' }}投资经验 · 年收入 {{ profile.annual_income_range || '待补充' }}</p></div>
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
          <div class="card-heading split"><h3>四维度能力雷达</h3><span v-if="profile?.update_time" class="stale-note">评估时间：{{ new Date(profile.update_time).toLocaleDateString('zh-CN') }}</span></div>
          <div v-if="hasRadarData" ref="radarChartEl" class="radar-chart" />
          <div v-if="hasRadarData && isProfileStale" class="stale-warning">⚠ 评估数据已超过30天，建议重新测评以确保画像准确</div>
          <div v-else-if="!hasRadarData" class="radar-empty">暂无评估数据，请先完成风险测评</div>
        </div>
        <div class="surface-card">
          <div class="card-heading"><h3>关键研判标签</h3></div>
          <div class="tag-cloud">
            <span>{{ formatRiskLevelPure(profile.risk_level) }}</span>
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

const hasRadarData = computed(() => {
  const currentProfile = profile.value
  if (!currentProfile) return false
  const dims = ['basic_score', 'experience_score', 'risk_pref_score', 'behavior_score']
  return dims.some(k => Number(currentProfile[k]) > 0)
})

const isProfileStale = computed(() => {
  const updateTime = profile.value?.update_time
  if (!updateTime) return false
  const thirtyDaysAgo = Date.now() - 30 * 24 * 60 * 60 * 1000
  return new Date(updateTime).getTime() < thirtyDaysAgo
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

const RISK_LEVEL_PURE: Record<string, string> = {
  c1: '保守型', C1: '保守型', 保守型: '保守型',
  c2: '稳健型', C2: '稳健型', 稳健型: '稳健型',
  c3: '平衡型', C3: '平衡型', 平衡型: '平衡型',
  c4: '进取型', C4: '进取型', 进取型: '进取型',
  c5: '激进型', C5: '激进型', 激进型: '激进型',
}
function formatRiskLevelPure(level: unknown): string {
  if (!level) return '待评估'
  return RISK_LEVEL_PURE[String(level)] || String(level)
}

// ── 雷达图配色：按风险等级映射主色 ──
const RADAR_THEMES: Record<string, { stroke: string; glow: string; fill: [string, string]; dot: string }> = {
  C1: { stroke: '#34d399', glow: 'rgba(52,211,153,.40)', fill: ['rgba(52,211,153,.20)', 'rgba(52,211,153,.04)'], dot: '#6ee7b7' },
  C2: { stroke: '#2dd4bf', glow: 'rgba(45,212,191,.40)', fill: ['rgba(45,212,191,.20)', 'rgba(45,212,191,.04)'], dot: '#5eead4' },
  C3: { stroke: '#38bdf8', glow: 'rgba(56,189,248,.40)', fill: ['rgba(56,189,248,.20)', 'rgba(56,189,248,.04)'], dot: '#7dd3fc' },
  C4: { stroke: '#fbbf24', glow: 'rgba(251,191,36,.40)', fill: ['rgba(251,191,36,.20)', 'rgba(251,191,36,.04)'], dot: '#fcd34d' },
  C5: { stroke: '#f87171', glow: 'rgba(248,113,113,.40)', fill: ['rgba(248,113,113,.20)', 'rgba(248,113,113,.04)'], dot: '#fca5a5' },
}
const FALLBACK_THEME = RADAR_THEMES.C3

function resolveRadarTheme() {
  const level = String(profile.value?.risk_level || '').toUpperCase()
  return RADAR_THEMES[level] ?? FALLBACK_THEME
}

function renderRadarChart() {
  if (!radarChartEl.value || !profile.value || !hasRadarData.value) return
  if (radarChart && radarChart.getDom() !== radarChartEl.value) {
    radarChart.dispose()
    radarChart = undefined
  }
  const isRefresh = !!radarChart
  if (!radarChart) {
    radarChart = echarts.init(radarChartEl.value)
  }

  const theme = resolveRadarTheme()
  const dims = [
    { label: '基础属性', value: Number(profile.value.basic_score || 0), max: 25 },
    { label: '投资经验', value: Number(profile.value.experience_score || 0), max: 25 },
    { label: '风险偏好', value: Number(profile.value.risk_pref_score || 0), max: 30 },
    { label: '行为稳定', value: Number(profile.value.behavior_score || 0), max: 20 },
  ]

  radarChart.setOption({
    // ── 全局动画：首次渲染 900ms，后续刷新缩短至 200ms 避免动画叠加 ──
    animationDuration: isRefresh ? 200 : 900,
    animationEasing: 'cubicOut' as const,
    backgroundColor: 'transparent',

    // ── 提示框：卡片式，各维度带进度条 ──
    tooltip: {
      backgroundColor: 'rgba(15,23,42,.96)',
      borderColor: theme.stroke,
      borderWidth: 1,
      padding: [14, 18],
      textStyle: { color: '#e2e8f0', fontSize: 13 },
      extraCssText: 'border-radius:12px;box-shadow:0 20px 50px rgba(0,0,0,.55);backdrop-filter:blur(12px);',
      formatter: () => {
        const rows = dims.map(d => {
          const pct = Math.round((d.value / d.max) * 100)
          const filled = Math.round(pct / 10)
          const bar = '<span style="color:' + theme.stroke + '">' + '▮'.repeat(filled) + '</span>'
            + '<span style="color:rgba(148,163,184,.20)">' + '▮'.repeat(10 - filled) + '</span>'
          return '<div style="display:flex;align-items:center;justify-content:space-between;gap:14px;margin:5px 0;font-size:12px;">'
            + '<span style="color:#94a3b8;min-width:56px;">' + d.label + '</span>'
            + '<span style="font-family:monospace;">' + bar + '</span>'
            + '<span style="color:#e2e8f0;font-weight:700;min-width:52px;text-align:right;">'
            + d.value + ' <span style="color:#64748b;font-weight:400;">/ ' + d.max + '</span></span>'
            + '</div>'
        })
        return '<div style="font-size:11px;color:#64748b;margin-bottom:8px;letter-spacing:.5px;">四维度能力评估</div>'
          + rows.join('')
      },
    },

    // ── 雷达坐标系 ──
    radar: {
      center: ['50%', '52%'],
      radius: '60%',
      splitNumber: 4,
      shape: 'polygon',
      splitLine: {
        lineStyle: { color: 'rgba(148,163,184,.10)', width: 1, type: 'dashed' as const },
      },
      splitArea: {
        show: true,
        areaStyle: {
          color: [
            'rgba(148,163,184,.015)',
            'rgba(148,163,184,.045)',
            'rgba(148,163,184,.015)',
            'rgba(148,163,184,.045)',
          ],
        },
      },
      axisLine: {
        lineStyle: { color: 'rgba(148,163,184,.15)', width: 1.5 },
      },
      axisName: {
        rich: {
          label: { color: '#cbd5e1', fontSize: 13, fontWeight: 500, padding: [0, 0, 2, 0] },
          score: { color: '#e2e8f0', fontSize: 20, fontFamily: 'Georgia,serif', fontWeight: 700, padding: [4, 0, 0, 0] },
          unit: { color: '#64748b', fontSize: 10, padding: [0, 0, 0, 2] },
        },
      },
      indicator: dims.map(d => ({
        name: '{label|' + d.label + '}\n{score|' + d.value + '}{unit| /' + d.max + '}',
        max: d.max,
      })),
    },

    // ── 数据系列 ──
    series: [
      {
        type: 'radar',
        symbol: 'none',
        silent: true,
        z: 0,
        data: [{
          value: dims.map(d => d.max),
          name: '满分参照',
          lineStyle: { color: 'rgba(148,163,184,.12)', width: 1, type: 'dashed' as const },
          areaStyle: { color: 'transparent' },
        }],
      },
      {
        type: 'radar',
        symbol: 'circle',
        symbolSize: 9,
        z: 1,
        emphasis: { symbolSize: 13, scale: true },
        data: [{
          value: dims.map(d => d.value),
          name: '四维度能力',
          areaStyle: {
            color: theme.fill[0],
            shadowColor: theme.glow,
            shadowBlur: 24,
          },
          lineStyle: { color: theme.stroke, width: 2.5, cap: 'round' as const, join: 'round' as const },
          itemStyle: {
            color: theme.dot,
            borderColor: theme.stroke,
            borderWidth: 2,
            shadowColor: theme.glow,
            shadowBlur: 10,
          },
          label: {
            show: true,
            color: '#f1f5f9',
            fontSize: 11,
            fontWeight: 600,
            offset: [0, 10],
            backgroundColor: 'rgba(15,23,42,.88)',
            borderColor: theme.stroke,
            borderWidth: 1,
            padding: [2, 6],
            borderRadius: 4,
          },
        }],
      },
    ],
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
let renderDebounceTimer: ReturnType<typeof setTimeout> | undefined

onMounted(() => {
  void load()
  window.addEventListener('resize', () => radarChart?.resize())
  stopProfileUpdates = onProfileUpdated((updatedCustomerId) => {
    if (updatedCustomerId === customerId.value) void load()
  })
})
onBeforeUnmount(() => {
  if (renderDebounceTimer) clearTimeout(renderDebounceTimer)
  stopProfileUpdates()
  window.removeEventListener('resize', () => radarChart?.resize())
  radarChart?.dispose()
})

// 单一 watcher：profile 变化时尝试渲染雷达图
// 使用带重试的 DOM 检测，避免 v-if 挂载时序导致的渲染失败
watch(profile, async (newProfile) => {
  if (newProfile && hasRadarData.value) {
    // 取消挂起的重复渲染，避免快速切换客户时多次触发
    if (renderDebounceTimer) clearTimeout(renderDebounceTimer)
    await nextTick()
    const tryRender = (attempts: number) => {
      if (radarChartEl.value) {
        renderRadarChart()
      } else if (attempts < 5) {
        renderDebounceTimer = setTimeout(() => tryRender(attempts + 1), 50)
      }
    }
    tryRender(0)
  } else {
    radarChart?.dispose()
    radarChart = undefined
  }
})
</script>

<style scoped>
.profile-hero h2 { font-size: 32px; }
.radar-chart { width: 100%; height: 360px; }
.radar-empty { display: grid; place-items: center; height: 360px; color: #8ca0b7; font-size: 14px; }
.stale-note { font-size: 11px; color: #64748b; font-weight: 400; }
.stale-warning { text-align: center; padding: 8px 12px; margin-top: -8px; font-size: 12px; color: #f59e0b; background: rgba(251, 191, 36, .08); border-radius: 6px; }
</style>
