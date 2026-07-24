<template>
  <div class="page-stack analytics-dark">
    <section class="page-intro">
      <div>
        <h2>问业务问题，而不是写 SQL</h2>
        <p>只读安全校验、结果解释和图表生成在同一条分析链路完成。</p>
      </div>
    </section>

    <!-- 查询输入区 -->
    <section class="query-studio">
      <form @submit.prevent="query">
        <label>向 Analyst Agent 提问</label>
        <div>
          <textarea v-model="question" rows="3" placeholder="例如：查询资产超过100万的客户，并按风险等级统计" />
          <button class="primary-button" :disabled="loading">
            {{ loading ? '分析中…' : '开始分析 ↗' }}
          </button>
        </div>
        <div class="query-hints">
          <button
            v-for="hint in hints"
            :key="hint.text"
            type="button"
            @click="question = hint.text"
          >
            {{ hint.text }}
          </button>
        </div>
      </form>
    </section>

    <!-- 错误提示（含失败 SQL） -->
    <ErrorAlert :message="errorMsg" />
    <div v-if="failedSql" class="failed-sql-card surface-card-dark">
      <div class="card-heading"><span class="eyebrow">ATTEMPTED SQL</span><h3>尝试的 SQL（校验未通过）</h3></div>
      <pre class="sql-block"><code>{{ failedSql }}</code></pre>
    </div>

    <LoadingPanel v-if="loading" text="正在理解问题、生成安全 SQL 并执行…" />

    <template v-else-if="result">
      <!-- Agent 解读 -->
      <section class="analysis-insight">
        <span class="analysis-mark">析</span>
        <div>
          <span class="eyebrow">AGENT INTERPRETATION</span>
          <p>{{ result.reply || '分析完成，结果如下所示。' }}</p>
        </div>
      </section>

      <!-- SQL + 图表 -->
      <section class="two-column analysis-output">
        <!-- SQL 卡片 -->
        <div class="surface-card-dark">
          <div class="card-heading">
            <span class="eyebrow">GENERATED SQL</span>
            <h3>安全查询语句</h3>
          </div>
          <textarea
            v-model="editableSql"
            class="sql-editor"
            rows="8"
            spellcheck="false"
          />
          <div class="sql-actions">
            <button class="text-button" @click="copySQL">📋 复制 SQL</button>
            <button
              class="text-button"
              :disabled="editableSql === result.sql"
              @click="reExecute"
            >
              🔄 修改后重新执行
            </button>
          </div>
          <!-- 动态安全标签 -->
          <div class="sql-safety">
            <span :class="result.safety?.select_only ? 'pass' : 'fail'">
              {{ result.safety?.select_only ? '✓' : '✗' }} 仅允许 SELECT
            </span>
            <span :class="result.safety?.no_sensitive ? 'pass' : 'fail'">
              {{ result.safety?.no_sensitive ? '✓' : '✗' }} 敏感字段过滤
            </span>
            <span :class="result.safety?.row_limit ? 'pass' : 'fail'">
              {{ result.safety?.row_limit ? '✓' : '✗' }} 最大 100 行
            </span>
          </div>
          <div v-if="result.timing" class="sql-timing">
            生成 {{ result.timing.generate_ms }}ms · 执行 {{ result.timing.execute_ms }}ms · 解读 {{ result.timing.explain_ms }}ms · 总计 {{ result.timing.total_ms }}ms
          </div>
        </div>

        <!-- 图表卡片 -->
        <div class="surface-card-dark">
          <div class="card-heading">
            <span class="eyebrow">VISUAL RESULT</span>
            <h3>{{ chartMessage }}</h3>
          </div>
          <div ref="chartElement" class="analysis-chart" />
        </div>
      </section>

      <!-- 数据明细 -->
      <section class="surface-card-dark">
        <div class="card-heading">
          <span class="eyebrow">QUERY RESULT</span>
          <h3>
            数据明细 · {{ result.query_result?.length || 0 }} 行
            <span v-if="result.truncated" class="truncate-warn">⚡ 结果已截断，建议缩小查询范围</span>
          </h3>
          <button class="text-button" @click="exportCSV">📥 导出 CSV</button>
        </div>
        <div class="data-table-wrap">
          <table v-if="result.query_result?.length">
            <thead>
              <tr>
                <th v-for="column in columns" :key="column" @click="sortBy(column)" class="sortable">
                  {{ column }} {{ sortColumn === column ? (sortAsc ? '▲' : '▼') : '' }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, pageRowIndex) in pagedRows" :key="pageRowIndex">
                <td v-for="column in columns" :key="column">{{ formatCell(row[column]) }}</td>
              </tr>
            </tbody>
          </table>
          <EmptyState v-else title="查询未返回数据" description="换一种描述或扩大筛选范围。" />
        </div>
        <div v-if="totalPages > 1" class="pagination">
          <button :disabled="page <= 1" @click="page--">‹ 上一页</button>
          <span>第 {{ page }} / {{ totalPages }} 页</span>
          <button :disabled="page >= totalPages" @click="page++">下一页 ›</button>
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

