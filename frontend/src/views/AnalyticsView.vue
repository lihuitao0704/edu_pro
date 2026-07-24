<template>
  <div class="bi-dashboard">
    <!-- 页头 -->
    <header class="bi-header">
      <div>
        <span class="section-kicker">BUSINESS INTELLIGENCE</span>
        <h1>数据分析报告</h1>
        <p>关键业务指标聚合看板，数据来源于数据库实时聚合查询。</p>
      </div>
      <div class="bi-header-actions">
        <button class="quiet-button" @click="switchMode">{{ nl2sqlMode ? '← 返回仪表盘' : '自然语言查询 ↗' }}</button>
        <button class="text-button" :disabled="loading" @click="fetchData">⟳ 刷新</button>
      </div>
    </header>

    <!-- ======== NL2SQL 查询模式（保留原有功能） ======== -->
    <template v-if="nl2sqlMode">
      <section class="page-intro">
        <div>
          <span class="eyebrow">NATURAL LANGUAGE ANALYTICS</span>
          <h2>问业务问题，而不是写 SQL</h2>
          <p>只读安全校验、结果解释和图表生成在同一条分析链路完成。</p>
        </div>
      </section>
      <section class="query-studio">
        <form @submit.prevent="nl2sqlQuery">
          <label>向 Analyst Agent 提问</label>
          <div>
            <textarea v-model="nl2sqlQuestion" rows="3" placeholder="例如：查询资产超过100万的客户，并按风险等级统计" />
            <button class="primary-button" :disabled="nl2sqlLoading">
              {{ nl2sqlLoading ? '分析中…' : '开始分析 ↗' }}
            </button>
          </div>
          <div class="query-hints">
            <button v-for="hint in nl2sqlHints" :key="hint.text" type="button" @click="nl2sqlQuestion = hint.text">
              {{ hint.text }}
            </button>
          </div>
        </form>
      </section>
      <ErrorAlert :message="nl2sqlError" />
      <LoadingPanel v-if="nl2sqlLoading" text="正在理解问题、生成安全 SQL 并执行…" />
      <template v-else-if="nl2sqlResult">
        <section class="analysis-insight"><span class="analysis-mark">析</span><div><span class="eyebrow">AGENT INTERPRETATION</span><p>{{ nl2sqlResult.reply }}</p></div></section>
        <section class="two-column analysis-output">
          <div class="surface-card">
            <div class="card-heading"><span class="eyebrow">GENERATED SQL</span><h3>安全查询语句</h3></div>
            <textarea v-model="nl2sqlEditableSql" class="sql-editor" rows="8" spellcheck="false" />
            <div class="sql-actions">
              <button class="text-button" @click="copySql">📋 复制 SQL</button>
              <button class="text-button" :disabled="nl2sqlEditableSql === nl2sqlResult.sql" @click="nl2sqlReExecute">🔄 修改后重新执行</button>
            </div>
            <div v-if="nl2sqlResult.timing" class="sql-timing">生成 {{ nl2sqlResult.timing.generate_ms }}ms · 执行 {{ nl2sqlResult.timing.execute_ms }}ms · 解读 {{ nl2sqlResult.timing.explain_ms }}ms</div>
          </div>
          <div class="surface-card">
            <div class="card-heading"><span class="eyebrow">VISUAL RESULT</span><h3>{{ nl2sqlChartMessage }}</h3></div>
            <div ref="nl2sqlChartEl" class="analysis-chart" />
          </div>
        </section>
        <section class="surface-card">
          <div class="card-heading"><span class="eyebrow">QUERY RESULT</span><h3>数据明细 · {{ (nl2sqlResult.query_result || []).length }} 行</h3></div>
          <div class="data-table-wrap">
            <table v-if="nl2sqlResult.query_result?.length">
              <thead><tr><th v-for="col in nl2sqlColumns" :key="col">{{ col }}</th></tr></thead>
              <tbody><tr v-for="(row, i) in nl2sqlResult.query_result.slice(0, 20)" :key="i"><td v-for="col in nl2sqlColumns" :key="col">{{ formatCell(row[col]) }}</td></tr></tbody>
            </table>
            <EmptyState v-else title="查询未返回数据" description="换一种描述或扩大筛选范围。" />
          </div>
        </section>
      </template>
    </template>

    <!-- ======== BI 仪表盘模式（主视图） ======== -->
    <template v-else>
      <LoadingPanel v-if="loading && !Object.keys(data).length" text="正在加载业务数据…" />

      <!-- 汇总卡片条 -->
      <section v-if="summary" class="summary-strip">
        <div class="summary-card"><span class="summary-icon">👥</span><div><strong>{{ summary.total_customers }}</strong><span>客户总数</span></div></div>
        <div class="summary-card"><span class="summary-icon">💰</span><div><strong>{{ formatCurrency(summary.total_aum) }}</strong><span>客户总资产 (AUM)</span></div></div>
        <div class="summary-card"><span class="summary-icon">📦</span><div><strong>{{ summary.in_sale_products }}</strong><span>在售产品</span></div></div>
        <div class="summary-card"><span class="summary-icon">⚠️</span><div><strong>{{ summary.total_alerts }}</strong><span>风险预警</span></div></div>
      </section>

      <!-- 图表网格: 3×2 -->
      <section v-if="!loading" class="chart-grid">
        <!-- ① AUM分布 -->
        <ChartPanel title="客户AUM分布" eyebrow="ASSET DISTRIBUTION" :caption="aumCaption" :option="aumOption" />
        <!-- ② 风险-收益 -->
        <ChartPanel title="各风险等级平均收益率" eyebrow="RISK VS RETURN" :caption="returnCaption" :option="returnOption" />
        <!-- ③ 热销Top5 -->
        <ChartPanel title="热销产品 Top5" eyebrow="BEST SELLERS" :caption="topProductCaption" :option="topProductOption" />
        <!-- ④ 月度交易趋势 -->
        <ChartPanel title="月度交易趋势" eyebrow="TRANSACTION TREND" :caption="trendCaption" :option="trendOption" />
        <!-- ⑤ 预警分布 -->
        <ChartPanel title="风险预警等级分布" eyebrow="RISK ALERTS" :caption="alertCaption" :option="alertOption" />
        <!-- ⑥ 产品货架矩阵 -->
        <ChartPanel title="产品货架健康度" eyebrow="PRODUCT MATRIX" :caption="matrixCaption" :option="matrixOption" />
      </section>

      <!-- 底部数据说明 -->
      <footer v-if="!loading" class="bi-footer">
        <span class="eyebrow">DATA FRESHNESS</span>
        <p>数据来源于数据库实时聚合查询，反映当前最新快照。指标每小时自动更新。</p>
      </footer>
    </template>
  </div>
