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

export interface ConversationHistory {
  sessionId: string
  messages: ChatMessage[]
}

export const useConversationStore = defineStore('conversation', () => {
  const sessions = ref<Record<string, ConversationSession>>({})

  function sessionFor(userKey: string): ConversationSession {
    if (!sessions.value[userKey]) {
      sessions.value[userKey] = {
        conversationId: '',
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

  function hydrateUserSession(userKey: string, history: ConversationHistory) {
    const session = sessionFor(userKey)
    if (!session.messages.length && history.messages.length) {
      session.conversationId = history.sessionId || session.conversationId
      session.messages = history.messages
    }
  }

  function clearUserSession(userKey: string) {
    delete sessions.value[userKey]
  }

  function resetUserSession(userKey: string) {
    sessions.value[userKey] = {
      conversationId: '',
      messages: [],
    }
  }

  function clearAll() {
    sessions.value = {}
  }

  return {
    sessionFor,
    appendMessage,
    setSessionId,
    hydrateUserSession,
    clearUserSession,
    resetUserSession,
    clearAll,
  }
})
