function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function inline(value: string): string {
  return value
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

export function renderAssistantMarkdown(source: string): string {
  const lines = escapeHtml(source || '').split(/\r?\n/)
  const output: string[] = []
  let list: 'ul' | 'ol' | null = null
  const closeList = () => {
    if (list) output.push(`</${list}>`)
    list = null
  }

  for (const line of lines) {
    const bullet = line.match(/^-\s+(.+)$/)
    const ordered = line.match(/^\d+\.\s+(.+)$/)
    if (bullet || ordered) {
      const next = bullet ? 'ul' : 'ol'
      if (list && list !== next) closeList()
      if (!list) output.push(`<${next}>`)
      list = next
      output.push(`<li>${inline((bullet || ordered)![1])}</li>`)
      continue
    }

    closeList()
    if (!line.trim()) continue
    if (line === '---') output.push('<hr>')
    else if (line.startsWith('### ')) output.push(`<h3>${inline(line.slice(4))}</h3>`)
    else if (line.startsWith('## ')) output.push(`<h2>${inline(line.slice(3))}</h2>`)
    else if (line.startsWith('# ')) output.push(`<h1>${inline(line.slice(2))}</h1>`)
    else if (line.startsWith('&gt; ')) output.push(`<blockquote>${inline(line.slice(5))}</blockquote>`)
    else output.push(`<p>${inline(line)}</p>`)
  }
  closeList()
  return output.join('')
}