</template>

<script setup lang="ts">
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { get, post } from '../api/http'
import ChartPanel from '../components/ChartPanel.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorAlert from '../components/ErrorAlert.vue'
import LoadingPanel from '../components/LoadingPanel.vue'
import { useAuthStore } from '../stores/auth'

echarts.use([BarChart, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const auth = useAuthStore()

// ════════════════════════════════════════════════════════════
// 状态
// ════════════════════════════════════════════════════════════

const loading = ref(false)
const nl2sqlMode = ref(false)
const data = ref<Record<string, any>>({})

const summary = computed(() => data.value.summary || null)

// ════════════════════════════════════════════════════════════
// 获取数据
// ════════════════════════════════════════════════════════════

async function fetchData() {
  loading.value = true
  try {
    const resp = await get<Record<string, any>>('/analytics/bi/dashboard')
    data.value = resp?.data || resp || {}
  } catch { /* 静默 */ }
  finally { loading.value = false }
}

onMounted(() => { fetchData() })

// ════════════════════════════════════════════════════════════
// 工具函数
// ════════════════════════════════════════════════════════════

function formatCurrency(val: number): string {
  if (!val) return '¥0'
  if (val >= 1e8) return `¥${(val / 1e8).toFixed(1)}亿`
  if (val >= 1e4) return `¥${(val / 1e4).toFixed(1)}万`
  return `¥${val.toFixed(0)}`
}

function formatCell(v: any): string {
  if (v === null || v === undefined) return '—'
  return String(v)
}

// ════════════════════════════════════════════════════════════
// 图表 ① — AUM分布 (饼图)
// ════════════════════════════════════════════════════════════

// 风险等级颜色（中文字段 + R1-R5 统一映射）
const RISK_COLORS: Record<string, string> = {
  '保守型': '#22a6b3', '稳健型': '#4fc3f7', '平衡型': '#ffa726',
  '进取型': '#ef5350', '激进型': '#ab47bc', '未知': '#bdbdbd',
  'R1': '#22a6b3', 'R2': '#4fc3f7', 'R3': '#ffa726',
  'R4': '#ef5350', 'R5': '#ab47bc',
}

const aumData = computed(() => data.value.aum_distribution || [])

const aumOption = computed<echarts.EChartsOption>(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c}人 ({d}%)' },
  legend: { bottom: 0, textStyle: { color: '#bfd4e0', fontSize: 11 } },
  series: [{
    type: 'pie', roseType: 'area', radius: ['25%', '70%'],
    itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
    label: { formatter: '{b}\n{c}人', fontSize: 11, color: '#bfd4e0' },
    data: aumData.value.map((r: any) => ({
      name: r.name, value: r.customer_count,
      itemStyle: { color: RISK_COLORS[r.name] || '#bdbdbd' },
    })),
  }],
}))

