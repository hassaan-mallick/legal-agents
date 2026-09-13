import type { Doc } from "@/types"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { AlertTriangle } from "lucide-react"

export function DocList({
  docs,
  selectedId,
  onSelect,
}: {
  docs: Doc[]
  selectedId: string
  onSelect: (id: string) => void
}) {
  return (
    <div className="h-full overflow-y-auto">
      <ul className="flex flex-col gap-1 p-2">
        {docs.map((d) => {
          const n = d.agent === "nda" ? d.fields!.filter((f) => f.present).length : d.findings!.length
          const flagged =
            d.agent === "nda"
              ? d.fields!.filter((f) => f.status === "escalated").length
              : d.findings!.filter((f) => f.status === "escalated").length
          return (
            <li key={d.id}>
              <button
                onClick={() => onSelect(d.id)}
                className={cn(
                  "w-full rounded-md border px-3 py-2 text-left transition-colors",
                  "hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  selectedId === d.id ? "border-foreground/30 bg-accent" : "border-transparent",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-[13px]">{d.id}</span>
                  {d.status === "escalated" ? (
                    <AlertTriangle className="size-3.5 shrink-0 text-red-600 dark:text-red-400" />
                  ) : null}
                </div>
                <div className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span>{d.agent === "nda" ? `${n} of 12 terms found` : `${n} citations`}</span>
                  {flagged > 0 ? (
                    <Badge variant="outline" className="h-4 px-1.5 text-[10px] text-red-700 dark:text-red-300">
                      {flagged} to review
                    </Badge>
                  ) : null}
                </div>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