// ---- 状态 ----
const question = ref('查询资产超过100万的客户')
const loading = ref(false)
const errorMsg = ref('')
const failedSql = ref('')
const result = ref<{
  reply: string; sql: string; query_result: Record<string, any>[]
  safety?: { select_only: boolean; row_limit: boolean; no_sensitive: boolean }
  truncated?: boolean
  timing?: { generate_ms: number; execute_ms: number; explain_ms: number; total_ms: number }
} | null>(null)
const editableSql = ref('')
const chartElement = ref<HTMLElement>()
let chart: ReturnType<typeof echarts.init> | null = null

const hints = [
  { text: '查询资产超过100万的客户' },
  { text: '各产品类型的平均收益率是多少？' },
  { text: '统计近30天各等级风险预警数量' },
]

const columns = computed(() => Object.keys(result.value?.query_result?.[0] || {}))
const chartMessage = ref('自动图表')

// ---- 分页 ----
const page = ref(1)
const pageSize = 20
const sortColumn = ref('')
const sortAsc = ref(true)
const sortedRows = computed(() => {
  const rows = [...(result.value?.query_result || [])]
  if (sortColumn.value) {
    rows.sort((a, b) => {
      const va = a[sortColumn.value] ?? '', vb = b[sortColumn.value] ?? ''
      const na = Number(va), nb = Number(vb)
      if (!Number.isNaN(na) && !Number.isNaN(nb)) return sortAsc.value ? na - nb : nb - na
      return sortAsc.value ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va))
    })
  }
  return rows
})
const totalPages = computed(() => Math.max(1, Math.ceil(sortedRows.value.length / pageSize)))
const pagedRows = computed(() => sortedRows.value.slice((page.value - 1) * pageSize, page.value * pageSize))

function sortBy(col: string) {
  if (sortColumn.value === col) { sortAsc.value = !sortAsc.value } else { sortColumn.value = col; sortAsc.value = true }
  page.value = 1
}

// ---- 查询 ----
async function query() {
  if (!question.value.trim()) return
  loading.value = true
  errorMsg.value = ''
  failedSql.value = ''
  result.value = null
  page.value = 1
  try {
    const resp = await post<Record<string, any>>('/chat', {
      session_id: `analyst-${Date.now().toString(36)}`,
      message: question.value,
      user_id: auth.user?.user_id,
      user_role: auth.user?.role || '理财顾问',
    })
    const respData = resp?.data || resp || {}
    const inner = respData.data || {}
    result.value = {
      ...respData,
      ...inner,
      reply: respData.reply || inner.reply || '',
      sql: inner.sql || respData.sql || '',
      query_result: inner.query_result || respData.query_result || [],
    }
    editableSql.value = result.value?.sql || ''
    await nextTick()
    renderChart()
  } catch (reason: any) {
    result.value = null
    failedSql.value = reason?.data?.sql || ''
    errorMsg.value = reason instanceof Error ? reason.message : '分析查询失败'
  } finally {
    loading.value = false
  }
}

