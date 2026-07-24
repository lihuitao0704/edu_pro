<template><section class="chart-panel"><header class="panel-title-row"><div><span class="section-kicker">{{ eyebrow }}</span><h3>{{ title }}</h3></div><span v-if="caption">{{ caption }}</span></header><div ref="chartElement" class="echart-canvas" /></section></template>

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
