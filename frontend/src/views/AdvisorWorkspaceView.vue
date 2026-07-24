<template>
  <div class="advisor-grid">
    <aside class="customer-browser surface-card">
      <div class="card-heading"><h3>客户名册</h3></div>
      <form class="search-box" @submit.prevent="search"><input v-model="keyword" placeholder="姓名 / 用户名 / 手机号" /><button>⌕</button></form>
      <ErrorAlert :message="error" />
      <LoadingPanel v-if="loading" text="正在检索客户…" />
      <div v-else class="customer-list">
        <button
          v-for="customer in customers"
          :key="customer.customer_id"
          :class="{ active: selected?.customer_id === customer.customer_id }"
          @click="selectCustomer(customer)"
        >
          <span class="customer-avatar">{{ (customer.real_name || '客').slice(0, 1) }}</span>
          <span><strong>{{ customer.real_name || customer.username }}</strong><small>{{ customer.risk_level || '待评估' }} · {{ money(customer.total_assets) }}</small></span>
          <i :data-risk="customer.risk_flag" />
        </button>
        <EmptyState v-if="!customers.length" title="没有匹配客户" description="尝试使用更短的姓名或用户名。" />
      </div>
    </aside>
    <section class="advisor-main">
      <EmptyState v-if="!selected" title="选择一位客户开始服务" description="画像、持仓和投顾工具将在这里协同工作。" />
      <template v-else>
        <section class="client-banner">
          <div><h2>{{ selected.real_name || selected.username }}</h2><p>客户ID {{ selected.customer_id }} · {{ selected.risk_level }} · {{ selected.customer_level || '普通客户' }} · 资产 {{ money(selected.total_assets) }}</p></div>
          <div class="banner-actions">
            <button class="secondary-button" :disabled="actionLoading" @click="runAllocation">资产配置</button>
            <button class="primary-button" :disabled="actionLoading" @click="runRecommend">生成推荐方案</button>
          </div>
        </section>
        <section class="metric-grid compact">
          <article><span>风险等级</span><strong>{{ selected.risk_level || '—' }}</strong><small>综合 {{ selected.risk_score || '—' }} 分</small></article>
          <article><span>资产规模</span><strong>{{ money(selected.total_assets) }}</strong><small>{{ selected.customer_level || '零售' }}</small></article>
          <article><span>画像置信度</span><strong>{{ selected.confidence_score ? `${Math.round(Number(selected.confidence_score) * 100)}%` : '—' }}</strong><small>持续校准</small></article>
          <article><span>持仓市值</span><strong>{{ money(totalValue) }}</strong><small>{{ holdings.length }} 项持仓</small></article>
        </section>
        <section class="two-column">
          <div class="surface-card">
            <div class="card-heading"><h3>客户持仓</h3></div>
            <div class="risk-legend"><span><strong>风险等级说明：</strong>R1保守型 · R2稳健型 · R3平衡型 · R4进取型 · R5激进型</span></div>
            <div class="holding-list">
              <div v-for="holding in holdings" :key="holding.id">
                <span><strong>{{ holding.product_name }}</strong><small>{{ holding.product_type }} · {{ holding.risk_level }}</small></span>
                <span class="align-right"><strong>{{ money(holding.current_value) }}</strong><small :class="{ positive: Number(holding.profit_loss) >= 0 }">{{ money(holding.profit_loss) }}</small></span>
              </div>
              <EmptyState v-if="!holdings.length" title="暂无持仓" description="可先为客户生成适配产品方案。" />
            </div>
          </div>
          <div class="surface-card recommendation-card">
            <div class="card-heading"><h3>投顾输出</h3></div>
            <LoadingPanel v-if="actionLoading" text="Agent 正在调用画像、推荐与图谱工具…" />
            <div v-else-if="advice" class="advice-content">
              <div class="advice-mark">策</div>
              <p>{{ advice }}</p>
            </div>
            <EmptyState v-else title="等待生成方案" description="系统将基于真实画像和产品库生成结果。" />
          </div>
        </section>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { get, post } from '../api/http'
