<template>
  <div class="page-stack">
    <!-- ===== 页面头部 + 工具栏 ===== -->
    <section class="page-intro">
      <div><h2>异常交易与工单联动</h2><p>预警、证据规则、客户风险标记和调查工单保持同步。</p></div>
      <div class="toolbar-row">
        <select v-model="filterLevel" @change="page=1; loadAlerts()" class="filter-select">
          <option value="">全部等级</option>
          <option value="high">高</option>
          <option value="medium">中</option>
          <option value="low">低</option>
        </select>
        <select v-model="filterStatus" @change="page=1; loadAlerts()" class="filter-select">
          <option value="">全部状态</option>
          <option value="pending">待处理</option>
          <option value="resolved">已处理</option>
          <option value="false_positive">误报</option>
        </select>
        <button class="secondary-button" @click="loadAll">刷新数据</button>
        <button class="secondary-button" @click="exportCSV">📥 导出CSV</button>
      </div>
    </section>

    <!-- ===== 统计卡片 ===== -->
    <section class="risk-summary">
      <article><span>待处理预警</span><strong>{{ pendingCount }}</strong><i class="red" /></article>
      <article><span>高风险</span><strong>{{ highCount }}</strong><i class="amber" /></article>
      <article><span>处理中工单</span><strong>{{ activeOrders }}</strong><i class="blue" /></article>
    </section>

    <!-- ===== 风控日报 ===== -->
    <section v-if="dailyReport" class="daily-report surface-card">
      <div class="card-heading"><h3>📋 风控日报 · {{ dailyReport.date }}</h3></div>
      <div class="report-grid">
        <div class="report-stat"><span>今日新增</span><strong>{{ dailyReport.summary.total_alerts }}</strong></div>
        <div class="report-stat high"><span>高风险</span><strong>{{ dailyReport.summary.high_new }}</strong></div>
        <div class="report-stat medium"><span>中风险</span><strong>{{ dailyReport.summary.medium_new }}</strong></div>
        <div class="report-stat low"><span>低风险</span><strong>{{ dailyReport.summary.low_new }}</strong></div>
        <div class="report-stat"><span>今日已处理</span><strong>{{ dailyReport.summary.resolved_today }}</strong></div>
        <div class="report-stat pending"><span>待处理总数</span><strong>{{ dailyReport.summary.pending_total }}</strong></div>
      </div>
      <div class="report-detail-row">
        <div class="report-mini">
          <span>🔴 高风险客户 TOP3</span>
          <ol>
            <li v-for="c in dailyReport.top_high_risk_customers?.slice(0,3)" :key="c.customer_id">
              客户 #{{ c.customer_id }} · {{ c.count }} 条预警
            </li>
            <li v-if="!dailyReport.top_high_risk_customers?.length">暂无</li>
          </ol>
        </div>
        <div class="report-mini">
          <span>📊 触发最多规则 TOP3</span>
          <ol>
            <li v-for="r in dailyReport.top_rules?.slice(0,3)" :key="r.rule_id">
              {{ r.rule_id }} · {{ r.count }} 次
            </li>
            <li v-if="!dailyReport.top_rules?.length">暂无</li>
          </ol>
        </div>
      </div>
    </section>

    <!-- ===== 图表区 ===== -->
    <section v-if="statistics" class="two-column">
      <div class="surface-card">
        <div class="card-heading"><h3>近7天预警趋势</h3></div>
        <div ref="trendChartEl" class="risk-chart" />
      </div>
      <div class="surface-card">
        <div class="card-heading"><h3>级别分布</h3></div>
        <div ref="pieChartEl" class="risk-chart" />
      </div>
    </section>

    <ErrorAlert :message="error" />
    <LoadingPanel v-if="loading" />

    <!-- ===== 预警队列 + 详情 ===== -->
    <section v-else class="risk-layout">
      <div class="surface-card alert-table-card">
        <div class="card-heading"><h3>风险预警队列</h3></div>
        <div class="data-table-wrap">
          <table>
            <thead><tr><th>等级</th><th>客户</th><th>触发规则</th><th>状态</th><th>时间</th><th></th></tr></thead>
            <tbody>
              <tr v-for="alert in alerts" :key="alert.alert_id" :class="{ selected: selected?.alert_id === alert.alert_id }" @click="selected = alert">
                <td>
                  <span class="level-chip" :data-level="alert.alert_level">{{ levelLabel(alert.alert_level) }}</span>
                  <!-- 累计升级标记 -->
                  <span v-if="alert.alert_type === 'cumulative_risk'" class="cumulative-tag">累计升级</span>
                </td>
                <td>#{{ alert.customer_id }}</td>
                <td>
                  {{ alert.trigger_rules?.map(r => r.rule_name || r.rule_id).join('、') || alert.summary }}
                  <!-- SLA超时标记 -->
                  <span v-if="slaTimeout(alert)" class="sla-badge" :title="slaTimeout(alert) || undefined">⏰超时</span>
                </td>
                <td>{{ alert.status }}</td>
                <td>{{ alert.created_at?.slice(0, 16).replace('T', ' ') }}</td>
                <td>
                  <span v-if="alert.confidence != null" class="confidence-dot" :class="confidenceClass(alert.confidence)" :title="`置信度 ${(alert.confidence*100).toFixed(0)}%`" />
                </td>
              </tr>
            </tbody>
          </table>
          <EmptyState v-if="!alerts.length" title="当前没有风险预警" description="交易监测保持运行。" />
        </div>
        <!-- 分页 -->
        <div v-if="totalPages > 1" class="pagination">
          <button :disabled="page <= 1" @click="page--; loadAlerts()">‹ 上一页</button>
          <span>第 {{ page }} / {{ totalPages }} 页 · 共 {{ totalAlerts }} 条</span>
          <button :disabled="page >= totalPages" @click="page++; loadAlerts()">下一页 ›</button>
        </div>
      </div>
      <aside class="surface-card alert-detail">
        <template v-if="selected">
          <h3>
            {{ levelLabel(selected.alert_level) }}预警
            <span v-if="selected.alert_type === 'cumulative_risk'" class="cumulative-tag large">累计风险升级</span>
          </h3>
          <p>{{ selected.summary }}</p>
          <!-- 置信度 -->
          <div v-if="selected.confidence != null" class="confidence-bar">
            <span>置信度</span>
            <strong :class="confidenceClass(selected.confidence)">{{ (selected.confidence * 100).toFixed(0) }}%</strong>
          </div>
          <!-- 触发规则（含可解释性条件） -->
          <div class="rule-stack">
            <span v-for="rule in selected.trigger_rules" :key="rule.rule_id">
              <b>{{ rule.rule_id }}</b>{{ rule.rule_name }}
              <small v-if="rule.trigger_condition">{{ rule.trigger_condition }}</small>
            </span>
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

    <!-- ===== 批量导入 ===== -->
    <section class="surface-card">
      <div class="card-heading split">
        <div><h3>批量导入监控数据</h3></div>
        <span class="import-hint">支持 JSON / CSV 文件，最多 100 笔</span>
      </div>
      <div class="batch-import-row">
        <label class="import-drop">
          <input type="file" accept=".json,.csv" @change="batchFile = ($event.target as HTMLInputElement).files?.[0] || null" />
          <span>{{ batchFile?.name || '选择文件…' }}</span>
        </label>
        <button class="secondary-button" :disabled="!batchFile || batchUploading" @click="batchUpload">
          {{ batchUploading ? '上传中…' : '上传并分析' }}
        </button>
      </div>
      <!-- 批量结果弹窗 -->
      <div v-if="batchResult" class="batch-result">
        <div class="batch-result-header">
          <strong>导入结果</strong>
          <button class="quiet-button" @click="batchResult = null">✕</button>
        </div>
        <div class="batch-result-grid">
          <span>总数 <b>{{ batchResult.total }}</b></span>
          <span class="green">正常 <b>{{ batchResult.normal }}</b></span>
          <span class="red">命中 <b>{{ batchResult.hit }}</b></span>
          <span class="red">高 <b>{{ batchResult.high }}</b></span>
          <span class="amber">中 <b>{{ batchResult.medium }}</b></span>
          <span class="blue">低 <b>{{ batchResult.low }}</b></span>
        </div>
      </div>
    </section>

    <!-- ===== 关联工单 ===== -->
    <section class="surface-card">
      <div class="card-heading"><h3>关联调查工单</h3></div>
      <div class="workorder-strip">
        <article v-for="order in workorders.slice(0, 6)" :key="order.id">
          <span>{{ order.priority || '普通' }}</span><strong>{{ order.work_order_no }}</strong><p>客户 #{{ order.customer_id }} · {{ order.order_type }}</p><small>{{ order.status }}</small>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import * as echarts from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import { get, post, put } from '../api/http'
