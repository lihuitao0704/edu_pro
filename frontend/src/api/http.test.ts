import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiRequest } from './http'

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('apiRequest', () => {
  it('adds the bearer token and unwraps a successful envelope', async () => {
    localStorage.setItem('wealth-token', 'jwt-token')
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ code: 200, message: 'success', data: { id: 3 }, trace_id: 'trace' }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const data = await apiRequest<{ id: number }>('/profile/3')

    expect(data.id).toBe(3)
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer jwt-token')
  })

  it('raises ApiError when the business code is not 200', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ code: 403, message: '适当性不匹配', data: null, trace_id: 'trace-403' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    await expect(apiRequest('/risk/suitability-check')).rejects.toEqual(
      expect.objectContaining({
        message: '适当性不匹配',
        code: 403,
        traceId: 'trace-403',
      }),
    )
  })
})
