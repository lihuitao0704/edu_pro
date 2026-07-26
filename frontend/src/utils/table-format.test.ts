import { describe, expect, it } from 'vitest'

import { formatTableCell } from './table-format'

describe('formatTableCell', () => {
  it('masks phone numbers and keeps identifiers as text', () => {
    expect(formatTableCell('15448401154', 'phone')).toBe('154****1154')
    expect(formatTableCell('00123', 'product_code')).toBe('00123')
  })

  it('formats only known currency fields as currency', () => {
    expect(formatTableCell(15448401154, 'customer_id')).toBe('15,448,401,154')
    expect(formatTableCell('15448.4', 'balance')).toBe('¥15,448.40')
  })

  it('renders masked contact data unchanged', () => {
    expect(formatTableCell('154****1154', 'phone')).toBe('154****1154')
    expect(formatTableCell('zha*****@example.com', 'email')).toBe(
      'zha*****@example.com',
    )
    expect(formatTableCell('zhangsan@example.com', 'email')).toBe(
      'zha*****@example.com',
    )
  })
})
