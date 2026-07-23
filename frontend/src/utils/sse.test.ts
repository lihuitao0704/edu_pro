import { describe, expect, it } from 'vitest'

import { consumeSSEText } from './sse'

describe('consumeSSEText', () => {
  it('parses split SSE frames and keeps unicode content', () => {
    const events = consumeSSEText(
      'event: meta\ndata: {"session_id":"s1"}\n\n' +
        'event: delta\ndata: {"content":"稳健"}\n\n' +
        'event: done\ndata: {"session_id":"s1"}\n\n',
    )

    expect(events.map((event) => event.event)).toEqual(['meta', 'delta', 'done'])
    expect(events[1].data.content).toBe('稳健')
  })
})