const aumCaption = computed(() => {
  const top = aumData.value[0]
  if (!top) return ''
  const pct = summary.value ? ((top.total_aum / (summary.value.total_aum || 1)) * 100).toFixed(0) : '—'
  return `💡 ${top.name}客户AUM占总量${pct}%，是核心客群，建议配置专属服务。`
})

// ════════════════════════════════════════════════════════════
// 图表 ② — 风险-收益 (柱状图)
// ════════════════════════════════════════════════════════════

const returnData = computed(() => data.value.return_by_risk || [])

const returnOption = computed<echarts.EChartsOption>(() => ({
  tooltip: { trigger: 'axis', formatter: (p: any) => {
    const d = p[0]
    if (!d) return ''
    const row = returnData.value[d.dataIndex] || {}
    return `${d.name}<br/>平均收益: ${d.value}%<br/>产品数: ${row.product_count}支<br/>范围: ${row.min_return}% ~ ${row.max_return}%`
  }},
  grid: { left: 50, right: 20, top: 10, bottom: 30 },
  xAxis: { type: 'category', data: returnData.value.map((r: any) => r.name), axisLabel: { color: '#bfd4e0' } },
  yAxis: { type: 'value', axisLabel: { color: '#bfd4e0', formatter: '{value}%' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
  series: [{
    type: 'bar', barMaxWidth: 40,
    data: returnData.value.map((r: any) => ({
      value: r.avg_return,
      itemStyle: { color: RISK_COLORS[r.name] || '#5470c6', borderRadius: [6, 6, 0, 0] },
    })),
  }],
}))

const returnCaption = computed(() => {
  if (!returnData.value.length) return ''
  const maxR = returnData.value.reduce((a: any, b: any) => a.avg_return > b.avg_return ? a : b)
  const minR = returnData.value.reduce((a: any, b: any) => a.avg_return < b.avg_return ? a : b)
  return `💡 ${maxR.name}产品平均收益${maxR.avg_return}%最高，${minR.name}产品${minR.avg_return}%最低，风险-收益关系${maxR.avg_return > minR.avg_return ? '基本合理' : '需关注'}。`
})

// ════════════════════════════════════════════════════════════
// 图表 ③ — 热销Top5 (横向柱状图)
// ════════════════════════════════════════════════════════════

const topProductData = computed(() => (data.value.top_products || []).slice(0, 5))

const topProductOption = computed<echarts.EChartsOption>(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (p: any) => {
    const d = p[0]
    if (!d) return ''
    const row = topProductData.value[d.dataIndex] || {}
    return `${row.product_name}<br/>类型: ${row.product_type}<br/>风险: ${row.risk_level}<br/>交易笔数: ${row.tx_count}笔<br/>总金额: ${formatCurrency(row.total_amount)}`
  }},
  grid: { left: 100, right: 30, top: 10, bottom: 10 },
  xAxis: { type: 'value', axisLabel: { color: '#bfd4e0', formatter: (v: number) => formatCurrency(v) }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
  yAxis: { type: 'category', data: topProductData.value.map((r: any) => r.product_name).reverse(), axisLabel: { color: '#bfd4e0', fontSize: 11 } },
  series: [{
    type: 'bar', barMaxWidth: 28,
    data: topProductData.value.map((r: any) => ({
      value: r.total_amount,
      itemStyle: { color: '#0b7f78', borderRadius: [0, 6, 6, 0] },
    })).reverse(),
  }],
}))

