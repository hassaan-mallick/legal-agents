import { useEffect, useMemo, useState } from "react"
import raw from "@/data/demo-runs.json"
import type { Decision, DemoData, Doc } from "@/types"
import { DocList } from "@/components/DocList"
import { DocumentPane } from "@/components/DocumentPane"
import { FindingsPane } from "@/components/FindingsPane"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Scale } from "lucide-react"

const data = raw as unknown as DemoData
const STORAGE = "legal-agents-demo-decisions"

function loadDecisions(): Record<string, Decision> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE) ?? "{}")
  } catch {
    return {}
  }
}

export default function App() {
  const [agent, setAgent] = useState<"nda" | "cite">("nda")
  const docs = useMemo(() => data.docs.filter((d) => d.agent === agent), [agent])
  const [docId, setDocId] = useState<string>(docs[0].id)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [decisions, setDecisions] = useState<Record<string, Decision>>(loadDecisions)

  useEffect(() => {
    setDocId(docs[0].id)
    setSelectedKey(null)
  }, [docs])

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE, JSON.stringify(decisions))
    } catch {
      /* per-viewer convenience only */
    }
  }, [decisions])

  const doc: Doc = docs.find((d) => d.id === docId) ?? docs[0]
  const run = data.runs[agent]

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex h-12 shrink-0 items-center gap-4 border-b px-4">
        <div className="flex items-center gap-2">
          <Scale className="size-4" />
          <span className="text-sm font-semibold tracking-tight">Legal Agents</span>
          <span className="text-sm text-muted-foreground">review queue</span>
        </div>
        <Tabs value={agent} onValueChange={(v) => setAgent(v as "nda" | "cite")}>
          <TabsList>
            <TabsTrigger value="nda">001 · NDA review</TabsTrigger>
            <TabsTrigger value="cite">002 · Citation verifier</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <Tooltip>
            <TooltipTrigger render={<Badge variant="outline" className="font-mono text-[11px]" />}>
              {run.model}
            </TooltipTrigger>
            <TooltipContent>Chosen at run time. No agent file names a model.</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger render={<Badge variant="outline" className="text-[11px]" />}>
              {run.endpoint} · {run.retention}
            </TooltipTrigger>
            <TooltipContent>
              Data class for this run: {run.data_class}. Confidential text is refused unless the endpoint is
              verified zero-retention.
            </TooltipContent>
          </Tooltip>
          {run.usd != null ? (
            <Badge variant="outline" className="tabular-nums text-[11px]">
              ${run.usd.toFixed(2)} for {run.calls} calls
            </Badge>
          ) : (
            <Badge variant="outline" className="text-[11px]">no model call</Badge>
          )}
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[240px_minmax(0,1fr)_440px]">
        <aside className="min-h-0 border-r">
          <div className="border-b px-3 py-2 text-[10px] uppercase tracking-wider text-muted-foreground">
            Documents · run {run.run_id}
          </div>
          <div className="h-[calc(100%-33px)]">
            <DocList docs={docs} selectedId={doc.id} onSelect={(id) => { setDocId(id); setSelectedKey(null) }} />
          </div>
        </aside>
        <main className="min-h-0 bg-muted/30">
          <DocumentPane key={doc.id} doc={doc} selectedKey={selectedKey} onSelect={setSelectedKey} />
        </main>
        <aside className="min-h-0 border-l">
          <FindingsPane
            key={doc.id}
            doc={doc}
            selectedKey={selectedKey}
            onSelect={setSelectedKey}
            decisions={decisions}
            onDecide={(k, d) => setDecisions((prev) => ({ ...prev, [k]: d }))}
          />
        </aside>
      </div>

      <footer className="flex h-8 shrink-0 items-center gap-3 border-t px-4 text-[11px] text-muted-foreground">
        <span>No item on this page is final. A named human decides each one.</span>
        <span className="ml-auto">Public and synthetic documents only · {data.docs.length} shown from two runs on 8 Sep 2026</span>
      </footer>
    </div>
  )
}