// ---- 重新执行（用户编辑 SQL 后） ----
async function reExecute() {
  if (!editableSql.value.trim()) return
  loading.value = true
  errorMsg.value = ''
  failedSql.value = ''
  result.value = null
  page.value = 1
  try {
    const resp = await post<Record<string, any>>('/chat', {
      session_id: `analyst-${Date.now().toString(36)}`,
      message: `执行SQL查询：${editableSql.value}`,
      user_id: auth.user?.user_id,
      user_role: auth.user?.role || '理财顾问',
    })
    const respData = resp?.data || resp || {}
    const inner = respData.data || {}
    result.value = {
      ...respData,
      ...inner,
      reply: respData.reply || inner.reply || '',
      sql: inner.sql || respData.sql || editableSql.value,
      query_result: inner.query_result || respData.query_result || [],
    }
  } catch (reason: any) {
    failedSql.value = editableSql.value
    errorMsg.value = reason instanceof Error ? reason.message : '执行失败'
  } finally {
    loading.value = false
  }
}

function copySQL() {
  if (result.value?.sql) {
    navigator.clipboard?.writeText(result.value.sql).catch(() => {})
  }
}

// ---- 图表 ----
function renderChart() {
  const rows = result.value?.query_result || []
  if (!chartElement.value || !rows.length) {
    chartMessage.value = rows.length === 0 ? '无数据，不展示图表' : '该结果不适合图表展示'
    return
  }

  chart?.dispose()
  chart = echarts.init(chartElement.value)

  const keys = Object.keys(rows[0] || {})
  const numCols: string[] = []
  const labelCols: string[] = []
  for (const key of keys) {
    const allNumeric = rows.every(r => {
      const v = r[key]
      return v !== null && v !== undefined && v !== '' && !Number.isNaN(Number(v))
    })
    if (allNumeric) { numCols.push(key) } else { labelCols.push(key) }
  }

  if (numCols.length === 0) {
    chartMessage.value = '该结果不适合图表展示（无数字列）'
    return
  }

  const labelKey = labelCols[0] || keys[0]
  chartMessage.value = numCols.length > 1 ? '多系列柱状图' : '柱状图'

  chart.setOption({
    grid: { left: 50, right: 20, top: 20, bottom: 55 },
    xAxis: {
      type: 'category',
      data: rows.map((r, i) => String(r[labelKey] ?? `结果${i + 1}`)),
      axisLabel: { color: '#94a3b8', rotate: rows.length > 8 ? 25 : 0 },
      axisLine: { lineStyle: { color: '#334155' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#94a3b8' },
      splitLine: { lineStyle: { color: '#1e293b' } },
    },
    series: numCols.map((col, i) => ({
      name: col,
      type: 'bar',
      data: rows.map(r => {
        const v = Number(r[col])
        return Number.isNaN(v) ? null : v
      }),
      itemStyle: {
        color: ['#38bdf8', '#f59e0b', '#8b5cf6', '#34d399', '#fb7185'][i % 5],
        borderRadius: [6, 6, 0, 0],
      },
      barMaxWidth: 38,
    })),
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0f172a',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0' },
    },
    legend: numCols.length > 1 ? {
      data: numCols,
      bottom: 0,
      textStyle: { color: '#94a3b8' },
    } : undefined,
  })
}

