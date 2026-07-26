import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AppIntro from './AppIntro.vue'

describe('AppIntro', () => {
  it('announces readiness and emits complete when skipped', async () => {
    const wrapper = mount(AppIntro, { props: { visible: true } })

    expect(wrapper.get('[data-testid="app-intro"]').attributes('aria-label')).toBe('平台正在启动')

    await wrapper.get('button').trigger('click')

    expect(wrapper.emitted('complete')).toHaveLength(1)
  })
})
