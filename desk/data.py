"""Load real run outputs and their source documents for the desk UI.

Reads the latest run folder of each agent under `runs/`, joins each item to
its document text from `corpus/`, and computes highlight spans by locating
each quote or citation in the raw text (whitespace- and quote-tolerant, the
same looseness the harness's quote locator applies before an exact match).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
CORPUS = ROOT / "corpus"

FIELD_LABEL = {
    "parties": "Parties",
    "effective_date": "Effective date",
    "term": "Term",
    "confidential_information_definition": "Confidential Information",
    "exclusions": "Exclusions",
    "permitted_disclosures": "Permitted disclosures",
    "return_or_destroy": "Return or destroy",
    "governing_law": "Governing law",
    "jurisdiction_forum": "Forum",
    "assignment": "Assignment",
    "survival": "Survival",
    "remedies": "Remedies",
}


@dataclass
class Span:
    start: int
    end: int
    key: str
    tone: str  # ok | warn | bad | dim


@dataclass
class Finding:
    key: str
    title: str          # field label or citation
    verdict: str        # Found / Not in document / Resolved / Name mismatch / ...
    tone: str
    confidence: float
    value: str
    quote: str
    detail: str
    page: int | None = None
    url: str | None = None


@dataclass
class Doc:
    doc_id: str
    agent: str
    status: str
    reasons: list[str]
    injection: bool
    text: str
    findings: list[Finding]
    spans: list[Span] = field(default_factory=list)
    headline: str = ""


@dataclass
class Run:
    agent: str
    run_id: str
    label: str
    model: str
    endpoint: str
    retention: str
    data_class: str
    docs: list[Doc]
    egress: list[dict]
    usage: dict
    run_dir: Path | None = None


def _pattern(needle: str) -> re.Pattern:
    parts = []
    for w in needle.strip().split():
        w = re.escape(w)
        w = w.replace('"', "[\"“”]").replace("'", "['‘’]")
        parts.append(w)
    return re.compile(r"\s+".join(parts))


def locate_spans(text: str, needles: list[tuple[str, str, str]]) -> list[Span]:
    """needles: (key, needle_text, tone). First unclaimed occurrence wins."""
    claimed: list[Span] = []
    for key, needle, tone in needles:
        if not needle:
            continue
        pat = _pattern(needle)
        pos = 0
        while pos < len(text):
            m = pat.search(text, pos)
            if not m:
                break
            s, e = m.start(), m.end()
            if not any(s < c.end and e > c.start for c in claimed):
                claimed.append(Span(s, e, key, tone))
                break
            pos = e
    claimed.sort(key=lambda c: c.start)
    return claimed


def _doc_text(doc_id: str, collections: list[str]) -> str:
    for coll in collections:
        man = CORPUS / coll / "manifest.json"
        if not man.exists():
            continue
        m = json.loads(man.read_text())
        entries = m.get("documents") or m.get("docs") or m
        if isinstance(entries, dict):
            entries = list(entries.values())
        for e in entries:
            if isinstance(e, dict) and e.get("doc_id") == doc_id:
                return (CORPUS / coll / e["file"]).read_text(errors="replace")
    return ""


def _latest(agent_dir: Path) -> Path | None:
    runs = sorted(p for p in agent_dir.iterdir() if p.is_dir())
    return runs[-1] if runs else None


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v)


def load_nda(run_dir: Path) -> Run:
    docs: list[Doc] = []
    for f in sorted(run_dir.glob("*.json")):
        if f.name == "run.json":
            continue
        d = json.loads(f.read_text())
        if not d.get("fields") or not d["doc_id"].startswith("nda"):
            continue  # a brief that got swept into the synthetic run; not an NDA
        text = _doc_text(d["doc_id"], ["synthetic", "contract-nli", "edgar-nda"])
        findings: list[Finding] = []
        needles: list[tuple[str, str, str]] = []
        for name, v in d["fields"].items():
            esc = v.get("status") == "escalated"
            present = bool(v.get("present"))
            tone = "bad" if esc else ("ok" if present else "dim")
            verdict = "Escalated" if esc else ("Found" if present else "Not in document")
            findings.append(Finding(
                key=name, title=FIELD_LABEL.get(name, name), verdict=verdict, tone=tone,
                confidence=float(v.get("confidence") or 0), value=_fmt(v.get("value")),
                quote=v.get("quote") or "", detail=v.get("note") or v.get("escalation_reason") or ""))
            if present and v.get("quote"):
                needles.append((name, v["quote"], tone))
        found = sum(1 for x in findings if x.verdict == "Found")
        docs.append(Doc(
            doc_id=d["doc_id"], agent="nda", status=d["status"], reasons=d.get("escalation_reasons", []),
            injection=bool(d.get("injection_suspected")), text=text, findings=findings,
            spans=locate_spans(text, needles),
            headline=f"{found}/12 terms · {d.get('document_fields', {}).get('document_type', '').replace('_', ' ')}"))
    run = json.loads((run_dir / "run.json").read_text())
    usage = [json.loads(line) for line in (run_dir / "usage.jsonl").read_text().splitlines() if line.strip()] \
        if (run_dir / "usage.jsonl").exists() else []
    nda_usage = [u for u in usage if "nda" in u.get("stage", "")]
    egress = [json.loads(line) for line in (run_dir / "egress.jsonl").read_text().splitlines() if line.strip()] \
        if (run_dir / "egress.jsonl").exists() else []
    cost = sum(u["input"] * 2e-6 + u["output"] * 10e-6 + u["cacheRead"] * 0.2e-6 + u["cacheWrite"] * 2.5e-6
               for u in nda_usage)
    return Run(
        agent="nda", run_id=run["run_id"], label="001 · NDA REVIEW", model=run.get("model", "?"),
        endpoint=run.get("endpoint", "").split(" (")[0] or "api.anthropic.com",
        retention="30d · ZDR unverified", data_class=run.get("data_class", "public"), docs=docs, egress=egress,
        usage={"calls": len(nda_usage), "in": sum(u["input"] + u["cacheRead"] + u["cacheWrite"] for u in nda_usage),
               "out": sum(u["output"] for u in nda_usage), "usd": cost}, run_dir=run_dir)


VERDICT_TONE = {"RESOLVED": "ok", "NAME_MISMATCH": "bad", "UNRESOLVED": "warn", "NOT_CHECKED": "dim", "SKIPPED": "dim"}
VERDICT_LABEL = {"RESOLVED": "Resolved", "NAME_MISMATCH": "Name mismatch", "UNRESOLVED": "Unresolved",
                 "NOT_CHECKED": "Not checked", "SKIPPED": "Skipped"}


def load_cite(run_dir: Path, only: list[str] | None = None) -> Run:
    docs: list[Doc] = []
    for f in sorted(run_dir.glob("*.json")):
        if f.name == "run.json":
            continue
        d = json.loads(f.read_text())
        if only and d["doc_id"] not in only:
            continue
        text = _doc_text(d["doc_id"], ["recap-briefs", "synthetic"])
        findings: list[Finding] = []
        needles: list[tuple[str, str, str]] = []
        for i, x in enumerate(d.get("findings") or []):
            key = f"c{i}"
            tone = VERDICT_TONE.get(x["verdict"], "dim")
            name = (x.get("written_name") or "").strip()
            name = re.sub(r"^TABLE OF AUTHORITIES\s*Page\(?\)?\s*Cases\s*", "", name, flags=re.I)
            loc = x.get("locator") or {}
            findings.append(Finding(
                key=key, title=x["citation"], verdict=VERDICT_LABEL.get(x["verdict"], x["verdict"]), tone=tone,
                confidence=float(x.get("confidence") or 0), value=name,
                quote=x.get("resolved_name") or "", detail=x.get("explanation") or "",
                page=loc.get("page"), url=x.get("url")))
            if x["verdict"] != "SKIPPED":
                needles.append((key, x["citation"], tone))
        n_h = sum(1 for x in findings if x.tone in ("bad", "warn", "dim") and x.verdict != "Skipped")
        docs.append(Doc(
            doc_id=d["doc_id"], agent="cite", status=d["status"], reasons=d.get("escalation_reasons", []),
            injection=bool(d.get("injection_suspected")), text=text, findings=findings,
            spans=locate_spans(text, needles), headline=f"{len(findings)} citations · {n_h} need a human"))
    run = json.loads((run_dir / "run.json").read_text())
    egress = [json.loads(line) for line in (run_dir / "egress.jsonl").read_text().splitlines() if line.strip()] \
        if (run_dir / "egress.jsonl").exists() else []
    return Run(
        agent="cite", run_id=run["run_id"], label="002 · CITATION VERIFIER", model="none · eyecite + CourtListener",
        endpoint="courtlistener.com", retention="only {vol, reporter, page} sent", data_class=run.get("data_class", "public"),
        docs=docs, egress=egress, usage={"calls": len(egress), "in": 0, "out": 0, "usd": 0.0}, run_dir=run_dir)


def load_runs() -> list[Run]:
    out: list[Run] = []
    nda = _latest(RUNS / "001-nda-review")
    if nda:
        out.append(load_nda(nda))
    cite = _latest(RUNS / "002-citation-verifier")
    if cite:
        out.append(load_cite(cite, only=["recap-209920417", "recap-377506294-fake5", "recap-436884607", "recap-377506294"]))
    return out
