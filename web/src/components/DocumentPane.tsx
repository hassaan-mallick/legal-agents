import { useEffect, useMemo, useRef } from "react"
import type { Doc } from "@/types"
import { segment, type Needle } from "@/lib/highlight"
import { FIELD_TONE, VERDICT_TONE } from "@/lib/tone"
import { cn } from "@/lib/utils"

export function DocumentPane({
  doc,
  selectedKey,
  onSelect,
}: {
  doc: Doc
  selectedKey: string | null
  onSelect: (key: string) => void
}) {
  const needles = useMemo<Needle[]>(() => {
    if (doc.agent === "nda") {
      return doc
        .fields!.filter((f) => f.present && f.quote)
        .map((f) => ({
          key: f.name,
          text: f.quote!,
          tone: f.status === "escalated" ? FIELD_TONE.escalated.mark : FIELD_TONE.present.mark,
        }))
    }
    return doc.findings!.map((f, i) => ({
      key: `c${i}`,
      text: f.citation,
      tone: VERDICT_TONE[f.verdict].mark,
    }))
  }, [doc])

  const segments = useMemo(() => segment(doc.text, needles), [doc.text, needles])
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!selectedKey || !ref.current) return
    const box = ref.current
    const el = box.querySelector<HTMLElement>(`[data-key="${selectedKey}"]`)
    if (!el) return
    const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop
    box.scrollTo({ top: Math.max(0, top - box.clientHeight / 2) })
  }, [selectedKey])

  return (
    <div ref={ref} className="h-full overflow-y-auto">
      <article
        className={cn(
          "mx-auto max-w-[72ch] px-8 py-10 font-serif text-[15px] leading-7 text-foreground/90",
          "whitespace-pre-wrap [overflow-wrap:anywhere]",
        )}
      >
        {segments.map((s, i) =>
          s.key ? (
            <mark
              key={i}
              data-key={s.key}
              onClick={() => onSelect(s.key!)}
              className={cn(
                "cursor-pointer rounded-sm px-0.5 text-inherit transition-shadow",
                s.tone,
                selectedKey === s.key && "ring-2 ring-foreground/60 ring-offset-1 ring-offset-background",
              )}
            >
              {s.text}
            </mark>
          ) : (
            <span key={i}>{s.text}</span>
          ),
        )}
      </article>
    </div>
  )
}
