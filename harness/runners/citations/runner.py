"""Citation runner: document → findings → ReviewItem. Zero model calls."""

from __future__ import annotations

from pathlib import Path

from harness.document import Document
from harness.gate import c5_scan
from harness.loader import Agent
from harness.quote import locate
from harness.review import ReviewItem, RunWriter
from harness.runners.citations.classify import Finding, Verdict, classify
from harness.runners.citations.extract import extract
from harness.runners.citations.resolve import HOST, Resolver


def make_resolver(agent: Agent, *, cache_dir: Path | None, offline: bool,
                  egress=None) -> Resolver:
    assert not agent.spec.egress.document_may_leave
    assert HOST in agent.spec.egress.allow, "agent.yaml egress.allow must include courtlistener"
    return Resolver(egress=egress, cache_dir=cache_dir, offline=offline)


def run_document(agent: Agent, doc: Document, resolver: Resolver, *,
                 writer: RunWriter | None) -> tuple[ReviewItem, list[Finding]]:
    spec = agent.spec
    _, cites = extract(doc.text)
    findings: list[Finding] = []
    for cite in cites:
        if cite.parallel_to is not None:
            from harness.runners.citations.resolve import Resolution

            findings.append(Finding(cite, Resolution(found=False), Verdict.SKIPPED,
                                    explanation="Parallel citation of the preceding case."))
            continue
        findings.append(classify(cite, resolver.resolve(cite.volume, cite.reporter, cite.page)))

    # C1: the citation text as written is the quote; locate it in the source.
    out = []
    escalated = 0
    for f in findings:
        qr = locate(doc, f.citation.text)
        status = "escalated" if f.needs_review else ("skipped" if f.verdict is Verdict.SKIPPED else "extracted")
        if f.needs_review:
            escalated += 1
        threshold = spec.gates.confidence.default
        if status == "extracted" and f.confidence < threshold:
            status, escalated = "escalated", escalated + 1
        out.append({"citation": f.citation.text, "written_name": f.citation.written_name,
                    "verdict": f.verdict.value, "confidence": round(f.confidence, 2),
                    "status": status, "explanation": f.explanation,
                    "resolved_name": f.resolution.case_name, "court": f.resolution.court,
                    "date_filed": f.resolution.date_filed, "url": f.resolution.absolute_url,
                    "quote_match": qr.match, "locator": qr.locator.to_json() if qr.locator else None})

    # The verifier egress log must never contain document text.
    sample = doc.text[:200]
    leaked = resolver.egress.contains(sample[:60]) if len(sample) >= 60 else False
    reasons = []
    if escalated:
        reasons.append(f"{escalated} citation(s) need a human: unresolved, name mismatch, or not checked")
    if leaked:
        reasons.append("DOCUMENT TEXT FOUND IN EGRESS LOG — stop and investigate")
    if not findings:
        reasons.append("no full case citations found; confirm this is expected")
    c5 = c5_scan(spec, out)
    if c5:
        reasons.append(f"forbidden disposition tokens in output: {c5}")
    doc_status = "escalated" if reasons else "pending_review"
    item = ReviewItem(agent=agent.folder, doc_id=doc.doc_id, status=doc_status,
                      reviewer_role=spec.human_gate.role, reviewer=RunWriter.reviewer(),
                      gate_point=spec.human_gate.point, fields={},
                      absences_to_confirm=[], escalation_reasons=reasons, findings=out,
                      document_fields={"disposition": "escalated" if doc_status == "escalated" else "needs_review"})
    if writer:
        writer.write_item(item)
    return item, findings
