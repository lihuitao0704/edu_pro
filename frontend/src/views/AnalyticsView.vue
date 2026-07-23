<template>
  <div class="page-stack">
    <section class="page-intro">
      <div><span class="eyebrow">NATURAL LANGUAGE ANALYTICS</span><h2>问业务问题，而不是写 SQL</h2><p>只读安全校验、结果解释和图表生成在同一条分析链路完成。</p></div>
    </section>
    <section class="query-studio">
      <form @submit.prevent="query">
        <label>向 Analyst Agent 提问</label>
        <div><textarea v-model="question" rows="3" placeholder="例如：查询资产超过100万的客户，并按风险等级统计" /><button class="primary-button" :disabled="loading">{{ loading ? '分析中…' : '开始分析 ↗' }}</button></div>
        <div class="query-hints"><button v-for="hint in hints" :key="hint" type="button" @click="question = hint">{{ hint }}</button></div>
      </form>
    </section>
    <ErrorAlert :message="error" />
    <LoadingPanel v-if="loading" text="正在理解问题、生成安全 SQL 并执行…" />
    <template v-else-if="result">
      <section class="analysis-insight">
        <span class="analysis-mark">析</span>
        <div><span class="eyebrow">AGENT INTERPRETATION</span><p>{{ result.reply }}</p></div>
      </section>
      <section class="two-column analysis-output">
        <div class="surface-card">
          <div class="card-heading"><span class="eyebrow">GENERATED SQL</span><h3>安全查询语句</h3></div>
          <pre class="sql-block"><code>{{ result.sql }}</code></pre>
          <div class="sql-safety"><span>✓ 仅允许 SELECT</span><span>✓ 敏感字段过滤</span><span>✓ 最大 100 行</span></div>
        </div>
        <div class="surface-card">
          <div class="card-heading"><span class="eyebrow">VISUAL RESULT</span><h3>自动图表</h3></div>
          <div ref="chartElement" class="analysis-chart" />
        </div>
      </section>
      <section class="surface-card">
        <div class="card-heading"><span class="eyebrow">QUERY RESULT</span><h3>数据明细 · {{ result.query_result?.length || 0 }} 行</h3></div>
        <div class="data-table-wrap">
          <table v-if="result.query_result?.length">
            <thead><tr><th v-for="column in columns" :key="column">{{ column }}</th></tr></thead>
            <tbody><tr v-for="(row, index) in result.query_result" :key="index"><td v-for="column in columns" :key="column">{{ row[column] }}</td></tr></tbody>
          </table>
          <EmptyState v-else title="查询未返回数据" description="换一种描述或扩大筛选范围。" />
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

import { post } from '../api/http'
import EmptyState from '../components/EmptyState.vue'
import ErrorAlert from '../components/ErrorAlert.vue'
import LoadingPanel from '../components/LoadingPanel.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])
const question = ref('查询资产超过100万的客户')
const loading = ref(false)
const error = ref('')
const result = ref<{ reply: string; sql: string; query_result: Record<string, any>[] } | null>(null)
const chartElement = ref<HTMLElement>()
let chart: ReturnType<typeof echarts.init> | null = null
const hints = ['查询资产超过100万的客户', '各产品类型的平均收益率是多少？', '统计近30天各等级风险预警数量']
const columns = computed(() => Object.keys(result.value?.query_result?.[0] || {}))

async function query() {
  if (!question.value.trim()) return
  loading.value = true
  error.value = ''
  try {
    result.value = await post('/chat/analyst', {
      session_id: `analyst-${Date.now().toString(36)}`,
      message: question.value,
      user_id: auth.user?.user_id,
    })
    await nextTick()
    renderChart()
  } catch (reason) {
    result.value = null
    error.value = reason instanceof Error ? reason.message : '分析查询失败'
  } finally {
    loading.value = false
  }
}

function renderChart() {
  const rows = result.value?.query_result || []
  if (!chartElement.value) return
  chart?.dispose()
  chart = echarts.init(chartElement.value)
  const keys = Object.keys(rows[0] || {})
  const valueKey = keys.find((key) => rows.some((row) => !Number.isNaN(Number(row[key]))))
  const labelKey = keys.find((key) => key !== valueKey) || keys[0]
  chart.setOption({
    grid: { left: 40, right: 20, top: 20, bottom: 45 },
    xAxis: { type: 'category', data: rows.map((row, index) => String(row[labelKey] ?? `结果${index + 1}`)), axisLabel: { color: '#607080', rotate: rows.length > 8 ? 25 : 0 } },
    yAxis: { type: 'value', axisLabel: { color: '#607080' }, splitLine: { lineStyle: { color: '#e7ecef' } } },
    series: [{ type: 'bar', data: rows.map((row) => Number(row[valueKey || ''] || 0)), itemStyle: { color: '#0b7f78', borderRadius: [6, 6, 0, 0] }, barMaxWidth: 38 }],
    tooltip: { trigger: 'axis' },
  })
}

onBeforeUnmount(() => chart?.dispose())
</script>
