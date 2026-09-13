export type Verdict = "RESOLVED" | "NAME_MISMATCH" | "UNRESOLVED" | "NOT_CHECKED" | "SKIPPED"

export interface NdaField {
  name: string
  present: boolean
  value: unknown
  quote: string | null
  confidence: number
  note: string | null
  status: string
  escalation_reason: string | null
  quote_match: string | null
}

export interface CiteFinding {
  citation: string
  written_name: string | null
  verdict: Verdict
  confidence: number
  status: string
  explanation: string
  resolved_name: string | null
  court: string | null
  date_filed: string | null
  url: string | null
  quote_match: string | null
  page: number | null
  heading: string | null
}

export interface Doc {
  id: string
  agent: "nda" | "cite"
  title: string
  status: "pending_review" | "escalated"
  reasons: string[]
  injection: boolean
  text: string
  doc_type?: string
  absences?: string[]
  fields?: NdaField[]
  findings?: CiteFinding[]
}

export interface RunMeta {
  run_id: string
  provider: string
  model: string
  endpoint: string
  retention: string
  data_class: string
  calls?: number
  input_tokens?: number
  output_tokens?: number
  usd?: number
  n_items?: number
}

export interface DemoData {
  docs: Doc[]
  runs: { nda: RunMeta; cite: RunMeta }
}

export type Decision = "accepted" | "sent_back" | null