import type { RiskAlert, RiskDailyReport, RiskStatistics } from '../api/types'
import EmptyState from '../components/EmptyState.vue'
import ErrorAlert from '../components/ErrorAlert.vue'
import LoadingPanel from '../components/LoadingPanel.vue'
import { useAuthStore } from '../stores/auth'

echarts.use([LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const auth = useAuthStore()
const alerts = ref<RiskAlert[]>([])
const workorders = ref<any[]>([])
const dailyReport = ref<RiskDailyReport | null>(null)
const statistics = ref<RiskStatistics | null>(null)
const selected = ref<RiskAlert | null>(null)
const handleNote = ref('')
const loading = ref(false)
const error = ref('')
const filterLevel = ref('')
const filterStatus = ref('')

// 分页
const page = ref(1)
const pageSize = 10
const totalAlerts = ref(0)
const totalPages = computed(() => Math.max(1, Math.ceil(totalAlerts.value / pageSize)))

// 图表
const trendChartEl = ref<HTMLElement>()
const pieChartEl = ref<HTMLElement>()
let trendChart: echarts.ECharts | null = null
let pieChart: echarts.ECharts | null = null

// 批量导入
const batchFile = ref<File | null>(null)
const batchUploading = ref(false)
const batchResult = ref<{ total: number; normal: number; hit: number; high: number; medium: number; low: number } | null>(null)

// ---- 计算属性 ----
const pendingCount = computed(() => dailyReport.value?.summary?.pending_total ?? alerts.value.filter((item) => !['resolved', 'false_positive'].includes(item.status)).length)
const highCount = computed(() => dailyReport.value?.summary?.high_new ?? alerts.value.filter((item) => item.alert_level === 'high').length)
const activeOrders = computed(() => workorders.value.filter((item) => !['已完成', '已关闭'].includes(item.status)).length)
const levelLabel = (level: string) => ({ low: '低', medium: '中', high: '高' }[level] || level)

// SLA超时判断
function slaTimeout(alert: RiskAlert): string | null {
  if (!['pending'].includes(alert.status)) return null
  if (!alert.created_at) return null
  const hours = (Date.now() - new Date(alert.created_at).getTime()) / 3600000
  if (alert.alert_level === 'high') return null // 高风险不限时
  if (alert.alert_level === 'medium' && hours > 72) return `${Math.floor(hours / 24)}天未处理`
  if (alert.alert_level === 'low' && hours > 168) return `${Math.floor(hours / 24)}天未处理`
  return null
}

// 置信度颜色
function confidenceClass(val: number): string {
  if (val >= 0.8) return 'conf-high'
  if (val < 0.5) return 'conf-low'
  return 'conf-mid'
}

// ---- 数据加载 ----
async function loadAlerts() {
  error.value = ''
  try {
    const alertParams = new URLSearchParams({ page: String(page.value), page_size: String(pageSize) })
    if (filterLevel.value) alertParams.set('alert_level', filterLevel.value)
    if (filterStatus.value) alertParams.set('status', filterStatus.value)

    const alertData = await get<{ alerts: RiskAlert[]; total?: number }>(`/risk/alerts?${alertParams.toString()}`)
    alerts.value = alertData.alerts
    totalAlerts.value = alertData.total ?? alertData.alerts.length

    if (selected.value) {
      selected.value = alerts.value.find((item) => item.alert_id === selected.value?.alert_id) || null
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '预警数据加载失败'
  }
}

async function loadAll() {
  loading.value = true
  error.value = ''
  page.value = 1
  try {
    const [orderData, reportData, statsData] = await Promise.all([
      get<{ items: any[] }>('/operation/workorders?page_size=100'),
      get<RiskDailyReport>('/risk/report').catch(() => null),
      get<RiskStatistics>('/risk/statistics?days=7').catch(() => null),
    ])
    workorders.value = orderData.items
    dailyReport.value = reportData
    statistics.value = statsData

    await loadAlerts()
    await nextTick()
    renderCharts()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '风险数据加载失败'
  } finally {
    loading.value = false
  }
}

// ---- 预警处理 ----
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

// ---- CSV导出 ----
function exportCSV() {
  window.open('/api/risk/alerts/export', '_blank')
}

// ---- 批量导入 ----
async function batchUpload() {
  if (!batchFile.value) return
  batchUploading.value = true
  try {
    const text = await batchFile.value.text()
    let data: any[]
    if (batchFile.value.name.endsWith('.json')) {
      data = JSON.parse(text)
    } else {
      // 简单CSV解析
      const lines = text.split('\n').filter(Boolean)
      const headers = lines[0].split(',')
      data = lines.slice(1).map(line => {
        const values = line.split(',')
        return Object.fromEntries(headers.map((h, i) => [h.trim(), values[i]?.trim()]))
      })
    }
    const result = await post<{ total: number; normal: number; hit: number; high: number; medium: number; low: number }>(
      '/risk/monitor/batch',
      data.slice(0, 100),
    )
    batchResult.value = result
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '批量导入失败'
  } finally {
    batchUploading.value = false
  }
}

// ---- 图表渲染 ----
function renderCharts() {
  if (!statistics.value) return

  // 趋势折线图
  if (trendChartEl.value && statistics.value.trend?.length) {
    trendChart?.dispose()
    trendChart = echarts.init(trendChartEl.value)
    trendChart.setOption({
      grid: { left: 40, right: 16, top: 16, bottom: 30 },
      tooltip: { trigger: 'axis', backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e2e8f0', fontSize: 12 } },
      xAxis: {
        type: 'category',
        data: statistics.value.trend.map(t => t.date.slice(5)),
        axisLabel: { color: '#94a3b8', fontSize: 10 },
        axisLine: { lineStyle: { color: '#334155' } },
      },
      yAxis: {
        type: 'value', minInterval: 1,
        axisLabel: { color: '#94a3b8', fontSize: 10 },
        splitLine: { lineStyle: { color: '#1e293b' } },
      },
      series: [{
        type: 'line', data: statistics.value.trend.map(t => t.count),
        smooth: true, symbol: 'circle', symbolSize: 6,
        lineStyle: { color: '#38bdf8', width: 3 },
        itemStyle: { color: '#7dd3fc' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0,0,0,1,[
          { offset: 0, color: 'rgba(56,189,248,.3)' }, { offset: 1, color: 'rgba(56,189,248,0)' }
        ])},
      }],
    })
  }

  // 级别分布饼图
  if (pieChartEl.value && statistics.value.level_distribution) {
    pieChart?.dispose()
    pieChart = echarts.init(pieChartEl.value)
    const dist = statistics.value.level_distribution
    pieChart.setOption({
      tooltip: { trigger: 'item', backgroundColor: '#0f172a', borderColor: '#334155', textStyle: { color: '#e2e8f0' } },
      legend: { bottom: 0, textStyle: { color: '#94a3b8', fontSize: 11 } },
      series: [{
        type: 'pie',
        radius: ['50%', '74%'],
        center: ['50%', '45%'],
        label: { color: '#94a3b8', formatter: '{b}\n{d}%', fontSize: 10 },
        labelLine: { lineStyle: { color: '#475569' } },
        itemStyle: { borderColor: '#0f172a', borderWidth: 3 },
        data: [
          { value: dist.high, name: '高风险', itemStyle: { color: '#fb7185' } },
          { value: dist.medium, name: '中风险', itemStyle: { color: '#f59e0b' } },
          { value: dist.low, name: '低风险', itemStyle: { color: '#38bdf8' } },
        ],
      }],
    })
  }
}

function resizeCharts() { trendChart?.resize(); pieChart?.resize() }

// ---- 生命周期 ----
onMounted(() => { loadAll(); window.addEventListener('resize', resizeCharts) })
onBeforeUnmount(() => { window.removeEventListener('resize', resizeCharts); trendChart?.dispose(); pieChart?.dispose() })
</script>

<style scoped>
/* ===== 风控日报 ===== */
.daily-report { margin-top: 2px; }
.report-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}
.report-stat {
  padding: 12px;
  border-radius: 10px;
  background: #1e293b;
  text-align: center;
}
.report-stat span { display: block; color: #94a3b8; font-size: 10px; margin-bottom: 4px; }
.report-stat strong { color: #e5edf9; font-size: 22px; font-weight: 700; }
.report-stat.high strong { color: #fb7185; }
.report-stat.medium strong { color: #f59e0b; }
.report-stat.low strong { color: #38bdf8; }
.report-stat.pending strong { color: #fbbf24; }
.report-detail-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.report-mini { padding: 10px 14px; border-radius: 8px; background: #151f31; }
.report-mini > span { color: #94a3b8; font-size: 11px; font-weight: 600; }
.report-mini ol { margin: 6px 0 0; padding-left: 18px; color: #c9d5e5; font-size: 11px; line-height: 1.7; }

/* ===== 图表 ===== */
.risk-chart { width: 100%; height: 260px; }

/* ===== SLA超时 ===== */
.sla-badge {
  display: inline-block;
  margin-left: 6px;
  color: #fb7185;
  font-size: 12px;
  cursor: help;
  vertical-align: middle;
}

/* ===== 累计升级 ===== */
.cumulative-tag {
  display: inline-block;
  margin-left: 4px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(245,158,11,.15);
  color: #f59e0b;
  font-size: 9px;
  font-weight: 700;
  vertical-align: middle;
}
.cumulative-tag.large { margin-left: 8px; font-size: 10px; padding: 2px 8px; }

/* ===== 置信度 ===== */
.confidence-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  cursor: help;
}
.confidence-dot.conf-high { background: #34d399; }
.confidence-dot.conf-mid { background: #f59e0b; }
.confidence-dot.conf-low { background: #fb7185; }

.confidence-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0;
  padding: 8px 12px;
  border-radius: 8px;
  background: #1e293b;
}
.confidence-bar span { color: #94a3b8; font-size: 11px; }
.confidence-bar strong { font-size: 16px; }
.confidence-bar .conf-high { color: #34d399; }
.confidence-bar .conf-mid { color: #f59e0b; }
.confidence-bar .conf-low { color: #fb7185; }

/* ===== 规则触发条件 ===== */
.rule-stack span small {
  display: block;
  margin-top: 3px;
  color: #64748b;
  font-size: 10px;
}

/* ===== 批量导入 ===== */
.import-hint { color: #64748b; font-size: 11px; }
.batch-import-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}
.import-drop {
  flex: 1;
  padding: 12px 16px;
  border: 1px dashed #475569;
  border-radius: 8px;
  color: #94a3b8;
  font-size: 12px;
  cursor: pointer;
  text-align: center;
  transition: border-color .2s;
}
.import-drop:hover { border-color: #38bdf8; }
.import-drop input { display: none; }
.batch-result {
  margin-top: 14px;
  padding: 16px;
  border: 1px solid #334155;
  border-radius: 10px;
  background: #151f31;
}
.batch-result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.batch-result-header strong { color: #e5edf9; }
.batch-result-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
  text-align: center;
}
.batch-result-grid span { font-size: 11px; color: #94a3b8; }
.batch-result-grid b { display: block; font-size: 20px; margin-top: 2px; }
.batch-result-grid .green, .batch-result-grid .green b { color: #34d399; }
.batch-result-grid .red, .batch-result-grid .red b { color: #fb7185; }
.batch-result-grid .amber, .batch-result-grid .amber b { color: #f59e0b; }
.batch-result-grid .blue, .batch-result-grid .blue b { color: #38bdf8; }

/* 工作台header */
.page-intro h2 { font-size: 28px; }

@media (max-width: 1180px) {
  .report-grid { grid-template-columns: repeat(3, 1fr); }
  .report-detail-row { grid-template-columns: 1fr; }
  .batch-result-grid { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 760px) {
  .report-grid { grid-template-columns: repeat(2, 1fr); }
  .batch-result-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
