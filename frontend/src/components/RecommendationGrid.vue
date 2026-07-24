<template>
  <section class="recommendation-grid-section surface-card">
    <div class="card-heading"><h3>推荐方案</h3><span class="rec-count">{{ recommendations.length }} 款产品</span></div>

    <div v-if="!recommendations.length" class="state-panel">
      <span class="state-symbol">🎯</span>
      <p>等待生成推荐方案</p>
      <small class="muted">点击"生成推荐方案"按钮获取产品推荐</small>
    </div>

    <div v-else class="product-grid">
      <div
        v-for="(product, index) in recommendations"
        :key="index"
        class="product-card"
        :data-risk="product.risk_level"
      >
        <div class="card-front">
          <div class="card-rank">{{ index + 1 }}</div>
          <div class="card-risk-badge" :data-level="product.risk_level">{{ product.risk_level || '—' }}</div>
          <h4>{{ product.product_name || product.title || '未知产品' }}</h4>
          <span class="card-type">{{ product.product_type || '理财产品' }}</span>

          <div class="card-metrics">
            <div class="metric">
              <span>预期收益</span>
              <strong>{{ typeof product.expected_return === 'number' ? `${product.expected_return}%` : (product.expected_return || '—') }}</strong>
            </div>
            <div class="metric">
              <span>匹配度</span>
              <strong>{{ product.match_score ? `${(product.match_score * 100).toFixed(0)}%` : '—' }}</strong>
            </div>
          </div>

          <div class="hover-hint">悬停查看详情</div>
        </div>

        <div class="card-detail">
          <p class="detail-reason">{{ product.rationale || product.reason || product.description || '暂无推荐理由' }}</p>
          <div v-if="product.allocation" class="detail-allocation">
            <span>建议配置</span>
            <strong>{{ product.allocation }}</strong>
          </div>

          <!-- NLP 洞察操作栏 -->
          <div class="nlp-actions">
            <button
              class="nlp-btn"
              :disabled="nlpLoading?.[`intro-${index}`]"
              @click.stop="emit('insight', product, index, 'intro')"
            >
              {{ nlpLoading?.[`intro-${index}`] ? '⏳ 生成中…' : '📝 产品介绍' }}
            </button>
            <button
              class="nlp-btn nlp-btn-accent"
              :disabled="nlpLoading?.[`advantage-${index}`]"
              @click.stop="emit('insight', product, index, 'advantage')"
            >
              {{ nlpLoading?.[`advantage-${index}`] ? '⏳ 生成中…' : '✨ 产品优势' }}
            </button>
          </div>

          <!-- NLP 洞察结果 -->
          <div v-if="nlpInsights && nlpInsights[index]" class="nlp-insight">
            <div class="nlp-insight-header">
              <strong>{{ nlpInsights[index].type === 'intro' ? '📝 产品介绍' : '✨ 产品优势' }}</strong>
              <button class="quiet-button nlp-close" @click.stop="emit('closeInsight', index)">×</button>
            </div>
            <div class="nlp-insight-body" v-html="formatNlpContent(nlpInsights[index].content)" />
          </div>
        </div>
      </div>
    </div>

    <p v-if="reasoning" class="rec-reasoning">{{ reasoning }}</p>
  </section>
</template>

