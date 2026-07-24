import { get, post } from './http'

export interface ChatRequest {
  user_id: string | number
  conversation_id: string
  message: string
  user_role?: string
}

export interface Recommendation {
  title: string
  risk_level: '低风险' | '稳健型' | '进取型'
  product: string
  allocation: string
  rationale: string
}

export interface ChatResponse {
  answer: string
  agent: string
  confidence: number
  suggestions: string[]
  metadata: {
    recommendation?: Recommendation
    risk_level?: string
    trace_id?: string
    session_id?: string
  }
}

export interface ChatHistory {
  sessionId: string
  messages: Array<{ role: 'user' | 'assistant'; content: string }>
}

interface UnifiedChatPayload {
  reply: string
  agent: string
  confidence: number
  session_id: string
  data?: {
    recommendations?: Array<{
      product_name?: string
      risk_level?: Recommendation['risk_level']
      reason?: string
      expected_return?: number
    }>
    risk_level?: string
  }
}

export async function sendChat(payload: ChatRequest): Promise<ChatResponse> {
  const numericUserId = Number(payload.user_id)
  const response = await post<UnifiedChatPayload>('/chat', {
    message: payload.message,
    session_id: payload.conversation_id,
    user_id: Number.isFinite(numericUserId) ? numericUserId : 0,
    user_role: payload.user_role || '客户',
  })
  return normalizeUnifiedChatResponse(response)
}

export async function getChatHistory(): Promise<ChatHistory> {
  const response = await get<{
    session_id?: string
    messages?: Array<{ role: 'user' | 'assistant'; content: string }>
  }>('/chat/history')
  return {
    sessionId: response.session_id || '',
    messages: response.messages || [],
  }
}

function normalizeUnifiedChatResponse(response: UnifiedChatPayload): ChatResponse {
  const product = response.data?.recommendations?.[0]
  const recommendation = product?.product_name
    ? {
        title: '智能匹配产品建议',
        risk_level: product.risk_level || '稳健型',
        product: product.product_name,
        allocation: product.expected_return ? `参考收益 ${product.expected_return}%` : '查看产品详情',
        rationale: product.reason || '该产品由投资建议引擎根据客户画像与适当性规则筛选。',
      }
    : undefined

  return {
    answer: response.reply,
    agent: response.agent,
    confidence: response.confidence,
    suggestions: recommendation ? ['查看方案详情', '比较同类产品', '预约专属顾问'] : [],
    metadata: { risk_level: response.data?.risk_level, recommendation, session_id: response.session_id },
  }
}

export function createMockChatResponse(message: string): ChatResponse {
  const isRiskQuestion = /风险|测评|波动|回撤/.test(message)
  const isAccountQuestion = /账户|赎回|转账|交易/.test(message)

  if (isRiskQuestion) {
    return {
      answer: '根据您的历史偏好与当前持仓结构，建议将权益类资产控制在可承受波动范围内，并在操作前完成风险测评更新。',
      agent: 'risk',
      confidence: 0.95,
      suggestions: ['开始风险测评', '查看风险提示', '预约人工顾问'],
      metadata: { risk_level: '稳健型' },
    }
  }

  if (isAccountQuestion) {
    return {
      answer: '已为您识别到账户业务场景。涉及资金变动的操作需要在交易确认页完成二次校验。',
      agent: 'operations',
      confidence: 0.97,
      suggestions: ['查看账户资产', '发起业务操作', '联系专属顾问'],
      metadata: {},
    }
  }

  return {
    answer: '结合您的稳健投资偏好，建议采用“固收打底、权益增益、现金管理”的三层配置，并分批执行以平滑市场波动。',
    agent: 'investment',
    confidence: 0.92,
    suggestions: ['查看方案详情', '比较同类产品', '预约专属顾问'],
    metadata: {
      risk_level: '稳健型',
      recommendation: {
        title: '稳健增值配置方案',
        risk_level: '稳健型',
        product: '安盈固收增强组合',
        allocation: '建议配置 30 万元',
        rationale: '以中低波动资产为底仓，保留流动性并适度参与权益市场机会。',
      },
    },
  }
}
