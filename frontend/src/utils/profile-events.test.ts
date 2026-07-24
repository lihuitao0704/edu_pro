import { afterEach, describe, expect, it, vi } from 'vitest'

import { onProfileUpdated, publishProfileUpdated } from './profile-events'

describe('profile update events', () => {
  afterEach(() => window.dispatchEvent(new Event('wealth:profile-updated:cleanup')))

  it('stops notifying after unsubscribe', () => {
    const listener = vi.fn()
    const stop = onProfileUpdated(listener)

    publishProfileUpdated(7)
    stop()
    publishProfileUpdated(8)

    expect(listener).toHaveBeenCalledTimes(1)
    expect(listener).toHaveBeenCalledWith(7)
  })
})
