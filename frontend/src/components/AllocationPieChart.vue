<template>
  <section class="allocation-pie-chart surface-card">
    <div class="card-heading"><h3>资产配置</h3><span class="risk-badge" :data-level="riskLevel">{{ riskLevel || '—' }}</span></div>
    <div v-if="!hasData" class="state-panel">
      <span class="state-symbol">📊</span>
      <p>暂无资产配置数据</p>
      <small class="muted">点击"资产配置"按钮获取建议</small>
    </div>
    <template v-else>
      <div ref="chartElement" class="echart-canvas" />
      <div class="allocation-legend">
        <div v-for="item in legendData" :key="item.name" class="legend-item">
          <span class="legend-dot" :style="{ background: item.color }" />
          <span class="legend-label">{{ item.name }}</span>
          <span class="legend-pct">{{ item.value }}%</span>
        </div>
      </div>
      <p v-if="explanation" class="allocation-note">{{ explanation }}</p>
    </template>
  </section>
</template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

interface AllocationItem {
  name: string
  value: number
  color?: string
}

const props = defineProps<{
  allocation: Record<string, number> | null
  riskLevel?: string
  explanation?: string
}>()

const chartElement = ref<HTMLElement>()
let chart: echarts.ECharts | undefined

// 金融配色方案（暗色主题）
const COLOR_PALETTE: Record<string, string> = {
  '货币类': '#34d399',
  '货币基金': '#34d399',
  '债券类': '#60a5fa',
  '债券基金': '#60a5fa',
  '混合类': '#a78bfa',
  '混合基金': '#a78bfa',
  '股票类': '#fb7185',
  '股票基金': '#fb7185',
  '现金': '#fbbf24',
}
const FALLBACK_COLORS = ['#34d399', '#60a5fa', '#a78bfa', '#fb7185', '#fbbf24', '#38bdf8', '#f472b6']

const hasData = computed(() => {
  if (!props.allocation) return false
  const items = Object.entries(props.allocation).filter(([, v]) => v > 0)
  return items.length > 0
})

const legendData = computed<AllocationItem[]>(() => {
  if (!props.allocation) return []
  return Object.entries(props.allocation)
    .filter(([, v]) => v > 0)
    .map(([name, value]) => ({
      name,
      value: typeof value === 'number' ? Math.round(value) : Number(value),
    }))
    .sort((a, b) => b.value - a.value)
})

function buildOption(): echarts.EChartsOption {
  const data = legendData.value.map((item, i) => ({
    name: item.name,
    value: item.value,
    itemStyle: {
      color: COLOR_PALETTE[item.name] || FALLBACK_COLORS[i % FALLBACK_COLORS.length],
      borderRadius: 6,
      borderColor: '#0f172a',
      borderWidth: 3,
    },
  }))

  // 计算总占比确认是否为 100%
  const total = data.reduce((sum, d) => sum + d.value, 0)

  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(15,23,42,0.95)',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0', fontSize: 13 },
      formatter: (params: any) => {
        return `<strong>${params.name}</strong><br/>占比：<b style="color:#67e8f9;font-size:16px">${params.value}%</b>`
      },
    },
    legend: { show: false },
    series: [
      {
        type: 'pie',
        radius: ['55%', '82%'],
        center: ['50%', '48%'],
        roseType: 'area',
        itemStyle: { borderRadius: 8 },
        label: {
          show: false,
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 14,
            fontWeight: 'bold',
            color: '#e2e8f0',
          },
          itemStyle: {
            shadowBlur: 30,
            shadowOffsetX: 0,
            shadowColor: 'rgba(56,189,248,0.35)',
          },
          scaleSize: 12,
        },
        data,
        animationType: 'scale',
        animationEasing: 'elasticOut',
        animationDelay: (idx: number) => idx * 120,
      },
    ],
    graphic: [
      {
        type: 'text',
        left: 'center',
        top: '44%',
        style: {
          text: props.riskLevel || '—',
          textAlign: 'center',
          fill: '#e2e8f0',
          fontSize: 22,
          fontWeight: 700,
          fontFamily: 'Georgia, serif',
        },
      },
    ],
  } as echarts.EChartsOption
}

function renderChart() {
  if (!chartElement.value || !hasData.value) return
  chart ??= echarts.init(chartElement.value, undefined, { renderer: 'canvas' })
  chart.setOption(buildOption(), true)
}

function resizeChart() {
  chart?.resize()
}

onMounted(() => {
  renderChart()
  window.addEventListener('resize', resizeChart)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  chart?.dispose()
})
watch(() => [props.allocation, props.riskLevel], renderChart, { deep: true })
</script>

<style scoped>
.allocation-pie-chart {
  min-height: 380px;
  display: flex;
  flex-direction: column;
}
.allocation-pie-chart .card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.risk-badge {
  padding: 4px 12px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 700;
  background: rgba(56, 189, 248, 0.12);
  color: #7dd3fc;
}
.risk-badge[data-level='C4'],
.risk-badge[data-level='C5'] {
  background: rgba(251, 113, 133, 0.12);
  color: #fda4af;
}
.echart-canvas {
  flex: 1;
  width: 100%;
  min-height: 260px;
}
.allocation-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: center;
  padding: 8px 0 0;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #cbd5e1;
}
.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  flex-shrink: 0;
}
.legend-pct {
  color: #67e8f9;
  font-weight: 700;
}
.allocation-note {
  margin: 14px 0 0;
  padding: 10px 14px;
  border-left: 3px solid #38bdf8;
  border-radius: 6px;
  background: rgba(56, 189, 248, 0.06);
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.7;
}
</style>
