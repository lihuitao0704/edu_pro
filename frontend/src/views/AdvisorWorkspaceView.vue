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
          <span class="customer-info">
            <strong>{{ customer.real_name || customer.username }}</strong>
            <small>{{ customer.customer_level || '零售' }} · {{ money(customer.total_assets) }} · {{ getHoldingCount(customer.customer_id) }}项持仓</small>
          </span>
          <i :data-risk="customer.risk_flag" />
        </button>
        <EmptyState v-if="!customers.length" title="没有匹配客户" description="尝试使用更短的姓名或用户名。" />
      </div>
    </aside>
    <section class="advisor-main">
      <EmptyState v-if="!selected" title="选择一位客户开始服务" description="画像、持仓和投顾工具将在这里协同工作。" />
      <template v-else>
        <section class="client-banner">
          <div>
            <h2>{{ selected.real_name || selected.username }}</h2>
            <p>
              <span class="tag">{{ selected.customer_level || '普通客户' }}</span>
              <span class="tag">{{ formatRiskLevel(selected.risk_level) }}</span>
              <span>资产 {{ money(selected.total_assets) }}</span>
              <span>· {{ holdings.length }} 项持仓 · 市值 {{ money(totalValue) }}</span>
            </p>
          </div>
          <div class="banner-actions">
            <button class="secondary-button" :disabled="actionLoading" @click="runAllocation">资产配置</button>
            <button class="primary-button" :disabled="actionLoading" @click="runRecommend">生成推荐方案</button>
          </div>
        </section>
        <section class="metric-grid compact">
          <article><span>风险等级</span><strong>{{ formatRiskLevel(selected.risk_level) }}</strong><small>综合 {{ selected.risk_score || '—' }} 分</small></article>
          <article><span>资产规模</span><strong>{{ money(selected.total_assets) }}</strong><small>{{ selected.customer_level || '零售' }}</small></article>
          <article><span>画像置信度</span><strong>{{ selected.confidence_score ? `${Math.round(Number(selected.confidence_score) * 100)}%` : '—' }}</strong><small>持续校准</small></article>
          <article><span>持仓市值</span><strong>{{ money(totalValue) }}</strong><small>{{ holdings.length }} 项持仓</small></article>
        </section>
        <section class="advice-section">
          <div class="surface-card recommendation-card">
            <div class="card-heading"><h3>投顾输出</h3></div>
            <LoadingPanel v-if="actionLoading" text="Agent 正在调用画像、推荐与图谱工具…" />
            <template v-else-if="advice">
              <!-- 产品推荐列表 -->
              <div v-if="recommendations.length" class="product-list">
                <div v-for="(product, index) in recommendations" :key="index" class="product-item">
                  <div class="product-header">
                    <span class="product-index">{{ index + 1 }}</span>
                    <div class="product-title">
                      <strong>{{ product.product_name || product.title }}</strong>
                      <small>{{ product.product_type || product.risk_level || '' }}</small>
                    </div>
                    <span class="risk-tag" :data-level="product.risk_level">{{ product.risk_level || '—' }}</span>
                  </div>
                  <div class="product-body">
                    <p>{{ product.rationale || product.reason || product.description || '暂无详细描述' }}</p>
                    <div v-if="product.expected_return !== undefined" class="product-meta">
                      <span>预期收益</span>
                      <strong>{{ typeof product.expected_return === 'number' ? `${product.expected_return}%` : product.expected_return }}</strong>
                    </div>
                    <!-- NLP 洞察操作栏 -->
                    <div class="nlp-actions">
                      <button
                        class="nlp-btn"
                        :disabled="nlpLoading[`intro-${index}`]"
                        @click="generateInsight(product, index, 'intro')"
                      >
                        {{ nlpLoading[`intro-${index}`] ? '⏳ 生成中…' : '📝 产品介绍' }}
                      </button>
                      <button
                        class="nlp-btn nlp-btn-accent"
                        :disabled="nlpLoading[`advantage-${index}`]"
                        @click="generateInsight(product, index, 'advantage')"
                      >
                        {{ nlpLoading[`advantage-${index}`] ? '⏳ 生成中…' : '✨ 产品优势' }}
                      </button>
                    </div>
                    <!-- NLP 洞察结果 -->
                    <div v-if="nlpInsights[index]" class="nlp-insight">
                      <div class="nlp-insight-header">
                        <strong>{{ nlpInsights[index].type === 'intro' ? '📝 产品介绍' : '✨ 产品优势' }}</strong>
                        <button class="quiet-button nlp-close" @click="delete nlpInsights[index]">×</button>
                      </div>
                      <div class="nlp-insight-body" v-html="formatNlpContent(nlpInsights[index].content)" />
                    </div>
                  </div>
                </div>
              </div>
              <!-- 纯文本建议 -->
              <div v-else class="advice-content">
                <div class="advice-mark">策</div>
                <p>{{ advice }}</p>
              </div>
            </template>
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

