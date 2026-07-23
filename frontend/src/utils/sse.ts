import { API_BASE } from '../api/http'

export interface SSEEvent {
  event: string
  data: Record<string, any>
}

export function consumeSSEText(text: string): SSEEvent[] {
  return text
    .split(/\r?\n\r?\n/)
    .map((frame) => frame.trim())
    .filter(Boolean)
    .map((frame) => {
      let event = 'message'
      const dataLines: string[] = []
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      const raw = dataLines.join('\n')
      return { event, data: raw ? JSON.parse(raw) : {} }
    })
}

export async function streamChat(
  path: string,
  body: unknown,
  onEvent: (event: SSEEvent) => void,
): Promise<void> {
  const token = localStorage.getItem('wealth-token')
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  })
  if (!response.ok || !response.body) {
    throw new Error(`流式请求失败（HTTP ${response.status}）`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    for (const frame of frames) {
      for (const event of consumeSSEText(`${frame}\n\n`)) onEvent(event)
    }
    if (done) break
  }
  if (buffer.trim()) {
    for (const event of consumeSSEText(buffer)) onEvent(event)
  }
}
