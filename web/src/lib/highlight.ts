/** Locate needles in a document and split it into renderable segments. */

export interface Needle {
  key: string
  text: string
  tone: string
}

export interface Segment {
  text: string
  key?: string
  tone?: string
}

function flexiblePattern(needle: string): RegExp {
  // The harness normalises whitespace and curly quotes before locating a quote;
  // mirror that loosely so an exact-match quote still lands in the raw text.
  const parts = needle
    .trim()
    .split(/\s+/)
    .map((w) =>
      w
        .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
        .replace(/["“”]/g, "[\"“”]")
        .replace(/['‘’]/g, "['‘’]"),
    )
  return new RegExp(parts.join("\\s+"))
}

export function segment(text: string, needles: Needle[]): Segment[] {
  const claimed: { start: number; end: number; key: string; tone: string }[] = []
  for (const n of needles) {
    if (!n.text) continue
    const re = flexiblePattern(n.text)
    let from = 0
    let placed = false
    while (from < text.length) {
      const m = re.exec(text.slice(from))
      if (!m) break
      const start = from + m.index
      const end = start + m[0].length
      const overlaps = claimed.some((c) => start < c.end && end > c.start)
      if (!overlaps) {
        claimed.push({ start, end, key: n.key, tone: n.tone })
        placed = true
        break
      }
      from = end
    }
    if (!placed) continue
  }
  claimed.sort((a, b) => a.start - b.start)
  const out: Segment[] = []
  let cursor = 0
  for (const c of claimed) {
    if (c.start > cursor) out.push({ text: text.slice(cursor, c.start) })
    out.push({ text: text.slice(c.start, c.end), key: c.key, tone: c.tone })
    cursor = c.end
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor) })
  return out
}
