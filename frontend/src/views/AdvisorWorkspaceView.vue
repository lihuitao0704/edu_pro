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
            <button class="secondary-button" :disabled="actionLoading" @click="runHoldingAnalysis">持仓</button>
            <button class="primary-button" :disabled="actionLoading" @click="runRecommend">生成推荐方案</button>
          </div>
        </section>
        <section class="metric-grid compact">
          <article><span>综合风险分</span><strong>{{ selected.risk_score ?? '—' }}</strong><small>/ 100</small></article>
          <article><span>画像置信度</span><strong>{{ selected.confidence_score ? `${Math.round(Number(selected.confidence_score) * 100)}%` : '—' }}</strong><small>证据融合</small></article>
          <article><span>资产规模</span><strong>{{ money(selected.total_assets) }}</strong><small>总资产估值</small></article>
          <article><span>适配等级</span><strong>{{ getProductRiskLevel(selected.risk_level) }}</strong><small>产品风险上限</small></article>
          <article class="aml-risk-card" :data-aml-level="selected.aml_risk_level">
            <span>AML风险等级</span>
            <strong>{{ getAmlRiskLabel(selected.aml_risk_level) }}</strong>
            <small>近30天预警: {{ selected.alert_count_30d ?? 0 }}条</small>
          </article>
        </section>

        <!-- 投顾输出板块 -->
        <section class="advice-section">
          <LoadingPanel v-if="actionLoading" text="Agent 正在调用画像、推荐与图谱工具…" />

          <!-- 资产配置饼图 — activeView 优先，避免回退到持仓 -->
          <AllocationPieChart
            v-else-if="activeView === 'allocation' && allocationData"
            :allocation="allocationData"
            :risk-level="allocationRiskLevel"
            :explanation="allocationExplanation"
          />
          <div v-else-if="activeView === 'allocation'" class="surface-card recommendation-card">
            <div class="card-heading"><h3>投顾输出</h3></div>
            <EmptyState title="未获取到资产配置数据" description="请确认客户画像完整后重试" />
          </div>

          <!-- 推荐方案卡片网格 — activeView 优先 -->
          <RecommendationGrid
            v-else-if="activeView === 'recommend' && recommendations.length"
            :recommendations="recommendations"
            :reasoning="adviceReasoning"
            :nlp-loading="nlpLoading"
            :nlp-insights="nlpInsights"
            :feedback-loading="feedbackLoading"
            @insight="onNlpInsight"
            @close-insight="onCloseNlpInsight"
            @reject="onRejectRecommendation"
          />
          <div v-else-if="activeView === 'recommend' && advice" class="surface-card recommendation-card">
            <div class="card-heading"><h3>投顾输出</h3></div>
            <div class="advice-content">
              <div class="advice-mark">策</div>
              <p>{{ advice }}</p>
            </div>
          </div>
          <div v-else-if="activeView === 'recommend'" class="surface-card recommendation-card">
            <div class="card-heading"><h3>投顾输出</h3></div>
            <EmptyState title="未获取到推荐方案" description="请稍后重试" />
          </div>

          <!-- 持仓面板 — 默认显示（没有 activeView 时） -->
          <HoldingPanel
            v-else-if="holdings.length"
            :holdings="holdings"
            :total-value="totalValue"
            :pl-summary="plSummary"
            :concentration="concentration"
            :industry-dist="industryDist"
            :industry-warning="industryWarning"
          />

          <!-- 纯文本建议（回退） -->
          <div v-else-if="advice" class="surface-card recommendation-card">
            <div class="card-heading"><h3>投顾输出</h3></div>
            <div class="advice-content">
              <div class="advice-mark">策</div>
              <p>{{ advice }}</p>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-else class="surface-card recommendation-card">
            <div class="card-heading"><h3>投顾输出</h3></div>
            <EmptyState title="暂无持仓数据" description="该客户当前没有任何持仓记录" />
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
import AllocationPieChart from '../components/AllocationPieChart.vue'
import EmptyState from '../components/EmptyState.vue'
import ErrorAlert from '../components/ErrorAlert.vue'
import HoldingPanel from '../components/HoldingPanel.vue'
import LoadingPanel from '../components/LoadingPanel.vue'
import RecommendationGrid from '../components/RecommendationGrid.vue'
import { onProfileUpdated } from '../utils/profile-events'

interface ProductRecommendation {
  recommendation_id?: number
  product_name?: string
  title?: string
  product_type?: string
  risk_level?: string
  rationale?: string
  reason?: string
  description?: string
  expected_return?: number | string
  match_score?: number
  allocation?: string
}

