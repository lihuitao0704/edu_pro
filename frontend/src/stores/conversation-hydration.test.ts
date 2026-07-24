import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useConversationStore } from './conversation'

describe('conversation hydration', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('hydrates only an empty session for the matching user', () => {
    const conversations = useConversationStore()
    conversations.hydrateUserSession('customer-7', {
      sessionId: 'server-session-7',
      messages: [{ role: 'user', content: '上一个问题' }],
    })
    conversations.appendMessage('customer-8', { role: 'user', content: '其他用户的问题' })
    conversations.hydrateUserSession('customer-8', {
      sessionId: 'server-session-8',
      messages: [{ role: 'assistant', content: '不应覆盖' }],
    })

    expect(conversations.sessionFor('customer-7').conversationId).toBe('server-session-7')
    expect(conversations.sessionFor('customer-7').messages[0].content).toBe('上一个问题')
    expect(conversations.sessionFor('customer-8').messages[0].content).toBe('其他用户的问题')
  })
})
