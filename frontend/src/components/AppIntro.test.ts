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

  it('keeps keyboard focus on its only action while visible', async () => {
    const wrapper = mount(AppIntro, { attachTo: document.body, props: { visible: true } })
    const dialog = wrapper.get('[data-testid="app-intro"]')
    const skip = wrapper.get('button')

    expect(dialog.attributes('role')).toBe('dialog')
    expect(dialog.attributes('aria-modal')).toBe('true')
    await wrapper.vm.$nextTick()
    expect(document.activeElement).toBe(skip.element)

    await skip.trigger('keydown.tab')

    expect(document.activeElement).toBe(skip.element)
    wrapper.unmount()
  })
})