const topProductCaption = computed(() => {
  if (!topProductData.value.length) return ''
  const top = topProductData.value[0]
  return `💡 ${top.product_name}销售额${formatCurrency(top.total_amount)}领跑，投顾推荐时可优先关注同类型热销产品。`
})

// ════════════════════════════════════════════════════════════
// 图表 ④ — 月度交易趋势 (折线图)
// ════════════════════════════════════════════════════════════

const trendData = computed(() => data.value.monthly_trend || [])

const trendMonths = computed(() => {
  const s = new Set<string>()
  trendData.value.forEach((r: any) => s.add(r.month))
  return [...s].sort()
})

const trendSeries = computed(() => {
  const typeMap: Record<string, any[]> = {}
  trendData.value.forEach((r: any) => {
    if (!typeMap[r.transaction_type]) typeMap[r.transaction_type] = []
    typeMap[r.transaction_type].push({ month: r.month, amount: r.total_amount })
  })
  const colorMap: Record<string, string> = { purchase: '#0b7f78', redeem: '#ef5350', transfer_out: '#ffa726' }
  const nameMap: Record<string, string> = { purchase: '申购', redeem: '赎回', transfer_out: '转账' }
  return Object.entries(typeMap).map(([type, pts]) => ({
    name: nameMap[type] || type,
    type: 'line' as const,
    smooth: true,
    data: trendMonths.value.map(m => { const p = pts.find((x: any) => x.month === m); return p ? p.amount : 0 }),
    itemStyle: { color: colorMap[type] || '#5470c6' },
    areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: (colorMap[type] || '#5470c6') + '40' }, { offset: 1, color: (colorMap[type] || '#5470c6') + '05' }]) },
  }))
})

const trendOption = computed<echarts.EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  legend: { bottom: 0, textStyle: { color: '#bfd4e0', fontSize: 11 } },
  grid: { left: 55, right: 20, top: 10, bottom: 35 },
  xAxis: { type: 'category', data: trendMonths.value, axisLabel: { color: '#bfd4e0', fontSize: 10 } },
  yAxis: { type: 'value', axisLabel: { color: '#bfd4e0', formatter: (v: number) => formatCurrency(v) }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
  series: trendSeries.value,
}))

const trendCaption = computed(() => {
  if (!trendData.value.length) return ''
  const months = trendMonths.value
  const latest = months[months.length - 1]
  const purchaseTotal = trendData.value.filter((r: any) => r.month === latest && r.transaction_type === 'purchase').reduce((s: number, r: any) => s + r.total_amount, 0)
  const redeemTotal = trendData.value.filter((r: any) => r.month === latest && r.transaction_type === 'redeem').reduce((s: number, r: any) => s + r.total_amount, 0)
  if (redeemTotal > purchaseTotal && purchaseTotal > 0) return `💡 ${latest}赎回(${formatCurrency(redeemTotal)})超过申购(${formatCurrency(purchaseTotal)})，建议关注资金流向。`
  if (purchaseTotal > 0) return `💡 ${latest}交易活跃，申购${formatCurrency(purchaseTotal)}为主力方向。`
  return ''
})

// ════════════════════════════════════════════════════════════
// 图表 ⑤ — 预警分布 (饼图)
// ════════════════════════════════════════════════════════════