<script setup lang="ts">
interface ProductRecommendation {
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

const props = defineProps<{
  recommendations: ProductRecommendation[]
  reasoning?: string
  nlpLoading?: Record<string, boolean>
  nlpInsights?: Record<number, { type: string; content: string }>
}>()

const emit = defineEmits<{
  insight: [product: ProductRecommendation, index: number, type: 'intro' | 'advantage']
  closeInsight: [index: number]
}>()

function formatNlpContent(content: string): string {
  if (!content) return ''
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
</script>

<style scoped>
.recommendation-grid-section {
  min-height: 320px;
  display: flex;
  flex-direction: column;
}
.rec-count {
  padding: 4px 12px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(167, 139, 250, 0.1);
  color: #c4b5fd;
}

/* 产品卡片网格 */
.product-grid {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  padding-right: 4px;
  overflow-y: auto;
}

/* 每张卡片 */
.product-card {
  position: relative;
  border: 1px solid #1e293b;
  border-radius: 14px;
  background: linear-gradient(145deg, rgba(21, 31, 49, 0.9), rgba(14, 22, 36, 0.9));
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
  overflow: hidden;
}
.product-card:hover {
  transform: translateY(-8px);
  box-shadow: 0 20px 50px rgba(56, 189, 248, 0.12), 0 4px 12px rgba(0, 0, 0, 0.3);
  border-color: rgba(56, 189, 248, 0.35);
  z-index: 2;
}

/* 风险等级边框色 */
.product-card[data-risk='R1'] { border-left: 3px solid #34d399; }
.product-card[data-risk='R2'] { border-left: 3px solid #60a5fa; }
.product-card[data-risk='R3'] { border-left: 3px solid #fbbf24; }
.product-card[data-risk='R4'] { border-left: 3px solid #fb7185; }
.product-card[data-risk='R5'] { border-left: 3px solid #ef4444; }

/* 卡片正面 */
.card-front {
  padding: 20px;
}
.card-rank {
  position: absolute;
  top: 14px;
  right: 16px;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: rgba(56, 189, 248, 0.1);
  color: #7dd3fc;
  font-size: 12px;
  font-weight: 800;
}
.card-risk-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 99px;
  font-size: 10px;
  font-weight: 700;
  margin-bottom: 10px;
  background: rgba(52, 211, 153, 0.1);
  color: #34d399;
}
.card-risk-badge[data-level='R2'] { background: rgba(96, 165, 250, 0.1); color: #60a5fa; }
.card-risk-badge[data-level='R3'] { background: rgba(251, 191, 36, 0.1); color: #fbbf24; }
.card-risk-badge[data-level='R4'] { background: rgba(251, 113, 133, 0.12); color: #fda4af; }
.card-risk-badge[data-level='R5'] { background: rgba(239, 68, 68, 0.15); color: #f87171; }

.card-front h4 {
  margin: 0 30px 4px 0;
  color: #e2e8f0;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.3;
}
.card-type {
  color: #64748b;
  font-size: 11px;
}
.card-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #1e293b;
}
.card-metrics .metric span {
  display: block;
  color: #64748b;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.card-metrics .metric strong {
  display: block;
  margin-top: 4px;
  color: #67e8f9;
  font-size: 19px;
  font-family: Georgia, serif;
}
.hover-hint {
  margin-top: 14px;
  color: #475569;
  font-size: 10px;
  text-align: center;
  transition: opacity 0.3s;
}
.product-card:hover .hover-hint {
  opacity: 0;
}

/* 卡片详情（hover 展开） */
.card-detail {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.45s ease, padding 0.45s ease;
  background: rgba(15, 23, 42, 0.5);
  border-top: 1px solid transparent;
}
.product-card:hover .card-detail {
  max-height: 320px;
  padding: 16px 20px 20px;
  border-top-color: #1e293b;
}
.detail-reason {
  margin: 0;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.7;
}
.detail-allocation {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(56, 189, 248, 0.06);
}
.detail-allocation span {
  color: #64748b;
  font-size: 11px;
}
.detail-allocation strong {
  color: #67e8f9;
  font-size: 13px;
}

/* NLP 操作栏 */
.nlp-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #1e293b;
}
.nlp-btn {
  flex: 1;
  padding: 6px 10px;
  font-size: 10px;
  font-weight: 600;
  border: 1px solid #334155;
  border-radius: 7px;
  background: rgba(56, 189, 248, 0.06);
  color: #7dd3fc;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.nlp-btn:hover:not(:disabled) {
  background: rgba(56, 189, 248, 0.15);
  border-color: #38bdf8;
}
.nlp-btn:disabled {
  opacity: 0.5;
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

/* NLP 洞察结果 */
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
  font-size: 11px;
}
.nlp-close {
  padding: 0 6px !important;
  font-size: 14px !important;
  line-height: 1 !important;
  color: #94a3b8 !important;
}
.nlp-insight-body {
  color: #cbd5e1;
  font-size: 11px;
  line-height: 1.7;
}
.nlp-insight-body p {
  margin: 0 0 4px;
}
.nlp-insight-body .nlp-bullet {
  padding-left: 12px;
  position: relative;
  margin-bottom: 3px;
}
.nlp-insight-body .nlp-bullet::before {
  content: "•";
  position: absolute;
  left: 0;
  color: #38bdf8;
}

.rec-reasoning {
  margin: 14px 0 0;
  padding: 10px 14px;
  border-left: 3px solid #a78bfa;
  border-radius: 6px;
  background: rgba(167, 139, 250, 0.06);
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.7;
}

/* 滚动条 */
.product-grid::-webkit-scrollbar {
  width: 4px;
}
.product-grid::-webkit-scrollbar-thumb {
  background: #3c536e;
  border-radius: 2px;
}

@media (max-width: 760px) {
  .product-grid {
    grid-template-columns: 1fr;
  }
}
</style>