interface ProductRecommendation {
  product_name?: string
  title?: string
  product_type?: string
  risk_level?: string
  rationale?: string
  reason?: string
  description?: string
  expected_return?: number | string
  allocation?: string
}

const keyword = ref('')
const customers = ref<Customer[]>([])
const selected = ref<Customer | null>(null)
const holdings = ref<Holding[]>([])
const totalValue = ref(0)
const loading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const advice = ref('')
const recommendations = ref<ProductRecommendation[]>([])
const holdingCounts = ref<Record<number, number>>({})
const money = (value: unknown) => value === undefined || value === null ? '—' : `¥${(Number(value) / 10_000).toFixed(1)}万`

// ===== 方案持久化：sessionStorage 按客户ID缓存投顾输出 =====
const ADVICE_CACHE_PREFIX = 'advisor:advice:'
function cacheKey(customerId: number) { return `${ADVICE_CACHE_PREFIX}${customerId}` }

function saveAdviceToCache(customerId: number) {
  try {
    const payload = {
      advice: advice.value,
      recommendations: recommendations.value,
      nlpInsights: nlpInsights.value,
      savedAt: Date.now(),
    }
    sessionStorage.setItem(cacheKey(customerId), JSON.stringify(payload))
  } catch { /* quota exceeded — ignore */ }
}

function restoreAdviceFromCache(customerId: number): boolean {
  try {
    const raw = sessionStorage.getItem(cacheKey(customerId))
    if (!raw) return false
    const payload = JSON.parse(raw)
    advice.value = payload.advice || ''
    recommendations.value = payload.recommendations || []
    // 恢复 NLP 洞察结果
    nlpInsights.value = payload.nlpInsights || {}
    return !!(payload.advice || (payload.recommendations && payload.recommendations.length))
  } catch {
    return false
  }
}

// ===== NLP 产品智能解读 =====
const nlpLoading = ref<Record<string, boolean>>({})
const nlpInsights = ref<Record<number, { type: string; content: string }>>({})

function formatNlpContent(content: string): string {
  // 处理 bullet points（• 开头）和换行
  return content
    .split('\n')
    .map(line => {
      const trimmed = line.trim()
      if (!trimmed) return ''
      if (trimmed.startsWith('•') || trimmed.startsWith('-') || trimmed.startsWith('*')) {
        return `<div class="nlp-bullet">${trimmed.replace(/^[•\-*]\s*/, '')}</div>`
      }
      return `<p>${trimmed}</p>`
    })
    .join('')
}

