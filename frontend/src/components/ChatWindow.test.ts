import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useConversationStore } from '../stores/conversation'
import ChatWindow from './ChatWindow.vue'

const { streamChat } = vi.hoisted(() => ({ streamChat: vi.fn() }))

vi.mock('../utils/sse', () => ({ streamChat }))
vi.mock('../api/chat', () => ({
  createMockChatResponse: vi.fn(),
  getChatHistory: vi.fn().mockResolvedValue({ sessionId: '', messages: [] }),
}))

describe('ChatWindow', () => {
  let pinia: Pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    streamChat.mockReset()
    HTMLElement.prototype.scrollTo = vi.fn()
  })

  it('renders a non-advisor delta response and saves the server session id', async () => {
    streamChat.mockImplementation(async (_path, _body, onEvent) => {
      onEvent({ event: 'delta', data: { content: '已查询到赎回规则。' } })
      onEvent({ event: 'done', data: {
        reply: '已查询到赎回规则。',
        session_id: 'server-session-7',
        agent: 'customer_service',
        confidence: 0.91,
        data: { recommendations: [{ product_name: '稳健债券A' }] },
      } })
    })
    const wrapper = mount(ChatWindow, {
      props: { userId: 7 },
      global: { plugins: [pinia], stubs: { MessageCard: true } },
    })

    await wrapper.find('textarea').setValue('赎回规则是什么？')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const session = useConversationStore().sessionFor('7')
    expect(session.messages[1].content).toBe('已查询到赎回规则。')
    expect(session.conversationId).toBe('server-session-7')
    expect(session.messages[1].response?.agent).toBe('customer_service')
    expect(session.messages[1].response?.metadata.recommendation?.product).toBe('稳健债券A')
  })
})
