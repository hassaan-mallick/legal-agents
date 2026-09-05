"""C3 (confidence gate) and C5 (flag, never clear) as code.

Escalation is the safe failure. Nothing here can lower an escalation once set.
"""

from __future__ import annotations

from typing import Any

from harness.schema_build import forbidden_tokens_in
from harness.spec import AgentSpec

Status = str  # extracted | escalated | not_present


def gate_field(spec: AgentSpec, name: str, present: bool, confidence: float,
               quote_match: str) -> tuple[Status, str | None]:
    """Decide a field's status. Returns (status, escalation_reason)."""
    if not present:
        return "not_present", None
    if quote_match == "missing":
        return "escalated", "quote_not_in_source"
    threshold = spec.gates.confidence.per_field.get(name, spec.gates.confidence.default)
    if confidence < threshold:
        return "escalated", f"confidence {confidence:.2f} < threshold {threshold:.2f}"
    return "extracted", None


def gate_document(spec: AgentSpec, *, escalated_fields: int, quote_missing_fields: int,
                  injection_suspected: bool, hard_reason: str | None = None) -> tuple[bool, list[str]]:
    rules = spec.gates.escalate_document_if
    reasons: list[str] = []
    if hard_reason:
        reasons.append(hard_reason)
    if escalated_fields >= rules.escalated_fields_gte:
        reasons.append(f"{escalated_fields} fields escalated (>= {rules.escalated_fields_gte})")
    if quote_missing_fields >= rules.quote_missing_fields_gte:
        reasons.append(f"{quote_missing_fields} quotes not found in source")
    if injection_suspected and rules.injection_suspected:
        reasons.append("possible prompt injection in document text")
    return (bool(reasons), reasons)


def c5_scan(spec: AgentSpec, payload: Any) -> list[str]:
    """Belt-and-braces scan of serialised output for forbidden dispositions."""
    if not spec.obligation.professional:
        return []
    import json

    return forbidden_tokens_in(json.dumps(payload, default=str))
