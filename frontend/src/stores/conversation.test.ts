import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useConversationStore } from './conversation'

describe('conversation store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('keeps a user conversation and its server session across view remounts', () => {
    const conversations = useConversationStore()

    conversations.appendMessage('customer-7', { role: 'user', content: '我的持仓风险如何？' })
    conversations.setSessionId('customer-7', 'server-session-7')

    expect(conversations.sessionFor('customer-7').messages).toEqual([
      { role: 'user', content: '我的持仓风险如何？' },
    ])
    expect(conversations.sessionFor('customer-7').conversationId).toBe('server-session-7')
  })

  it('isolates conversations for different users', () => {
    const conversations = useConversationStore()
    conversations.appendMessage('customer-7', { role: 'user', content: '客户 7 的消息' })
    conversations.appendMessage('customer-8', { role: 'user', content: '客户 8 的消息' })

    expect(conversations.sessionFor('customer-7').messages).toHaveLength(1)
    expect(conversations.sessionFor('customer-8').messages[0].content).toBe('客户 8 的消息')
  })
})