const alertData = computed(() => data.value.alert_distribution || [])

const ALERT_COLORS: Record<string, string> = { 'high': '#ef5350', 'medium': '#ffa726', 'low': '#4fc3f7' }

const alertOption = computed<echarts.EChartsOption>(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c}条 ({d}%)' },
  legend: { bottom: 0, textStyle: { color: '#bfd4e0', fontSize: 11 } },
  series: [{
    type: 'pie', radius: ['35%', '65%'], center: ['50%', '45%'],
    label: { formatter: '{b}\n{c}条', fontSize: 11, color: '#bfd4e0' },
    emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.2)' } },
    data: alertData.value.map((r: any) => ({
      name: r.label, value: r.count,
      itemStyle: { color: ALERT_COLORS[r.name] || '#bdbdbd' },
    })),
  }],
}))

const alertCaption = computed(() => {
  if (!alertData.value.length) return '💡 暂无预警记录，风控态势平稳。'
  const high = alertData.value.find((r: any) => r.name === 'high')
  const total = alertData.value.reduce((s: number, r: any) => s + r.count, 0)
  if (high) return `💡 高风险预警${high.count}条占${((high.count / total) * 100).toFixed(0)}%，建议复核预警阈值配置。`
  return `💡 当前预警${total}条，以中低风险为主。`
})

// ════════════════════════════════════════════════════════════
// 图表 ⑥ — 产品货架矩阵 (分组柱状图)
// ════════════════════════════════════════════════════════════

const matrixData = computed(() => data.value.product_matrix || [])

const matrixTypes = computed(() => [...new Set(matrixData.value.map((r: any) => r.product_type))].sort())
const matrixRiskLevels = computed(() => {
  const order = ['R1', 'R2', 'R3', 'R4', 'R5', '未知']
  const levels = new Set(matrixData.value.map((r: any) => r.risk_level))
  return order.filter(l => levels.has(l))
})

const matrixOption = computed<echarts.EChartsOption>(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  legend: { bottom: 0, textStyle: { color: '#bfd4e0', fontSize: 10 } },
  grid: { left: 70, right: 20, top: 10, bottom: 45 },
  xAxis: { type: 'category', data: matrixTypes.value, axisLabel: { color: '#bfd4e0', fontSize: 10, rotate: 20 } },
  yAxis: { type: 'value', axisLabel: { color: '#bfd4e0' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
  series: matrixRiskLevels.value.map(level => ({
    name: level, type: 'bar' as const, barMaxWidth: 16,
    data: matrixTypes.value.map(t => {
      const match = matrixData.value.find((r: any) => r.product_type === t && r.risk_level === level)
      return match ? match.product_count : 0
    }),
    itemStyle: { color: RISK_COLORS[level] || '#5470c6', borderRadius: [4, 4, 0, 0] },
  })),
}))

const matrixCaption = computed(() => {
  const rows = matrixData.value
  if (!rows.length) return ''
  const r1Count = rows.filter((r: any) => r.risk_level === 'R1').reduce((s: number, r: any) => s + r.product_count, 0)
  const r5Count = rows.filter((r: any) => r.risk_level === 'R5').reduce((s: number, r: any) => s + r.product_count, 0)
  if (r1Count > r5Count * 2 && r1Count > 0) return `💡 低风险(R1)产品${r1Count}支远超高风险(R5)${r5Count}支，产品线偏保守，可考虑补充高风险产品。`
  if (r5Count > r1Count * 2 && r5Count > 0) return `💡 高风险(R5)产品${r5Count}支较多，需关注适当性匹配合规风险。`
  return `💡 ${r1Count + r5Count > 0 ? '产品风险覆盖较均衡' : '产品矩阵数据待完善'}。`
})

// ════════════════════════════════════════════════════════════
// NL2SQL 查询（保留原有功能）
// ════════════════════════════════════════════════════════════

