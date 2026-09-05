"""The generic extraction runner: stages load → pre_model → prompt → call →
parse_validate → verify_quotes → gate → playbook → c5_scan → emit.

Every control is a stage. There is no path from here to a `final` status.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from harness.document import Document
from harness.gate import c5_scan, gate_document, gate_field
from harness.loader import GUARD_PREAMBLE, Agent
from harness.providers.base import BaseProvider, ModelRefused, ModelRequest, ModelTruncated
from harness.quote import locate
from harness.redact import RedactionMap, redact, reidentify
from harness.review import ReviewItem, RunWriter
from harness.routing import Route, check_route, stage_retention
from harness.schema_build import build_output_model, json_schema_for

INJECTION_PATTERNS = Path(__file__).resolve().parent.parent / "injection_patterns.txt"


def _injection_regexes() -> list[re.Pattern]:
    out = []
    for line in INJECTION_PATTERNS.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(re.compile(line, re.IGNORECASE))
    return out


_INJECTION = _injection_regexes()


def injection_suspected(text: str) -> list[str]:
    return [p.pattern for p in _INJECTION if p.search(text)]


def render_document_block(doc: Document, text: str | None = None) -> str:
    body = (text if text is not None else doc.text).replace("</document>", "<\\/document>")
    return f'<document id="{doc.doc_id}" sha256="{doc.sha256}">\n{body}\n</document>'


def build_request(agent: Agent, doc: Document, output_model: type[BaseModel], *,
                  text_override: str | None = None, effort: str | None = None,
                  repair_error: str | None = None) -> ModelRequest:
    system = GUARD_PREAMBLE.read_text() + "\n\n" + (agent.system_prompt or "")
    if agent.playbook:
        system += "\n\n## Playbook (for context only; deviations are computed by code)\n"
        system += json.dumps(agent.playbook, indent=2)
    user = (agent.extract_prompt or "{{document}}").replace(
        "{{document}}", render_document_block(doc, text_override))
    if repair_error:
        user += ("\n\nYour previous answer did not match the schema. Error:\n"
                 f"{repair_error}\nReturn only a corrected JSON object.")
    return ModelRequest(system=system, user=user, json_schema=json_schema_for(output_model),
                        effort=effort, label=f"{agent.folder}:{doc.doc_id}")


@dataclass
class DocResult:
    doc_id: str
    item: ReviewItem
    parsed: dict | None
    error: str | None = None
    quote_results: dict[str, dict] = field(default_factory=dict)


def _parse(text: str, model: type[BaseModel]) -> BaseModel:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    return model.model_validate(json.loads(cleaned))


def evaluate_playbook(playbook: dict | None, fields: dict[str, Any]) -> list[dict]:
    """Deterministic rules over extracted values. Each deviation carries the
    rule text and the quote so a lawyer can see what it compared against."""
    if not playbook:
        return []
    deviations = []
    for rule in playbook.get("rules", []):
        fld = fields.get(rule["field"])
        if not fld or fld.get("status") != "extracted":
            continue
        value = fld.get("value")
        op, expected = rule["operator"], rule.get("value")
        hit = False
        match op:
            case "not_in":
                hit = value not in expected
            case "in":
                hit = value in expected
            case "eq":
                hit = value == expected
            case "ne":
                hit = value != expected
            case "contains":
                hit = isinstance(value, list) and expected in value
            case "not_contains":
                hit = not (isinstance(value, list) and expected in value)
        if hit:
            deviations.append({"rule_id": rule["id"], "rule": rule["text"], "field": rule["field"],
                               "severity": rule.get("severity", "medium"), "value": value,
                               "quote": fld.get("quote"), "locator": fld.get("locator")})
    return deviations


def run_document(agent: Agent, doc: Document, provider: BaseProvider, *, route: Route,
                 effort: str | None, writer: RunWriter | None) -> DocResult:
    spec = agent.spec
    professional = spec.obligation.professional
    output_model = build_output_model(agent.schema, professional=professional)

    # --- pre_model: routing (C6), redaction on split, injection heuristic
    check_route(route, provider.endpoint, spec.data_class, stage_retention(spec, "extract"))
    injection_hits = injection_suspected(doc.text)
    rmap: RedactionMap | None = None
    text_for_model: str | None = None
    if route == "split":
        text_for_model, rmap = redact(doc.text)
        if writer:
            rmap.save(writer.dir / f"{doc.doc_id}.redaction-map.json")

    # --- call + parse_validate with one repair round
    parsed: BaseModel | None = None
    hard_reason: str | None = None
    raw_text = ""
    try:
        req = build_request(agent, doc, output_model, text_override=text_for_model, effort=effort)
        resp = provider.complete(req)
        raw_text = resp.text
        try:
            parsed = _parse(raw_text, output_model)
        except (ValidationError, json.JSONDecodeError) as exc:
            req2 = build_request(agent, doc, output_model, text_override=text_for_model,
                                 effort=effort, repair_error=str(exc)[:2000])
            resp2 = provider.complete(req2)
            raw_text = resp2.text
            try:
                parsed = _parse(raw_text, output_model)
            except (ValidationError, json.JSONDecodeError) as exc2:
                hard_reason = f"model_output_invalid: {str(exc2)[:300]}"
    except ModelRefused as exc:
        hard_reason = f"model_refused: {exc}"
    except ModelTruncated as exc:
        hard_reason = f"model_truncated: {exc}"

    # --- verify_quotes (C1) + gate (C3)
    fields: dict[str, Any] = {}
    quote_results: dict[str, dict] = {}
    absences: list[str] = []
    escalated = quote_missing = 0
    if parsed is not None:
        data = parsed.model_dump(mode="json")
        for name in agent.schema.fields:
            ext = data[name]
            quote = ext.get("quote")
            if rmap and quote:
                quote = reidentify(quote, rmap)
            qr = locate(doc, quote) if ext["present"] else None
            match = qr.match if qr else "n/a"
            status, reason = gate_field(spec, name, ext["present"], ext["confidence"], match)
            if status == "escalated":
                escalated += 1
                if match == "missing":
                    quote_missing += 1
            if status == "not_present":
                absences.append(name)
            value = ext.get("value")
            if rmap and isinstance(value, str):
                value = reidentify(value, rmap)
            elif rmap and isinstance(value, list):
                value = [reidentify(v, rmap) if isinstance(v, str) else v for v in value]
            fields[name] = {"present": ext["present"], "value": value, "quote": quote,
                            "confidence": ext["confidence"] if status != "escalated" or match != "missing" else 0.0,
                            "note": ext.get("note"), "status": status, "escalation_reason": reason,
                            "quote_match": match,
                            "locator": qr.locator.to_json() if qr and qr.locator else None}
            quote_results[name] = qr.to_json() if qr else {"match": "n/a"}
        document_fields = {k: data[k] for k in agent.schema.document_fields}
        if professional:
            document_fields["disposition"] = "needs_review"
    else:
        document_fields = {}

    doc_escalated, reasons = gate_document(spec, escalated_fields=escalated,
                                           quote_missing_fields=quote_missing,
                                           injection_suspected=bool(injection_hits),
                                           hard_reason=hard_reason)
    deviations = evaluate_playbook(agent.playbook, fields)

    # --- c5_scan
    c5_hits = c5_scan(spec, {"fields": fields, "document_fields": document_fields})
    if c5_hits:
        doc_escalated = True
        reasons.append(f"forbidden disposition tokens in output: {c5_hits}")
        if professional:
            document_fields["disposition"] = "escalated"
    if professional and doc_escalated:
        document_fields["disposition"] = "escalated"

    item = ReviewItem(agent=agent.folder, doc_id=doc.doc_id,
                      status="escalated" if doc_escalated else "pending_review",
                      reviewer_role=spec.human_gate.role, reviewer=RunWriter.reviewer(),
                      gate_point=spec.human_gate.point, fields=fields,
                      absences_to_confirm=absences, escalation_reasons=reasons,
                      deviations=deviations, document_fields=document_fields,
                      injection_suspected=bool(injection_hits))
    if writer:
        writer.write_item(item)
    return DocResult(doc_id=doc.doc_id, item=item, parsed=fields if parsed else None,
                     error=hard_reason, quote_results=quote_results)
