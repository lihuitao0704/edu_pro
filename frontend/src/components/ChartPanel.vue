<template><section class="chart-panel"><header class="panel-title-row"><div><span class="section-kicker">{{ eyebrow }}</span><h3>{{ title }}</h3></div><span v-if="caption" class="chart-caption">{{ caption }}</span></header><div ref="chartElement" class="echart-canvas" /></section></template>

<script setup lang="ts">
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps<{ title: string; eyebrow: string; caption?: string; option: echarts.EChartsOption }>()
const chartElement = ref<HTMLElement>()
let chart: echarts.ECharts | undefined

function renderChart() {
  if (!chartElement.value) return
  chart ??= echarts.init(chartElement.value)
  chart.setOption(props.option, true)
}

function resizeChart() {
  chart?.resize()
}

onMounted(() => { renderChart(); window.addEventListener('resize', resizeChart) })
onBeforeUnmount(() => { window.removeEventListener('resize', resizeChart); chart?.dispose() })
watch(() => props.option, renderChart, { deep: true })
</script>

<style scoped>
.chart-panel {
  background: linear-gradient(135deg, #0f1a2e, #162033);
  border: 1px solid rgba(201,168,76,0.15);
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.25);
}
.panel-title-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 14px;
}
.panel-title-row h3 {
  margin: 2px 0 0;
  font-size: 15px;
  font-weight: 600;
  color: #e8ddc8;
}
.chart-caption {
  font-size: 12px;
  color: #bfd4e0;
  line-height: 1.6;
  max-width: 50%;
  text-align: right;
  flex-shrink: 0;
  background: rgba(255,255,255,0.04);
  padding: 6px 10px;
  border-radius: 6px;
}
.echart-canvas { height: 280px; width: 100%; }
</style>