const nl2sqlQuestion = ref('查询资产超过100万的客户')
const nl2sqlLoading = ref(false)
const nl2sqlError = ref('')
const nl2sqlResult = ref<any>(null)
const nl2sqlEditableSql = ref('')
const nl2sqlChartEl = ref<HTMLElement>()
let nl2sqlChart: echarts.ECharts | null = null
const nl2sqlColumns = computed(() => Object.keys(nl2sqlResult.value?.query_result?.[0] || {}))
const nl2sqlChartMessage = ref('自动图表')

const nl2sqlHints = [
  { text: '查询资产超过100万的客户' },
  { text: '各产品类型的平均收益率是多少？' },
  { text: '统计近30天各等级风险预警数量' },
]

function switchMode() {
  nl2sqlMode.value = !nl2sqlMode.value
  if (!nl2sqlMode.value) nl2sqlResult.value = null
}

async function nl2sqlQuery() {
  if (!nl2sqlQuestion.value.trim()) return
  nl2sqlLoading.value = true; nl2sqlError.value = ''; nl2sqlResult.value = null
  try {
    const resp = await post<any>('/chat', {
      session_id: `analyst-${Date.now().toString(36)}`,
      message: nl2sqlQuestion.value,
      user_id: auth.user?.user_id,
      user_role: auth.user?.role || '理财顾问',
    })
    const respData = resp?.data || resp || {}
    const inner = respData.data || {}
    nl2sqlResult.value = { ...respData, ...inner, reply: respData.reply || inner.reply || '', sql: inner.sql || respData.sql || '', query_result: inner.query_result || respData.query_result || [] }
    nl2sqlEditableSql.value = nl2sqlResult.value?.sql || ''
  } catch (reason: any) {
    nl2sqlResult.value = null; nl2sqlError.value = reason instanceof Error ? reason.message : '分析查询失败'
  } finally { nl2sqlLoading.value = false }
}

async function nl2sqlReExecute() {
  if (!nl2sqlEditableSql.value.trim()) return
  nl2sqlLoading.value = true; nl2sqlError.value = ''; nl2sqlResult.value = null
  try {
    const resp = await post<any>('/chat', { session_id: `analyst-${Date.now().toString(36)}`, message: `执行SQL查询：${nl2sqlEditableSql.value}`, user_id: auth.user?.user_id, user_role: auth.user?.role || '理财顾问' })
    const respData = resp?.data || resp || {}
    const inner = respData.data || {}
    nl2sqlResult.value = { ...respData, ...inner, reply: respData.reply || inner.reply || '', sql: inner.sql || respData.sql || nl2sqlEditableSql.value, query_result: inner.query_result || respData.query_result || [] }
  } catch { nl2sqlError.value = '执行失败' } finally { nl2sqlLoading.value = false }
}

function copySql() { if (nl2sqlResult.value?.sql) navigator.clipboard?.writeText(nl2sqlResult.value.sql).catch(() => {}) }

onBeforeUnmount(() => nl2sqlChart?.dispose())
</script>

