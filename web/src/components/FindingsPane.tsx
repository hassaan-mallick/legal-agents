import type { Decision, Doc } from "@/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { FIELD_LABEL, FIELD_TONE, VERDICT_TONE } from "@/lib/tone"
import { cn } from "@/lib/utils"
import { Check, ExternalLink, ShieldAlert, Undo2 } from "lucide-react"

function fmtValue(v: unknown): string {
  if (v == null) return "—"
  if (Array.isArray(v)) return v.map(String).join(", ")
  return String(v)
}

function DecisionButtons({
  value,
  onChange,
}: {
  value: Decision
  onChange: (d: Decision) => void
}) {
  return (
    <div className="flex gap-1">
      <Button
        size="sm"
        variant={value === "accepted" ? "default" : "outline"}
        className="h-7 px-2 text-xs"
        onClick={() => onChange(value === "accepted" ? null : "accepted")}
      >
        <Check className="size-3.5" /> Accept
      </Button>
      <Button
        size="sm"
        variant={value === "sent_back" ? "destructive" : "outline"}
        className="h-7 px-2 text-xs"
        onClick={() => onChange(value === "sent_back" ? null : "sent_back")}
      >
        <Undo2 className="size-3.5" /> Send back
      </Button>
    </div>
  )
}

export function FindingsPane({
  doc,
  selectedKey,
  onSelect,
  decisions,
  onDecide,
}: {
  doc: Doc
  selectedKey: string | null
  onSelect: (key: string) => void
  decisions: Record<string, Decision>
  onDecide: (key: string, d: Decision) => void
}) {
  const escalation = doc.status === "escalated" && (
    <div className="mx-3 mt-3 flex items-start gap-2 rounded-md border border-red-300/60 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
      <ShieldAlert className="mt-0.5 size-4 shrink-0" />
      <div>
        <div className="font-medium">Escalated to the named reviewer</div>
        <ul className="mt-1 list-disc pl-4 text-[13px]">
          {doc.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        {doc.injection ? (
          <p className="mt-1 text-[13px]">
            The document contains text that addresses the model directly. The harness flagged it before
            anything was extracted; the model's answers were not trusted.
          </p>
        ) : null}
      </div>
    </div>
  )

  if (doc.agent === "nda") {
    const fields = doc.fields!
    const found = fields.filter((f) => f.present).length
    const located = fields.filter((f) => f.present && f.quote_match === "exact").length
    return (
      <div className="flex h-full flex-col">
        <div className="grid grid-cols-3 gap-px border-b bg-border">
          <Stat label="Terms found" value={`${found} / 12`} />
          <Stat label="Quotes located" value={`${located} / ${found}`} />
          <Stat label="Type" value={doc.doc_type?.replace(/_/g, " ") ?? "—"} />
        </div>
        {escalation}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <ul className="flex flex-col p-3">
            {fields.map((f) => {
              const tone = f.status === "escalated" ? FIELD_TONE.escalated : f.present ? FIELD_TONE.present : FIELD_TONE.absent
              const selected = selectedKey === f.name
              return (
                <li key={f.name}>
                  <button
                    onClick={() => f.present && onSelect(f.name)}
                    className={cn(
                      "w-full rounded-md px-3 py-2.5 text-left transition-colors",
                      f.present ? "hover:bg-accent" : "cursor-default opacity-80",
                      selected && "bg-accent ring-1 ring-foreground/20",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-medium">{FIELD_LABEL[f.name] ?? f.name}</span>
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                          {Math.round(f.confidence * 100)}%
                        </span>
                        <Badge variant="outline" className={cn("h-5 text-[10px]", tone.badge)}>
                          {f.status === "escalated" ? "Escalated" : f.present ? "Found" : "Not in document"}
                        </Badge>
                      </div>
                    </div>
                    {f.present ? (
                      <>
                        <div className="mt-1 text-[13px]">{fmtValue(f.value)}</div>
                        <blockquote className="mt-1.5 border-l-2 border-foreground/20 pl-2 font-serif text-[12.5px] italic leading-5 text-muted-foreground">
                          “{f.quote}”
                        </blockquote>
                      </>
                    ) : null}
                    {f.note ? <p className="mt-1.5 text-[12px] text-muted-foreground">{f.note}</p> : null}
                    {f.escalation_reason ? (
                      <p className="mt-1 text-[12px] text-red-700 dark:text-red-300">{f.escalation_reason}</p>
                    ) : null}
                  </button>
                  {selected && f.present ? (
                    <div className="px-3 pb-2">
                      <DecisionButtons value={decisions[`${doc.id}:${f.name}`] ?? null} onChange={(d) => onDecide(`${doc.id}:${f.name}`, d)} />
                    </div>
                  ) : null}
                  <Separator />
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    )
  }

  const findings = doc.findings!
  const counts = findings.reduce<Record<string, number>>((acc, f) => {
    acc[f.verdict] = (acc[f.verdict] ?? 0) + 1
    return acc
  }, {})
  const needHuman = findings.filter((f) => f.status === "escalated").length
  return (
    <div className="flex h-full flex-col">
      <div className="grid grid-cols-3 gap-px border-b bg-border">
        <Stat label="Citations" value={String(findings.length)} />
        <Stat label="Resolved" value={String(counts.RESOLVED ?? 0)} />
        <Stat label="Need a human" value={String(needHuman)} tone={needHuman ? "text-red-700 dark:text-red-300" : undefined} />
      </div>
      {escalation}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ul className="flex flex-col p-3">
          {findings.map((f, i) => {
            const key = `c${i}`
            const tone = VERDICT_TONE[f.verdict]
            const selected = selectedKey === key
            return (
              <li key={key}>
                <button
                  onClick={() => onSelect(key)}
                  className={cn(
                    "w-full rounded-md px-3 py-2.5 text-left transition-colors hover:bg-accent",
                    selected && "bg-accent ring-1 ring-foreground/20",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[13px]">{f.citation}</span>
                    <div className="flex items-center gap-1.5">
                      {f.page ? <span className="text-[11px] tabular-nums text-muted-foreground">p. {f.page}</span> : null}
                      <Badge variant="outline" className={cn("h-5 text-[10px]", tone.badge)}>
                        {tone.label}
                      </Badge>
                    </div>
                  </div>
                  {f.written_name ? (
                    <div className="mt-1 text-[13px]">
                      <span className="text-muted-foreground">As written: </span>
                      {f.written_name.replace(/^TABLE OF AUTHORITIES\s*Page\(?\)?\s*Cases\s*/i, "")}
                    </div>
                  ) : null}
                  {f.resolved_name ? (
                    <div className="text-[13px]">
                      <span className="text-muted-foreground">Database: </span>
                      {f.resolved_name}
                      {f.court ? <span className="text-muted-foreground"> · {f.court}{f.date_filed ? `, ${f.date_filed.slice(0, 4)}` : ""}</span> : null}
                    </div>
                  ) : null}
                  <p className="mt-1 text-[12px] text-muted-foreground">{f.explanation}</p>
                </button>
                {selected ? (
                  <div className="flex items-center justify-between px-3 pb-2">
                    <DecisionButtons value={decisions[`${doc.id}:${key}`] ?? null} onChange={(d) => onDecide(`${doc.id}:${key}`, d)} />
                    {f.url ? (
                      <a
                        href={`https://www.courtlistener.com${f.url}`}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-2 hover:underline"
                      >
                        Open in CourtListener <ExternalLink className="size-3" />
                      </a>
                    ) : null}
                  </div>
                ) : null}
                <Separator />
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="bg-background px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={cn("text-[15px] font-medium tabular-nums", tone)}>{value}</div>
    </div>
  )
}
