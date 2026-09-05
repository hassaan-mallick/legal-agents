import pytest
import yaml
from pydantic import ValidationError

from harness.gate import c5_scan, gate_document, gate_field
from harness.routing import Endpoint, RoutingRefused, check_route, endpoint_allows
from harness.schema_build import build_output_model, forbidden_tokens_in, json_schema_for
from harness.spec import AgentSpec, SchemaSpec
from tests.conftest import FIXTURES


def _spec(**overrides) -> AgentSpec:
    raw = yaml.safe_load((FIXTURES / "900-compliant" / "agent.yaml").read_text())
    raw.update(overrides)
    return AgentSpec.model_validate(raw)


def test_gate_field_thresholds():
    spec = _spec()
    assert gate_field(spec, "example_field", True, 0.95, "exact") == ("extracted", None)
    status, reason = gate_field(spec, "example_field", True, 0.5, "exact")
    assert status == "escalated" and "threshold" in reason
    assert gate_field(spec, "example_field", True, 1.0, "missing") == ("escalated", "quote_not_in_source")
    assert gate_field(spec, "example_field", False, 0.0, "n/a") == ("not_present", None)


def test_gate_document_reasons():
    spec = _spec()
    esc, reasons = gate_document(spec, escalated_fields=0, quote_missing_fields=0, injection_suspected=True)
    assert esc and any("injection" in r for r in reasons)
    esc, reasons = gate_document(spec, escalated_fields=0, quote_missing_fields=0, injection_suspected=False)
    assert not esc


def test_c5_professional_disposition_fixed():
    schema = SchemaSpec.model_validate({"fields": {"x": {"type": "str"}}})
    model = build_output_model(schema, professional=True)
    js = json_schema_for(model)
    assert js["properties"]["disposition"]["enum"] == ["needs_review", "escalated"]
    assert js["additionalProperties"] is False


def test_c5_forbidden_enum_rejected():
    with pytest.raises(ValidationError):
        SchemaSpec.model_validate({"fields": {"x": {"type": "enum", "enum": ["cleared", "flag"]}}})


def test_c5_scan_only_for_professional():
    prof = _spec(obligation={"professional": True, "domain": "filing"}, controls=["C1", "C2", "C3", "C4", "C5", "C6"])
    assert c5_scan(prof, {"status": "cleared"}) == ["cleared"]
    assert c5_scan(_spec(), {"status": "cleared"}) == []
    assert forbidden_tokens_in("This is not a final answer") == ["final"]


def test_extraction_requires_quote_when_present():
    schema = SchemaSpec.model_validate({"fields": {"x": {"type": "str"}}})
    model = build_output_model(schema, professional=False)
    with pytest.raises(ValidationError):
        model.model_validate({"x": {"present": True, "value": "v", "quote": None, "confidence": 0.9}})
    ok = model.model_validate({"x": {"present": False, "value": None, "quote": None, "confidence": 0.9}})
    assert ok.x.present is False


ZDR = Endpoint("local", "openai_compat", "localhost", "ollama", True, True, "2026-01-01", 0, "")
UNVERIFIED = Endpoint("cloud", "anthropic_native", "api.example.com", None, "unverified", False, None, 30, "")


def test_c6_confidential_refused_on_unverified():
    ok, why = endpoint_allows(UNVERIFIED, "confidential")
    assert not ok and "C6" in why
    assert endpoint_allows(UNVERIFIED, "public")[0]
    assert endpoint_allows(ZDR, "privileged")[0]


def test_c6_route_checks():
    with pytest.raises(RoutingRefused):
        check_route("zdr", UNVERIFIED, "public")
    with pytest.raises(RoutingRefused):
        check_route("local", UNVERIFIED, "public")
    with pytest.raises(RoutingRefused):
        check_route("best-quality", UNVERIFIED, "confidential")
    check_route("best-quality", UNVERIFIED, "public")
    check_route("split", UNVERIFIED, "confidential")  # model only sees redacted text
    with pytest.raises(RoutingRefused):
        check_route("best-quality", UNVERIFIED, "public", stage_retention="local")