// ---- 导出 CSV ----
function exportCSV() {
  const cols = columns.value
  const rows = result.value?.query_result || []
  const BOM = '﻿'
  const header = cols.map(c => `"${c}"`).join(',')
  const body = rows.map(r => cols.map(c => `"${String(r[c] ?? '').replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob([BOM + header + '\n' + body], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = `analyst-${Date.now()}.csv`; a.click()
  URL.revokeObjectURL(url)
}

function formatCell(val: any): string {
  if (val === null || val === undefined) return '—'
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

onBeforeUnmount(() => chart?.dispose())
</script>

<style scoped>
/* ===== 数据分析深色主题 ===== */

/* 全局卡片覆盖 */
.surface-card-dark {
  border: 1px solid #263247;
  border-radius: 15px;
  padding: 21px;
  background: linear-gradient(145deg, rgba(21,31,49,.94), rgba(14,22,36,.94));
  box-shadow: 0 20px 55px rgba(0,0,0,.16);
}
.surface-card-dark .card-heading h3 {
  color: #eff6ff;
  font-size: 17px;
  margin: 5px 0 0;
}

/* Agent 解读区 */
.analysis-insight {
  padding: 18px 20px;
  display: flex;
  align-items: flex-start;
  gap: 13px;
  border-left: 3px solid #38bdf8;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(21,31,49,.94), rgba(14,22,36,.94));
  border: 1px solid #263247;
  border-left: 3px solid #38bdf8;
}
.analysis-insight p {
  margin: 4px 0 0;
  color: #c9d5e5;
  font-size: 13px;
  line-height: 1.75;
  white-space: pre-wrap;
}

/* SQL 编辑器 */
.sql-editor {
  min-height: 130px;
  margin: 0;
  padding: 15px;
  border: 1px solid #334155;
  border-radius: 9px;
  color: #e2e8f0;
  background: #0f172a;
  font-size: 12px;
  line-height: 1.7;
  font-family: Consolas, monospace;
  resize: vertical;
}
.sql-editor:focus {
  border-color: #38bdf8;
  box-shadow: 0 0 0 3px rgba(56,189,248,.1);
}

/* SQL 操作按钮 */
.sql-actions {
  margin-top: 10px;
  display: flex;
  gap: 12px;
}
.sql-actions .text-button {
  border: 0;
  background: transparent;
  color: #94a3b8;
  font-size: 11px;
  cursor: pointer;
  padding: 4px 0;
}
.sql-actions .text-button:hover:not(:disabled) {
  color: #38bdf8;
}
.sql-actions .text-button:disabled {
  opacity: .4;
  cursor: not-allowed;
}

/* 安全校验标签 */
.sql-safety {
  display: flex;
  gap: 12px;
  margin-top: 10px;
  font-size: 10px;
}
.sql-safety span.pass {
  color: #34d399;
}
.sql-safety span.fail {
  color: #fb7185;
}

/* SQL 耗时 */
.sql-timing {
  margin-top: 8px;
  color: #8d9bb1;
  font-size: 10px;
}

/* 图表区域 */
.analysis-chart {
  height: 220px;
}

/* 数据表格 */
.data-table-wrap {
  overflow-x: auto;
}
.data-table-wrap table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.data-table-wrap th {
  padding: 10px 12px;
  color: #94a3b8;
  border-bottom: 1px solid #334155;
  text-align: left;
  font-size: 10px;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.data-table-wrap th.sortable {
  cursor: pointer;
  user-select: none;
}
.data-table-wrap th.sortable:hover {
  color: #38bdf8;
}
.data-table-wrap td {
  padding: 12px;
  border-bottom: 1px solid #1e293b;
  color: #e5edf9;
}
.data-table-wrap tbody tr {
  cursor: pointer;
}
.data-table-wrap tbody tr:hover {
  background: rgba(56,189,248,.06);
}

/* 分页 */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-top: 16px;
}
.pagination button {
  padding: 7px 14px;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #94a3b8;
  background: transparent;
  font-size: 12px;
  cursor: pointer;
}
.pagination button:hover:not(:disabled) {
  color: #e2e8f0;
  border-color: #475569;
}
.pagination button:disabled {
  opacity: .4;
  cursor: not-allowed;
}
.pagination span {
  color: #94a3b8;
  font-size: 12px;
}

/* 截断警告 */
.truncate-warn {
  color: #f59e0b;
  font-size: 11px;
  font-weight: 500;
  margin-left: 8px;
}

/* 卡片头部按钮 */
.surface-card-dark .card-heading .text-button {
  border: 0;
  background: transparent;
  color: #94a3b8;
  font-size: 11px;
  cursor: pointer;
}
.surface-card-dark .card-heading .text-button:hover {
  color: #38bdf8;
}

/* 失败 SQL 卡片 */
.failed-sql-card {
  border: 1px solid rgba(251,113,133,.3);
}
.failed-sql-card .sql-block {
  min-height: 130px;
  margin: 0;
  padding: 15px;
  overflow: auto;
  border-radius: 9px;
  color: #fda4af;
  background: #1a0f17;
  font-size: 11px;
  line-height: 1.7;
}
</style>
