import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useConversationStore } from '../stores/conversation'
import ChatWindow from './ChatWindow.vue'

const { streamChat, getChatHistory } = vi.hoisted(() => ({
  streamChat: vi.fn(),
  getChatHistory: vi.fn(),
}))

vi.mock('../utils/sse', () => ({ streamChat }))
vi.mock('../api/chat', () => ({
  createMockChatResponse: vi.fn(),
  getChatHistory,
}))

describe('ChatWindow', () => {
  let pinia: Pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    streamChat.mockReset()
    getChatHistory.mockReset()
    getChatHistory.mockResolvedValue({ sessionId: '', messages: [] })
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

    const session = useConversationStore().sessionFor('客户:7')
    expect(session.messages[1].content).toBe('已查询到赎回规则。')
    expect(session.conversationId).toBe('server-session-7')
    expect(session.messages[1].response?.agent).toBe('customer_service')
    expect(session.messages[1].response?.metadata.recommendation?.product).toBe('稳健债券A')
  })

  it('starts blank and restores server history only after user asks', async () => {
    getChatHistory.mockResolvedValue({
      sessionId: 'history-session',
      messages: [{ role: 'user', content: '请问我的风险等级是什么？' }],
    })
    const wrapper = mount(ChatWindow, {
      props: { userId: 7, userRole: '风控专员' },
      global: { plugins: [pinia], stubs: { MessageCard: true } },
    })

    await flushPromises()
    expect(getChatHistory).not.toHaveBeenCalled()
    expect(useConversationStore().sessionFor('风控专员:7').messages).toEqual([])

    await wrapper.find('button[title="恢复当前账户最近一次对话"]').trigger('click')
    await flushPromises()

    expect(getChatHistory).toHaveBeenCalledOnce()
    expect(useConversationStore().sessionFor('风控专员:7').messages[0].content)
      .toBe('请问我的风险等级是什么？')
  })

  it('keeps all default prompts as router regression cases', () => {
    const wrapper = mount(ChatWindow, {
      props: { userId: 7 },
      global: { plugins: [pinia], stubs: { MessageCard: true } },
    })

    expect(wrapper.findAll('.quick-prompts button').map(button => button.text())).toEqual([
      '我有 50 万，如何稳健配置？',
      '帮我评估当前投资风险',
      '有哪些适合长期持有的产品？',
      '我想了解账户赎回流程',
    ])
  })

  it('renders clarification choices and sends the selected choice in the same session', async () => {
    streamChat.mockImplementation(async (_path, _body, onEvent) => {
      onEvent({ event: 'delta', data: { content: '请说明你的目标。' } })
      onEvent({ event: 'done', data: {
        reply: '请说明你的目标。',
        session_id: 'clarification-session',
        agent: 'router',
        confidence: 0.45,
        data: {
          clarification: {
            choices: ['查询明细或状态', '分析并给出建议', '执行具体业务操作'],
          },
          route_decision: {
            task: 'UNKNOWN',
            domain: 'HOLDING',
          },
        },
      } })
    })
    const wrapper = mount(ChatWindow, {
      props: { userId: 7 },
      global: { plugins: [pinia] },
    })

    await wrapper.find('textarea').setValue('看看我的持仓')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const choices = wrapper.findAll('.action-suggestions button')
    expect(choices).toHaveLength(3)
    await choices[0].trigger('click')
    await flushPromises()

    expect(streamChat).toHaveBeenCalledTimes(2)
    expect(streamChat.mock.calls[1][1]).toMatchObject({
      message: '查询明细或状态',
      session_id: 'clarification-session',
    })
  })
})
