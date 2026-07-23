import { describe, expect, it } from 'vitest'

import { homeForRole, navigationForRole } from './navigation'

describe('navigationForRole', () => {
  it('shows risk workbench only to risk and admin roles', () => {
    expect(navigationForRole('客户').map((item) => item.path)).not.toContain('/risk')
    expect(navigationForRole('风控专员').map((item) => item.path)).toContain('/risk')
    expect(navigationForRole('管理员').map((item) => item.path)).toContain('/risk')
  })

  it('shows the advisor workspace to advisors and administrators', () => {
    expect(navigationForRole('理财顾问').map((item) => item.path)).toContain('/advisor')
    expect(navigationForRole('管理员').map((item) => item.path)).toContain('/advisor')
  })

  it('opens each employee role on its primary workbench', () => {
    expect(homeForRole('客户')).toBe('/chat')
    expect(homeForRole('理财顾问')).toBe('/advisor')
    expect(homeForRole('客户经理')).toBe('/operations')
    expect(homeForRole('风控专员')).toBe('/risk')
    expect(homeForRole('管理员')).toBe('/knowledge')
  })
})
