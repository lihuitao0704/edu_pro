import { describe, expect, it } from 'vitest'

import { renderAssistantMarkdown } from './markdown'

describe('renderAssistantMarkdown', () => {
  it('escapes HTML and formats headings, lists and bold text', () => {
    const html = renderAssistantMarkdown('## 配置建议\n\n- **分散投资**\n- 保留流动性\n\n<script>alert(1)</script>')

    expect(html).toContain('<h2>配置建议</h2>')
    expect(html).toContain('<ul><li><strong>分散投资</strong></li><li>保留流动性</li></ul>')
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
    expect(html).not.toContain('<script>')
  })
})
