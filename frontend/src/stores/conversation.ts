import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { ChatResponse } from '../api/chat'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  response?: ChatResponse
  isMock?: boolean
}

interface ConversationSession {
  conversationId: string
  messages: ChatMessage[]
}

export const useConversationStore = defineStore('conversation', () => {
  const sessions = ref<Record<string, ConversationSession>>({})

  function sessionFor(userKey: string): ConversationSession {
    if (!sessions.value[userKey]) {
      sessions.value[userKey] = {
        conversationId: `wealth-${userKey}-${Date.now().toString(36)}`,
        messages: [],
      }
    }
    return sessions.value[userKey]
  }

  function appendMessage(userKey: string, message: ChatMessage) {
    sessionFor(userKey).messages.push(message)
  }

  function setSessionId(userKey: string, conversationId: string) {
    sessionFor(userKey).conversationId = conversationId
  }

  function clearUserSession(userKey: string) {
    delete sessions.value[userKey]
  }

  function clearAll() {
    sessions.value = {}
  }

  return { sessionFor, appendMessage, setSessionId, clearUserSession, clearAll }
})