interface IndustryDistItem {
  name: string
  productCount: number
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
const adviceReasoning = ref('')
const recommendations = ref<ProductRecommendation[]>([])
const feedbackLoading = ref<Record<number, boolean>>({})
const holdingCounts = ref<Record<number, number>>({})

// 当前展示视图：allocation | holding | recommend | text
const activeView = ref<'allocation' | 'holding' | 'recommend' | 'text' | ''>('')

// 资产配置数据
const allocationData = ref<Record<string, number> | null>(null)
const allocationRiskLevel = ref('')
const allocationExplanation = ref('')

// 持仓分析数据
const plSummary = ref<any>(null)
const concentration = ref<any>(null)
const industryDist = ref<IndustryDistItem[]>([])
const industryWarning = ref<string | null>(null)

const money = (value: unknown) => value === undefined || value === null ? '—' : `¥${(Number(value) / 10_000).toFixed(1)}万`

// ===== 方案持久化 =====
const ADVICE_CACHE_PREFIX = 'advisor:advice:'

function cacheKey(customerId: number) { return `${ADVICE_CACHE_PREFIX}${customerId}` }

function saveAdviceToCache(customerId: number) {
  try {
    const payload = {
      advice: advice.value,
      adviceReasoning: adviceReasoning.value,
      recommendations: recommendations.value,
      allocationData: allocationData.value,
      allocationRiskLevel: allocationRiskLevel.value,
      allocationExplanation: allocationExplanation.value,
      activeView: activeView.value,
      nlpInsights: nlpInsights.value,
      plSummary: plSummary.value,
      concentration: concentration.value,
      industryDist: industryDist.value,
      industryWarning: industryWarning.value,
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
    adviceReasoning.value = payload.adviceReasoning || ''
    recommendations.value = payload.recommendations || []
    allocationData.value = payload.allocationData || null
    allocationRiskLevel.value = payload.allocationRiskLevel || ''
    allocationExplanation.value = payload.allocationExplanation || ''
    activeView.value = payload.activeView || ''
    nlpInsights.value = payload.nlpInsights || {}
    plSummary.value = payload.plSummary || null
    concentration.value = payload.concentration || null
    industryDist.value = payload.industryDist || []
    industryWarning.value = payload.industryWarning || null
    return true
  } catch {
    return false
  }
}

// ===== NLP 产品智能解读 =====
const nlpLoading = ref<Record<string, boolean>>({})
const nlpInsights = ref<Record<number, { type: string; content: string }>>({})

async function onNlpInsight(product: ProductRecommendation, index: number, insightType: 'intro' | 'advantage') {
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
    if (selected.value) saveAdviceToCache(selected.value.customer_id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'NLP 生成失败'
  } finally {
    nlpLoading.value[loadKey] = false
  }
}

function onCloseNlpInsight(index: number) {
  delete nlpInsights.value[index]
  if (selected.value) saveAdviceToCache(selected.value.customer_id)
}

// 风险等级映射
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

function getProductRiskLevel(level: unknown): string {
  const map: Record<string, string> = {
    c1: 'R1', C1: 'R1', c2: 'R2', C2: 'R2',
    c3: 'R3', C3: 'R3', c4: 'R4', C4: 'R4',
    c5: 'R5', C5: 'R5',
  }
  return map[String(level)] || '—'
}

function getAmlRiskLabel(level?: string): string {
  const map: Record<string, string> = { high: '高', medium: '中', low: '低' }
  return map[level || ''] || '低'
}

function getHoldingCount(customerId: number): number {
  return holdingCounts.value[customerId] || 0
}

// ===== 提取 API 响应中的结构化数据 =====
function extractApiData(result: any): any {
  // 响应可能是 { data: { data: { ... } } } 或 { data: { ... } }
  const outerData = result.data || result
  // 如果外层有 data 且 data 是对象（UnifiedChatResponse），取内层
  return outerData.data || outerData
}

async function search() {
  loading.value = true
  error.value = ''
  try {
    const data = await get<{ items: Customer[] }>(`/customers?keyword=${encodeURIComponent(keyword.value)}&page_size=50`)
    customers.value = data.items
    if (!selected.value && customers.value.length) {
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
  adviceReasoning.value = ''
  recommendations.value = []
  allocationData.value = null
  allocationRiskLevel.value = ''
  allocationExplanation.value = ''
  activeView.value = ''
  plSummary.value = null
  concentration.value = null
  industryDist.value = []
  industryWarning.value = null
  try {
    const [detail, data] = await Promise.all([
      get<Customer>(`/customers/${customer.customer_id}`),
      get<{ items: Holding[]; total_value: number }>(`/customers/${customer.customer_id}/holdings`),
    ])
    selected.value = detail
    holdings.value = data.items
    totalValue.value = data.total_value
    holdingCounts.value[customer.customer_id] = data.items.length

    // 从原始持仓数据直接推算盈亏汇总 & 集中度（无需等待 /chat API）
    if (data.items.length > 0) {
      const totalPL = data.items.reduce((s, h) => s + (Number(h.profit_loss) || 0), 0)
      const profits = data.items.filter(h => (Number(h.profit_loss) || 0) > 0).length
      const losses = data.items.filter(h => (Number(h.profit_loss) || 0) < 0).length
      const avgRatio = data.items.length > 0
        ? data.items.reduce((s, h) => s + (Number(h.profit_ratio) || 0), 0) / data.items.length
        : 0
      plSummary.value = {
        total_value: data.total_value,
        total_profit_loss: Math.round(totalPL * 100) / 100,
        profit_count: profits,
        loss_count: losses,
        flat_count: data.items.length - profits - losses,
        avg_profit_ratio: Math.round(avgRatio * 10000) / 10000,
      }
      const maxSingle = Math.max(...data.items.map(h => Number(h.current_value) || 0))
      concentration.value = {
        total_value: data.total_value,
        product_count: data.items.length,
        max_single_ratio: data.total_value > 0 ? Math.round((maxSingle / data.total_value) * 100) / 100 : 0,
        warning: data.total_value > 0 && maxSingle / data.total_value > 0.5 ? '单产品持仓过于集中' : null,
      }
    }

    restoreAdviceFromCache(customer.customer_id)
    try { sessionStorage.setItem('advisor:selectedCustomerId', String(customer.customer_id)) } catch {}
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '客户详情加载失败'
  }
}

// ===== 三大功能 =====

async function runAllocation() {
  if (!selected.value) return
  actionLoading.value = true
  error.value = ''
  activeView.value = 'allocation'
  try {
    const result = await post<Record<string, any>>('/advisor/allocation', {
      customer_id: selected.value.customer_id,
    })
    const inner = extractApiData(result)

    // 提取 allocation 数据（用于饼图）
    // 兼容两种结构：
    //   嵌套：{customer_id, risk_level, allocation: {"货币类": 20, ...}, explanation}
    //   扁平：{"货币类": 20, "债券类": 50, ...}
    const alloc = inner?.allocation
    if (alloc && typeof alloc === 'object') {
      if (alloc.allocation && typeof alloc.allocation === 'object' && Object.keys(alloc.allocation).length > 0) {
        // 嵌套结构 → 提取内层 allocation map
        allocationData.value = alloc.allocation
        allocationRiskLevel.value = alloc.risk_level || inner?.customer_profile?.risk_level || ''
        allocationExplanation.value = alloc.explanation || inner?.reasoning || ''
      } else {
        // 扁平结构 → 验证值是数值类型
        const entries = Object.entries(alloc).filter(([, v]) => typeof v === 'number' && v > 0)
        if (entries.length > 0) {
          allocationData.value = alloc
          allocationRiskLevel.value = inner?.customer_profile?.risk_level || ''
          allocationExplanation.value = inner?.reasoning || ''
        }
      }
    }

    // 同时提取推荐产品（如果有）
    const recs = inner?.recommendations
    if (Array.isArray(recs) && recs.length) {
      recommendations.value = recs.map((r: any) => ({
        product_name: r.product_name || r.title || r.name || '',
        recommendation_id: r.recommendation_id,
        product_type: r.product_type || r.type || '',
        risk_level: r.risk_level || '',
        rationale: r.rationale || r.reason || r.description || '',
        expected_return: r.expected_return ?? r.return_rate,
        match_score: r.match_score,
        allocation: r.allocation || '',
      }))
      adviceReasoning.value = inner?.reasoning || ''
    }

    if (!allocationData.value && !recommendations.value.length) {
      advice.value = inner?.reply || JSON.stringify(inner, null, 2)
      activeView.value = 'text'
    }

    if (selected.value) saveAdviceToCache(selected.value.customer_id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '资产配置生成失败'
  } finally {
    actionLoading.value = false
  }
}

async function onRejectRecommendation(product: ProductRecommendation, index: number) {
  if (!selected.value || !product.recommendation_id) return
  feedbackLoading.value = { ...feedbackLoading.value, [index]: true }
  try {
    await post(`/advisor/recommendations/${product.recommendation_id}/feedback`, {
      customer_id: selected.value.customer_id,
      status: 'rejected',
      reason: '投顾工作台标记不感兴趣',
    })
    recommendations.value = recommendations.value.filter((_, itemIndex) => itemIndex !== index)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '推荐反馈提交失败'
  } finally {
    const next = { ...feedbackLoading.value }
    delete next[index]
    feedbackLoading.value = next
  }
}

async function runHoldingAnalysis() {
  if (!selected.value) return
  actionLoading.value = true
  error.value = ''
  activeView.value = 'holding'
  try {
    // 同时获取基础持仓数据和深度分析
    const [holdingsResult, analysisResult] = await Promise.allSettled([
      get<{ items: Holding[]; total_value: number }>(`/customers/${selected.value.customer_id}/holdings`),
      post<Record<string, any>>('/chat', {
        message: `分析客户${selected.value.customer_id}的持仓情况`,
        session_id: '',
        user_id: selected.value.customer_id,
        user_role: '理财顾问',
      }),
    ])

    // 基础持仓数据
    if (holdingsResult.status === 'fulfilled') {
      holdings.value = holdingsResult.value.items
      totalValue.value = holdingsResult.value.total_value
    }

    // 深度分析数据
    if (analysisResult.status === 'fulfilled') {
      const inner = extractApiData(analysisResult.value)
      const ha = inner?.holdings_analysis

      if (ha) {
        plSummary.value = ha.profit_loss_summary || null
        concentration.value = ha.concentration || null
        industryDist.value = (ha.industry_distribution?.industries || []).map((d: any) => ({
          name: d.name,
          productCount: d.product_count || d.productCount || 0,
        }))
        industryWarning.value = ha.industry_distribution?.warning || null
      }

      // LLM 回复作为参考
      adviceReasoning.value = inner?.reasoning || ''
      if (inner?.reply) advice.value = inner.reply
    }

    if (selected.value) saveAdviceToCache(selected.value.customer_id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '持仓分析失败'
  } finally {
    actionLoading.value = false
  }
}

async function runRecommend() {
  if (!selected.value) return
  actionLoading.value = true
  error.value = ''
  activeView.value = 'recommend'
  try {
    const result = await post<Record<string, any>>('/advisor', {
      message: `为客户${selected.value.customer_id}推荐3款适合的产品`,
      session_id: '',
      user_id: selected.value.customer_id,
      customer_id: selected.value.customer_id,
    })
    const inner = extractApiData(result)

    const recs = inner?.data?.recommendations || inner?.recommendations
    if (Array.isArray(recs) && recs.length) {
      recommendations.value = recs.map((r: any) => ({
        product_name: r.product_name || r.title || r.name || '',
        recommendation_id: r.recommendation_id,
        product_type: r.product_type || r.type || '',
        risk_level: r.risk_level || '',
        rationale: r.rationale || r.reason || r.description || '',
        expected_return: r.expected_return ?? r.return_rate,
        match_score: r.match_score,
        allocation: r.allocation || '',
      }))
      adviceReasoning.value = inner?.reasoning || ''
      advice.value = inner?.narrative || inner?.reply || ''
    } else {
      advice.value = inner?.reply || JSON.stringify(inner, null, 2)
      recommendations.value = []
      activeView.value = 'text'
    }

    // 同时提取 allocation（smart_recommend 可能一并返回）
    if (inner?.allocation) {
      const alloc = inner.allocation
      if (alloc.allocation && typeof alloc.allocation === 'object') {
        allocationData.value = alloc.allocation
        allocationRiskLevel.value = alloc.risk_level || ''
        allocationExplanation.value = alloc.explanation || ''
      }
    }

    if (selected.value) saveAdviceToCache(selected.value.customer_id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '推荐生成失败'
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
/* 五指标同行 */
.metric-grid.compact {
  grid-template-columns: repeat(5, 1fr);
}
.aml-risk-card[data-aml-level='high'] {
  border-left: 3px solid #fb7185;
}
.aml-risk-card[data-aml-level='medium'] {
  border-left: 3px solid #f59e0b;
}
.aml-risk-card[data-aml-level='low'] {
  border-left: 3px solid #34d399;
}

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
.advice-content::-webkit-scrollbar {
  width: 4px;
}
.advice-content::-webkit-scrollbar-thumb {
  background: #3c536e;
  border-radius: 2px;
}
</style>