async function generateInsight(
  product: ProductRecommendation,
  index: number,
  insightType: 'intro' | 'advantage',
) {
  const loadKey = `${insightType}-${index}`
  nlpLoading.value[loadKey] = true
  try {
    const result = await post<any>('/nlp/product-insight', {
      product_name: product.product_name || product.title || '未知产品',
      product_type: product.product_type || '',
      risk_level: product.risk_level || '',
      expected_return: typeof product.expected_return === 'number' ? product.expected_return : null,
      rationale: product.rationale || product.reason || product.description || '',
      customer_risk_level: selected.value?.risk_level || '',
      insight_type: insightType,
    })
    const data = result.data || result
    nlpInsights.value[index] = {
      type: insightType,
      content: data.content || '',
    }
    // 持久化 NLP 结果
    if (selected.value) saveAdviceToCache(selected.value.customer_id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'NLP 生成失败'
  } finally {
    nlpLoading.value[loadKey] = false
  }
}

// 风险等级映射：c1/c2/c3/c4/c5 → C1保守型/C2稳健型/C3平衡型/C4进取型/C5激进型
const RISK_LEVEL_DISPLAY: Record<string, string> = {
  c1: 'C1保守型', C1: 'C1保守型',
  c2: 'C2稳健型', C2: 'C2稳健型',
  c3: 'C3平衡型', C3: 'C3平衡型',
  c4: 'C4进取型', C4: 'C4进取型',
  c5: 'C5激进型', C5: 'C5激进型',
}
function formatRiskLevel(level: unknown): string {
  if (!level) return '待评估'
  return RISK_LEVEL_DISPLAY[String(level)] || String(level)
}

function getHoldingCount(customerId: number): number {
  return holdingCounts.value[customerId] || 0
}

async function search() {
  loading.value = true
  error.value = ''
  try {
    const data = await get<{ items: Customer[] }>(`/customers?keyword=${encodeURIComponent(keyword.value)}&page_size=50`)
    customers.value = data.items
    if (!selected.value && customers.value.length) {
      // 尝试恢复上次选中的客户
      const lastId = sessionStorage.getItem('advisor:selectedCustomerId')
      const toSelect = lastId ? customers.value.find(c => String(c.customer_id) === lastId) : null
      await selectCustomer(toSelect || customers.value[0])
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '客户检索失败'
  } finally {
    loading.value = false
  }
}

async function selectCustomer(customer: Customer) {
  selected.value = customer
  advice.value = ''
  recommendations.value = []
  try {
    const [detail, data] = await Promise.all([
      get<Customer>(`/customers/${customer.customer_id}`),
      get<{ items: Holding[]; total_value: number }>(`/customers/${customer.customer_id}/holdings`),
    ])
    selected.value = detail
    holdings.value = data.items
    totalValue.value = data.total_value
    holdingCounts.value[customer.customer_id] = data.items.length
    // 尝试从 sessionStorage 恢复该客户的投顾方案
    restoreAdviceFromCache(customer.customer_id)
    // 记录当前选中客户，便于返回时恢复
    try { sessionStorage.setItem('advisor:selectedCustomerId', String(customer.customer_id)) } catch {}
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
    // 尝试解析产品推荐列表
    const recs = data.data?.recommendations || data.recommendations
    if (Array.isArray(recs) && recs.length) {
      recommendations.value = recs.map((r: any) => ({
        product_name: r.product_name || r.title || r.name || '',
        product_type: r.product_type || r.type || '',
        risk_level: r.risk_level || '',
        rationale: r.rationale || r.reason || r.description || '',
        expected_return: r.expected_return ?? r.return_rate,
        allocation: r.allocation || '',
      }))
      advice.value = ''
    } else {
      advice.value = data.reply || data.data?.reasoning || JSON.stringify(data.data?.recommendations || data, null, 2)
      recommendations.value = []
    }
    if (selected.value) saveAdviceToCache(selected.value.customer_id)
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
    const recs = data.data?.recommendations || data.recommendations
    if (Array.isArray(recs) && recs.length) {
      recommendations.value = recs.map((r: any) => ({
        product_name: r.product_name || r.title || r.name || '',
        product_type: r.product_type || r.type || '',
        risk_level: r.risk_level || '',
        rationale: r.rationale || r.reason || r.description || '',
        expected_return: r.expected_return ?? r.return_rate,
        allocation: r.allocation || '',
      }))
      advice.value = ''
    } else {
      advice.value = data.reply || data.data?.reasoning || JSON.stringify(data.data || data, null, 2)
      recommendations.value = []
    }
    if (selected.value) saveAdviceToCache(selected.value.customer_id)
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
/* 客户列表缩小 */
.customer-list > button {
  padding: 8px 7px;
}
.customer-list strong {
  font-size: 12px;
  line-height: 1.3;
}
.customer-list small {
  font-size: 9px;
  line-height: 1.4;
  color: #8896a6;
}
.customer-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.customer-info small {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 客户 Banner 标签 */
.client-banner p {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.client-banner .tag {
  padding: 3px 8px;
  border-radius: 99px;
  background: rgba(56, 189, 248, 0.1);
  color: #7dd3fc;
  font-size: 10px;
  font-weight: 600;
}

/* 投顾输出全宽 */
.advice-section {
  margin-top: 15px;
}
.advice-section .surface-card {
  min-height: 400px;
  max-height: none;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 产品推荐列表 */
.product-list {
  flex: 1;
  overflow-y: auto;
  padding-right: 4px;
  display: grid;
  gap: 12px;
}
.product-item {
  border: 1px solid #1e293b;
  border-radius: 10px;
  background: rgba(17, 24, 39, 0.6);
  overflow: hidden;
}
.product-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid #1e293b;
  background: rgba(56, 189, 248, 0.04);
}
.product-index {
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: rgba(56, 189, 248, 0.12);
  color: #7dd3fc;
  font-size: 11px;
  font-weight: 700;
}
.product-title {
  flex: 1;
  min-width: 0;
}
.product-title strong {
  display: block;
  color: #eff6ff;
  font-size: 14px;
  line-height: 1.3;
}
.product-title small {
  color: #8896a6;
  font-size: 10px;
}
.risk-tag {
  flex: 0 0 auto;
  padding: 3px 8px;
  border-radius: 99px;
  font-size: 9px;
  font-weight: 700;
  background: rgba(52, 211, 153, 0.1);
  color: #34d399;
}
.risk-tag[data-level="进取型"],
.risk-tag[data-level="R4"] {
  background: rgba(251, 113, 133, 0.1);
  color: #fda4af;
}
.risk-tag[data-level="稳健型"],
.risk-tag[data-level="R2"] {
  background: rgba(251, 191, 36, 0.1);
  color: #fbbf24;
}
.product-body {
  padding: 12px 14px;
}
.product-body p {
  margin: 0;
  color: #aebfd2;
  font-size: 12px;
  line-height: 1.7;
}
.product-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #1e293b;
  font-size: 11px;
  color: #8896a6;
}
.product-meta strong {
  color: #67e8f9;
  font-size: 13px;
}

/* NLP 智能解读 */
.nlp-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #1e293b;
}
.nlp-btn {
  flex: 1;
  padding: 6px 10px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid #30415a;
  border-radius: 7px;
  background: rgba(56, 189, 248, 0.06);
  color: #7dd3fc;
  cursor: pointer;
  transition: all .15s;
  white-space: nowrap;
}
.nlp-btn:hover:not(:disabled) {
  background: rgba(56, 189, 248, 0.15);
  border-color: #38bdf8;
}
.nlp-btn:disabled {
  opacity: .55;
  cursor: wait;
}
.nlp-btn-accent {
  background: rgba(167, 139, 250, 0.06);
  border-color: #475569;
  color: #c4b5fd;
}
.nlp-btn-accent:hover:not(:disabled) {
  background: rgba(167, 139, 250, 0.15);
  border-color: #a78bfa;
}
.nlp-insight {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid #1e293b;
}
.nlp-insight-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.nlp-insight-header strong {
  color: #e5edf9;
  font-size: 12px;
}
.nlp-close {
  padding: 0 6px !important;
  font-size: 14px !important;
  line-height: 1 !important;
  color: #8896a6 !important;
}
.nlp-insight-body {
  color: #c9d5e5;
  font-size: 12px;
  line-height: 1.7;
}
.nlp-insight-body p {
  margin: 0 0 6px;
}
.nlp-insight-body .nlp-bullet {
  padding-left: 12px;
  position: relative;
  margin-bottom: 4px;
}
.nlp-insight-body .nlp-bullet::before {
  content: "•";
  position: absolute;
  left: 0;
  color: #38bdf8;
}

/* 投顾输出文本 */
.advice-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.advice-content p {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.7;
  color: #c9d5e5;
  margin: 0;
}
.advice-mark {
  background: #0b7f78;
}

/* 滚动条 */
.product-list::-webkit-scrollbar,
.advice-content::-webkit-scrollbar {
  width: 4px;
}
.product-list::-webkit-scrollbar-thumb,
.advice-content::-webkit-scrollbar-thumb {
  background: #3c536e;
  border-radius: 2px;
}
</style>
