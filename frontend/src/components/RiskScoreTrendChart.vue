<template>
  <section class="risk-score-trend surface-card">
    <div class="card-heading split"><div><span class="eyebrow">RISK SCORE HISTORY</span><h3>历次风险评估趋势</h3></div><span class="trend-caption">综合评分与四维度演变</span></div>
    <div v-if="!records.length" class="trend-empty">暂无评估记录</div>
    <div v-else ref="chartElement" class="risk-score-chart" />
  </section>
</template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

export interface RiskScoreHistoryRecord {
  rating_date: string
  total_score: number | null
  risk_level: string | null
  basic_score: number | null
  experience_score: number | null
  risk_pref_score: number | null
  behavior_score: number | null
  trigger_type: 'manual' | 'auto' | 'event'
}

const props = defineProps<{ records: RiskScoreHistoryRecord[] }>()
const chartElement = ref<HTMLElement>()
let chart: echarts.ECharts | undefined

function renderChart() {
  if (!chartElement.value || !props.records.length) return
  chart ??= echarts.init(chartElement.value)
  const labels = props.records.map((item) => item.rating_date)
  const turningPoints = props.records
    .map((item, index) => ({ item, index }))
    .filter(({ item, index }) => index === 0 || item.risk_level !== props.records[index - 1].risk_level)
    .map(({ item, index }) => ({ coord: [labels[index], item.total_score], value: item.risk_level }))
  const triggerSeries = (type: RiskScoreHistoryRecord['trigger_type'], symbol: string, hollow = false) => ({
    name: type === 'manual' ? '人工评估' : type === 'auto' ? '自动研判' : '事件触发',
    type: 'scatter' as const,
    symbol,
    symbolSize: 10,
    itemStyle: hollow ? { color: '#111827', borderColor: '#fbbf24', borderWidth: 2 } : { color: type === 'event' ? '#fb7185' : '#fbbf24' },
    data: props.records.map((item, index) => item.trigger_type === type ? [labels[index], item.total_score] : null),
  })
  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: 42, right: 20, top: 58, bottom: 30 },
    tooltip: { trigger: 'axis', backgroundColor: '#111827', borderColor: '#30415a', textStyle: { color: '#e5edf9' } },
    legend: { top: 5, textStyle: { color: '#aebed2', fontSize: 11 }, itemWidth: 14 },
    xAxis: { type: 'category', data: labels, axisLine: { lineStyle: { color: '#31445d' } }, axisLabel: { color: '#8ca0b7' } },
    yAxis: { type: 'value', min: 0, max: 100, axisLine: { show: false }, axisLabel: { color: '#8ca0b7' }, splitLine: { lineStyle: { color: '#223047' } } },
    series: [
      {
        name: '综合评分', type: 'line', data: props.records.map((item) => item.total_score), smooth: true, symbol: 'circle', symbolSize: 7,
        lineStyle: { color: '#38bdf8', width: 4 }, itemStyle: { color: '#7dd3fc' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(56,189,248,.35)' }, { offset: 1, color: 'rgba(56,189,248,0)' }]) },
        markPoint: { symbolSize: 40, itemStyle: { color: '#1e3a5f' }, label: { color: '#dbeafe', fontSize: 10 }, data: turningPoints },
      },
      { name: '基础属性', type: 'line', data: props.records.map((item) => item.basic_score), lineStyle: { type: 'dashed', color: '#a78bfa', width: 1.5 }, symbol: 'none' },
      { name: '投资经验', type: 'line', data: props.records.map((item) => item.experience_score), lineStyle: { type: 'dashed', color: '#34d399', width: 1.5 }, symbol: 'none' },
      { name: '风险偏好', type: 'line', data: props.records.map((item) => item.risk_pref_score), lineStyle: { type: 'dashed', color: '#f59e0b', width: 1.5 }, symbol: 'none' },
      { name: '行为稳定', type: 'line', data: props.records.map((item) => item.behavior_score), lineStyle: { type: 'dashed', color: '#fb7185', width: 1.5 }, symbol: 'none' },
      triggerSeries('manual', 'circle'), triggerSeries('auto', 'circle', true), triggerSeries('event', 'diamond'),
    ],
  }, true)
}

function resizeChart() { chart?.resize() }
onMounted(() => { renderChart(); window.addEventListener('resize', resizeChart) })
onBeforeUnmount(() => { window.removeEventListener('resize', resizeChart); chart?.dispose() })
watch(() => props.records, renderChart, { deep: true })
</script>
