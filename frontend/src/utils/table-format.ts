const CURRENCY_FIELDS = new Set([
  'amount',
  'balance',
  'total_assets',
  'current_value',
  'profit_loss',
  'min_amount',
  'min_purchase_amount',
  'transaction_amount',
  'total_amount',
])

function maskPhone(value: unknown): string {
  const phone = String(value)
  if (phone.includes('*') || phone.length < 7) return phone
  return `${phone.slice(0, 3)}****${phone.slice(-4)}`
}

function maskEmail(value: unknown): string {
  const email = String(value)
  if (email.includes('*')) return email
  const at = email.lastIndexOf('@')
  if (at <= 0 || at === email.length - 1) return email
  const local = email.slice(0, at)
  const visible = local.length <= 3 ? 1 : 3
  return `${local.slice(0, visible)}${'*'.repeat(Math.max(2, local.length - visible))}${email.slice(at)}`
}

export function formatTableCell(value: unknown, column: string): string {
  if (value === null || value === undefined) return '—'

  const normalizedColumn = column.toLowerCase()
  if (['phone', 'phone_number', 'mobile', 'mobile_phone', 'telephone', '手机号'].includes(normalizedColumn)) {
    return maskPhone(value)
  }
  if (['email', 'email_address', 'mail', '邮箱'].includes(normalizedColumn)) {
    return maskEmail(value)
  }

  if (CURRENCY_FIELDS.has(normalizedColumn)) {
    const amount = typeof value === 'number' ? value : Number(value)
    if (Number.isFinite(amount)) {
      return `¥${amount.toLocaleString('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`
    }
  }

  if (typeof value === 'number') return value.toLocaleString('zh-CN')
  return String(value)
}
