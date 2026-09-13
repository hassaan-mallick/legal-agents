import type { Verdict } from "@/types"

/** Semantic colour per verdict. Separate from the accent; these mean something. */
export const VERDICT_TONE: Record<Verdict, { badge: string; mark: string; label: string }> = {
  RESOLVED: {
    badge: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200 border-emerald-300/60",
    mark: "bg-emerald-200/60 dark:bg-emerald-900/50",
    label: "Resolved",
  },
  NAME_MISMATCH: {
    badge: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200 border-red-300/60",
    mark: "bg-red-200/70 dark:bg-red-900/60",
    label: "Name mismatch",
  },
  UNRESOLVED: {
    badge: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200 border-amber-300/60",
    mark: "bg-amber-200/70 dark:bg-amber-900/60",
    label: "Unresolved",
  },
  NOT_CHECKED: {
    badge: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border-slate-300/60",
    mark: "bg-slate-200/60 dark:bg-slate-700/50",
    label: "Not checked",
  },
  SKIPPED: {
    badge: "bg-slate-50 text-slate-500 dark:bg-slate-900 dark:text-slate-400 border-slate-200/60",
    mark: "",
    label: "Skipped",
  },
}

export const FIELD_TONE = {
  present: {
    badge: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200 border-emerald-300/60",
    mark: "bg-emerald-200/60 dark:bg-emerald-900/50",
  },
  absent: {
    badge: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border-slate-300/60",
    mark: "",
  },
  escalated: {
    badge: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200 border-red-300/60",
    mark: "bg-red-200/70 dark:bg-red-900/60",
  },
}

export const FIELD_LABEL: Record<string, string> = {
  parties: "Parties",
  effective_date: "Effective date",
  term: "Term",
  confidential_information_definition: "Confidential Information",
  exclusions: "Exclusions",
  permitted_disclosures: "Permitted disclosures",
  return_or_destroy: "Return or destroy",
  governing_law: "Governing law",
  jurisdiction_forum: "Forum",
  assignment: "Assignment",
  survival: "Survival",
  remedies: "Remedies",
}
