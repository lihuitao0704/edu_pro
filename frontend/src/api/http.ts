import type { ApiEnvelope } from './types'

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

export class ApiError extends Error {
  code: number
  traceId: string
  data: any

  constructor(message: string, code: number, traceId = '', data: any = null) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.traceId = traceId
    this.data = data
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = localStorage.getItem('wealth-token')
  const headers: Record<string, string> = {
    ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...Object.fromEntries(new Headers(options.headers).entries()),
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  let envelope: ApiEnvelope<T>
  try {
    envelope = (await response.json()) as ApiEnvelope<T>
  } catch {
    throw new ApiError(`服务返回了无法解析的响应（HTTP ${response.status}）`, response.status)
  }
  if (!response.ok || envelope.code !== 200) {
    if (response.status === 401 || envelope.code === 401) {
      localStorage.removeItem('wealth-token')
      localStorage.removeItem('wealth-user')
    }
    throw new ApiError(
      envelope.message || `请求失败（HTTP ${response.status}）`,
      envelope.code || response.status,
      envelope.trace_id,
      (envelope as any).data ?? null,
    )
  }
  return envelope.data
}

export const get = <T>(path: string) => apiRequest<T>(path)
export const post = <T>(path: string, body?: unknown) =>
  apiRequest<T>(path, { method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body ?? {}) })
export const put = <T>(path: string, body?: unknown) =>
  apiRequest<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) })
export const remove = <T>(path: string) => apiRequest<T>(path, { method: 'DELETE' })
