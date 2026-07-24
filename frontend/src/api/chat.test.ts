import { afterEach, describe, expect, it, vi } from 'vitest'

import { createMockChatResponse, sendChat } from './chat'

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('sendChat', () => {
  it('adapts the platform conversation payload to the unified backend contract', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 200,
          message: 'success',
          trace_id: 'trace-009',
          data: {
            reply: '建议采用稳健配置。',
            agent: 'advisor',
            confidence: 0.92,
            session_id: 'server-session-001',
            data: {
              recommendations: [{
                product_name: '安盈固收增强组合',
                risk_level: '稳健型',
                reason: '与客户稳健偏好匹配。',
              }],
            },
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const response = await sendChat({
      user_id: '1',
      conversation_id: 'conversation-001',
      message: '我有 50 万，如何稳健配置？',
    })

    expect(response.answer).toBe('建议采用稳健配置。')
    expect(response.agent).toBe('advisor')
    expect(response.confidence).toBe(0.92)
    expect(response.metadata.session_id).toBe('server-session-001')
    expect(response.metadata.recommendation?.product).toBe('安盈固收增强组合')
    expect(fetchMock.mock.calls[0][0]).toContain('/api/chat')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      user_id: 1,
      user_role: '客户',
      session_id: 'conversation-001',
      message: '我有 50 万，如何稳健配置？',
    })
  })

  it('uses the authenticated backend user when the UI identity is not numeric', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ code: 200, message: 'success', trace_id: 'trace', data: { reply: '已收到', agent: 'service', confidence: 0.9, session_id: 'server-session' } }), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await sendChat({ user_id: 'customer-uuid', conversation_id: 'conversation-002', message: '测试消息' })

    expect(JSON.parse(fetchMock.mock.calls[0][1].body).user_id).toBe(0)
  })
})

describe('createMockChatResponse', () => {
  it('returns a financial recommendation with confidence and suggested actions', () => {
    const response = createMockChatResponse('我想做稳健投资')

    expect(response.answer).toContain('稳健')
    expect(response.confidence).toBeGreaterThan(0.8)
    expect(response.suggestions.length).toBeGreaterThan(0)
    expect(response.metadata.recommendation).toBeDefined()
  })
})
