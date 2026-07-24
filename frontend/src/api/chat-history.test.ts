import { afterEach, describe, expect, it, vi } from 'vitest'

import { getChatHistory } from './chat'

afterEach(() => vi.unstubAllGlobals())

describe('getChatHistory', () => {
  it('maps the authenticated users most recent server conversation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: 200,
      message: 'success',
      data: { session_id: 'server-7', messages: [{ role: 'user', content: '上一个问题' }] },
    }), { status: 200 })))

    await expect(getChatHistory()).resolves.toEqual({
      sessionId: 'server-7',
      messages: [{ role: 'user', content: '上一个问题' }],
    })
  })
})