import type { Customer, Holding } from '../api/types'
import EmptyState from '../components/EmptyState.vue'
import ErrorAlert from '../components/ErrorAlert.vue'
import LoadingPanel from '../components/LoadingPanel.vue'
import { onProfileUpdated } from '../utils/profile-events'

const keyword = ref('')
const customers = ref<Customer[]>([])
const selected = ref<Customer | null>(null)
const holdings = ref<Holding[]>([])
const totalValue = ref(0)
const loading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const advice = ref('')
const money = (value: unknown) => value === undefined || value === null ? '—' : `¥${(Number(value) / 10_000).toFixed(1)}万`

async function search() {
  loading.value = true
  error.value = ''
  try {
    const data = await get<{ items: Customer[] }>(`/customers?keyword=${encodeURIComponent(keyword.value)}&page_size=50`)
    customers.value = data.items
    if (!selected.value && customers.value.length) await selectCustomer(customers.value[0])
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '客户检索失败'
  } finally {
    loading.value = false
  }
}

async function selectCustomer(customer: Customer) {
  selected.value = customer
  advice.value = ''
  try {
    const [detail, data] = await Promise.all([
      get<Customer>(`/customers/${customer.customer_id}`),
      get<{ items: Holding[]; total_value: number }>(`/customers/${customer.customer_id}/holdings`),
    ])
    selected.value = detail
    holdings.value = data.items
    totalValue.value = data.total_value
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '客户详情加载失败'
  }
}

async function runRecommend() {
  if (!selected.value) return
  actionLoading.value = true
  try {
    const result = await post<Record<string, any>>('/chat', {
      message: `为客户${selected.value.customer_id}推荐3款适合的产品`,
      session_id: '',
      user_id: selected.value.customer_id,
      user_role: '理财顾问',
    })
    const data = result.data || result
    advice.value = data.reply || data.data?.reasoning || JSON.stringify(data.data?.recommendations || data, null, 2)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '推荐生成失败'
  } finally {
    actionLoading.value = false
  }
}

async function runAllocation() {
  if (!selected.value) return
  actionLoading.value = true
  try {
    const result = await post<Record<string, any>>('/chat', {
      message: `为客户${selected.value.customer_id}提供资产配置建议`,
      session_id: '',
      user_id: selected.value.customer_id,
      user_role: '理财顾问',
    })
    const data = result.data || result
    advice.value = data.reply || data.data?.reasoning || JSON.stringify(data.data || data, null, 2)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '资产配置生成失败'
  } finally {
    actionLoading.value = false
  }
}

let stopProfileUpdates = () => {}
onMounted(() => {
  void search()
  stopProfileUpdates = onProfileUpdated((updatedCustomerId) => {
    if (selected.value?.customer_id === updatedCustomerId) void selectCustomer(selected.value)
  })
})
onBeforeUnmount(() => stopProfileUpdates())
</script>

<style scoped>
/* 风险等级图例 */
.risk-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-bottom: 12px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(56,189,248,.08);
  font-size: 11px;
  color: #94a3b8;
}
.risk-legend strong {
  color: #38bdf8;
  margin-right: 2px;
}

/* 滑动窗口：限制持仓和投顾输出高度，防止拉长页面 */
.holding-list {
  max-height: 280px;
  overflow-y: auto;
  padding-right: 4px;
}
.holding-list::-webkit-scrollbar,
.advice-content::-webkit-scrollbar {
  width: 4px;
}
.holding-list::-webkit-scrollbar-thumb,
.advice-content::-webkit-scrollbar-thumb {
  background: #3c536e;
  border-radius: 2px;
}

/* 确保两列等高且独立滚动 */
.two-column > .surface-card {
  max-height: 520px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.two-column > .surface-card .card-heading,
.two-column > .surface-card .risk-legend {
  flex-shrink: 0;
}
.two-column > .surface-card > :not(.card-heading):not(.risk-legend):last-child {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
/* 投顾输出区域：强制限高并滚动 */
.advice-content {
  max-height: 320px;
  overflow-y: auto;
  padding-right: 4px;
  flex: 1;
  min-height: 0;
}
.advice-content p {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.7;
  color: #c9d5e5;
}
.advice-mark { background: #0b7f78; }
</style>