<style scoped>
.bi-dashboard { padding: 0 0 32px; }
.bi-header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 16px; margin-bottom: 24px; }
.bi-header h1 { margin: 4px 0 6px; }
.bi-header p { margin: 0; color: #4a5568; font-size: 14px; }
.bi-header-actions { display: flex; gap: 8px; align-items: center; }
.summary-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; margin-bottom: 28px; }
.summary-card { background: linear-gradient(135deg, #0f1a2e, #162033); border: 1px solid rgba(201,168,76,0.15); border-radius: 12px; padding: 18px 20px; display: flex; align-items: center; gap: 14px; box-shadow: 0 4px 20px rgba(0,0,0,0.25); }
.summary-icon { font-size: 24px; }
.summary-card div { display: flex; flex-direction: column; }
.summary-card strong { font-size: 20px; font-weight: 700; color: #e8ddc8; line-height: 1.2; }
.summary-card span { font-size: 12px; color: #8aa0b8; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
@media (max-width: 900px) { .chart-grid { grid-template-columns: 1fr; } }
.bi-footer { margin-top: 28px; padding: 16px 0; border-top: 1px solid rgba(201,168,76,0.12); }
.bi-footer p { margin: 4px 0 0; font-size: 12px; color: #8aa0b8; }

/* NL2SQL 模式样式 */
.page-intro { margin-bottom: 20px; }
.page-intro h2 { margin: 4px 0 6px; color: #e8ddc8; }
.page-intro p { margin: 0; color: #8aa0b8; font-size: 14px; }
.query-studio { background: linear-gradient(135deg, #0f1a2e, #162033); border: 1px solid rgba(201,168,76,0.15); border-radius: 12px; padding: 24px; margin-bottom: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.25); }
.query-studio label { font-size: 12px; font-weight: 600; color: #8aa0b8; text-transform: uppercase; letter-spacing: 1px; display: block; margin-bottom: 8px; }
.query-studio > form > div { display: flex; gap: 12px; }
.query-studio textarea { flex: 1; background: #0a1628; border: 1px solid rgba(201,168,76,0.12); border-radius: 8px; padding: 12px; font-family: inherit; font-size: 14px; resize: vertical; color: #e8ddc8; }
.query-studio textarea::placeholder { color: #5a7088; }
.primary-button { background: #c9a84c; color: #0a1628; border: none; border-radius: 8px; padding: 10px 20px; font-weight: 600; cursor: pointer; white-space: nowrap; }
.primary-button:hover { background: #d4b966; }
.primary-button:disabled { opacity: 0.5; cursor: default; }
.query-hints { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.query-hints button { background: rgba(255,255,255,0.05); border: 1px solid rgba(201,168,76,0.12); border-radius: 6px; padding: 6px 12px; font-size: 12px; cursor: pointer; color: #8aa0b8; }
.query-hints button:hover { border-color: #c9a84c; color: #e8ddc8; }
.analysis-insight { background: linear-gradient(135deg, #0f1a2e, #162033); border: 1px solid rgba(201,168,76,0.15); border-radius: 12px; padding: 20px 24px; margin-bottom: 20px; display: flex; gap: 14px; align-items: flex-start; box-shadow: 0 4px 20px rgba(0,0,0,0.25); }
.analysis-mark { width: 32px; height: 32px; background: #c9a84c; color: #0a1628; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; flex-shrink: 0; }
.analysis-insight p { margin: 4px 0 0; font-size: 14px; line-height: 1.7; color: #bfd4e0; }
.two-column { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
.surface-card { background: linear-gradient(135deg, #0f1a2e, #162033); border: 1px solid rgba(201,168,76,0.15); border-radius: 12px; padding: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.25); }
.card-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card-heading h3 { margin: 2px 0 0; font-size: 15px; color: #e8ddc8; }
.sql-editor { width: 100%; background: #0a1628; border: 1px solid rgba(201,168,76,0.12); border-radius: 6px; padding: 10px; font-family: 'JetBrains Mono', monospace; font-size: 13px; resize: vertical; color: #bfd4e0; }
.sql-actions { display: flex; gap: 8px; margin-top: 8px; }
.text-button { background: none; border: none; color: #c9a84c; cursor: pointer; font-size: 12px; padding: 4px 8px; }
.text-button:hover { color: #d4b966; }
.text-button:disabled { opacity: 0.4; cursor: default; }
.sql-timing { margin-top: 8px; font-size: 11px; color: #8aa0b8; }
.analysis-chart { height: 260px; }
.data-table-wrap { max-height: 300px; overflow: auto; }
.data-table-wrap table { width: 100%; font-size: 13px; border-collapse: collapse; }
.data-table-wrap th { background: #0a1628; padding: 8px 10px; text-align: left; font-weight: 600; font-size: 12px; position: sticky; top: 0; color: #d4b966; }
.data-table-wrap td { padding: 6px 10px; border-top: 1px solid rgba(201,168,76,0.08); color: #bfd4e0; }
.quiet-button { background: rgba(255,255,255,0.05); border: 1px solid rgba(201,168,76,0.15); border-radius: 6px; padding: 6px 14px; font-size: 13px; cursor: pointer; color: #8aa0b8; }
.quiet-button:hover { border-color: #c9a84c; color: #e8ddc8; }
</style>
