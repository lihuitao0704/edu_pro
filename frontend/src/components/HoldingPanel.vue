<template>
  <section class="holding-panel surface-card">
    <div class="card-heading split">
      <h3>持仓分析</h3>
      <span class="holding-summary-badge">{{ holdings.length }} 项持仓 · 市值 {{ money(totalValue) }}</span>
    </div>

    <div v-if="!holdings.length" class="state-panel">
      <span class="state-symbol">💼</span>
      <p>该客户暂无持仓记录</p>
    </div>

    <template v-else>
      <!-- 盈亏概览条 -->
      <div class="pl-strip">
        <div class="pl-item" :class="{ positive: (plSummary?.total_profit_loss ?? 0) > 0, negative: (plSummary?.total_profit_loss ?? 0) < 0 }">
          <span>总盈亏</span>
          <strong>{{ (plSummary?.total_profit_loss ?? 0) > 0 ? '+' : '' }}{{ money(plSummary?.total_profit_loss) }}</strong>
        </div>
        <div class="pl-item">
          <span>总市值</span>
          <strong>{{ money(plSummary?.total_value) }}</strong>
        </div>
        <div class="pl-item">
          <span>盈利/亏损</span>
          <strong><span class="positive">{{ plSummary?.profit_count ?? 0 }}盈</span> / <span class="negative">{{ plSummary?.loss_count ?? 0 }}亏</span></strong>
        </div>
      </div>

      <!-- 持仓明细表格 -->
      <div class="data-table-wrap">
        <table>
          <thead>
            <tr>
              <th>产品名称</th>
              <th>类型</th>
              <th>风险</th>
              <th>市值</th>
              <th>盈亏</th>
              <th>盈亏比</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="h in holdings" :key="h.id" class="holding-row">
              <td>
                <strong>{{ h.product_name }}</strong>
                <small>{{ h.product_code }}</small>
              </td>
              <td><span class="type-tag">{{ h.product_type || '—' }}</span></td>
              <td><span class="risk-chip" :data-level="h.risk_level">{{ h.risk_level || '—' }}</span></td>
              <td class="align-right">{{ money(h.current_value) }}</td>
              <td class="align-right" :class="{ positive: (h.profit_loss || 0) > 0, negative: (h.profit_loss || 0) < 0 }">
                {{ (h.profit_loss || 0) > 0 ? '+' : '' }}{{ money(h.profit_loss ?? 0) }}
              </td>
              <td class="align-right" :class="{ positive: (h.profit_ratio || 0) > 0, negative: (h.profit_ratio || 0) < 0 }">
                {{ formatRatio(h.profit_ratio ?? 0) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 行业分布（如有） -->
      <div v-if="industryDist?.length" class="industry-section">
        <h4>行业分布</h4>
        <div class="industry-bars">
          <div v-for="ind in industryDist" :key="ind.name" class="industry-bar-item">
            <div class="industry-bar-label">
              <span>{{ ind.name }}</span>
              <span>{{ ind.productCount }} 项</span>
            </div>
            <div class="industry-bar-track">
              <div class="industry-bar-fill" :style="{ width: industryBarWidth(ind.productCount) }" />
            </div>
          </div>
        </div>
        <p v-if="industryWarning" class="industry-warning">⚠️ {{ industryWarning }}</p>
      </div>

      <!-- 集中度警告 -->
      <div v-if="concentration?.warning" class="concentration-warning">
        ⚠️ {{ concentration.warning }}
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Holding } from '../api/types'

interface IndustryItem {
  name: string
  productCount: number
}

const props = defineProps<{
  holdings: Holding[]
  totalValue: number
  plSummary?: {
    total_value?: number
    total_profit_loss?: number
    profit_count?: number
    loss_count?: number
    flat_count?: number
    avg_profit_ratio?: number
  }
  concentration?: {
    total_value?: number
    product_count?: number
    max_single_ratio?: number
    warning?: string | null
  }
  industryDist?: IndustryItem[]
  industryWarning?: string | null
}>()

const money = (value: unknown) => {
  if (value === undefined || value === null || value === '') return '—'
  const n = Number(value)
  if (Math.abs(n) >= 1_0000) return `¥${(n / 1_0000).toFixed(1)}万`
  return `¥${n.toFixed(2)}`
}

const formatRatio = (value: number) => {
  if (value === 0) return '0%'
  return `${(value * 100).toFixed(2)}%`
}

const maxProductCount = computed(() => {
  if (!props.industryDist?.length) return 1
  return Math.max(...props.industryDist.map(d => d.productCount), 1)
})

const industryBarWidth = (count: number) => `${(count / maxProductCount.value) * 100}%`
</script>

<style scoped>
.holding-panel {
  min-height: 320px;
  display: flex;
  flex-direction: column;
}
.holding-summary-badge {
  padding: 4px 12px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(56, 189, 248, 0.08);
  color: #7dd3fc;
}

/* 盈亏概览条 */
.pl-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 18px;
  padding: 16px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid #1e293b;
}
.pl-item {
  text-align: center;
}
.pl-item span {
  display: block;
  color: #64748b;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.pl-item strong {
  display: block;
  margin-top: 6px;
  color: #e2e8f0;
  font-size: 18px;
  font-family: Georgia, serif;
}
.pl-item.positive strong { color: #34d399; }
.pl-item.negative strong { color: #fb7185; }

/* 表格 */
.data-table-wrap {
  max-height: 300px;
  overflow-y: auto;
}
.data-table-wrap table { font-size: 12px; }
.data-table-wrap td strong {
  display: block;
  color: #e2e8f0;
}
.data-table-wrap td small {
  color: #64748b;
  font-size: 10px;
}
.type-tag {
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(56, 189, 248, 0.08);
  color: #7dd3fc;
  font-size: 10px;
  white-space: nowrap;
}
.risk-chip {
  padding: 2px 8px;
  border-radius: 99px;
  font-size: 10px;
  font-weight: 700;
  background: rgba(52, 211, 153, 0.1);
  color: #34d399;
}
.risk-chip[data-level='R3'] { background: rgba(251, 191, 36, 0.1); color: #fbbf24; }
.risk-chip[data-level='R4'] { background: rgba(251, 113, 133, 0.12); color: #fda4af; }
.risk-chip[data-level='R5'] { background: rgba(239, 68, 68, 0.15); color: #f87171; }
.align-right { text-align: right; }
.positive { color: #34d399 !important; }
.negative { color: #fb7185 !important; }

/* 行业分布 */
.industry-section {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid #1e293b;
}
.industry-section h4 {
  margin: 0 0 12px;
  color: #e2e8f0;
  font-size: 14px;
}
.industry-bars {
  display: grid;
  gap: 10px;
}
.industry-bar-item {
  display: grid;
  gap: 5px;
}
.industry-bar-label {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #94a3b8;
}
.industry-bar-track {
  height: 6px;
  border-radius: 3px;
  background: #1e293b;
  overflow: hidden;
}
.industry-bar-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #38bdf8, #818cf8);
  transition: width 0.6s ease;
}
.industry-warning, .concentration-warning {
  margin: 12px 0 0;
  padding: 10px 14px;
  border-radius: 8px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.2);
  color: #fbbf24;
  font-size: 11px;
}
</style>
