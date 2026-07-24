import { describe, expect, it } from 'vitest'

import { agentDirectory, executionTrace, platformMetrics } from './platform'

describe('platform dashboard mock data', () => {
  it('exposes the five operational agents with health metrics', () => {
    expect(agentDirectory).toHaveLength(5)
    expect(agentDirectory.every((agent) => agent.status === 'Online' && agent.successRate > 0.9)).toBe(true)
  })

  it('models a complete routing trace and the required operating metrics', () => {
    expect(executionTrace.map((node) => node.name)).toContain('Router Agent')
    expect(executionTrace.length).toBeGreaterThanOrEqual(5)
    expect(platformMetrics).toHaveLength(4)
  })
})
