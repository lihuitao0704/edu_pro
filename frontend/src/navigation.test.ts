import { describe, expect, it } from 'vitest'

import { homeForRole, navigationForRole, navigationItems } from './navigation'

describe('navigationForRole', () => {
  it('uses stable icon keys rather than presentation glyphs', () => {
    for (const item of navigationItems) expect(item.icon).toMatch(/^[a-z-]+$/)
  })

  it('shows risk workbench only to risk and admin roles', () => {
    expect(navigationForRole('\u5ba2\u6237').map((item) => item.path)).not.toContain('/risk')
    expect(navigationForRole('\u98ce\u63a7\u4e13\u5458').map((item) => item.path)).toContain('/risk')
    expect(navigationForRole('\u7ba1\u7406\u5458').map((item) => item.path)).toContain('/risk')
  })

  it('shows the advisor workspace to advisors and administrators', () => {
    expect(navigationForRole('\u7406\u8d22\u987e\u95ee').map((item) => item.path)).toContain('/advisor')
    expect(navigationForRole('\u7ba1\u7406\u5458').map((item) => item.path)).toContain('/advisor')
  })

  it('opens each employee role on its primary workbench', () => {
    expect(homeForRole('\u5ba2\u6237')).toBe('/chat')
    expect(homeForRole('\u7406\u8d22\u987e\u95ee')).toBe('/advisor')
    expect(homeForRole('\u5ba2\u6237\u7ecf\u7406')).toBe('/operations')
    expect(homeForRole('\u98ce\u63a7\u4e13\u5458')).toBe('/risk')
    expect(homeForRole('\u7ba1\u7406\u5458')).toBe('/knowledge')
  })
})
