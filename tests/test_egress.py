"""The only modules allowed to touch the network are egress.py and providers/*."""

import re
from pathlib import Path

import pytest

from harness.egress import EgressDenied, EgressLog, guarded_client

HARNESS = Path(__file__).resolve().parent.parent / "harness"
NETWORK_IMPORT = re.compile(r"^\s*(?:import|from)\s+(httpx|requests|anthropic|openai|urllib\.request|aiohttp)\b", re.M)


def test_no_network_imports_outside_chokepoints():
    offenders = []
    for p in HARNESS.rglob("*.py"):
        rel = p.relative_to(HARNESS).as_posix()
        if rel == "egress.py" or rel.startswith("providers/"):
            continue
        if NETWORK_IMPORT.search(p.read_text()):
            offenders.append(rel)
    assert offenders == []


def test_denied_host_never_requested():
    client = guarded_client({"www.courtlistener.com"}, user_agent="test")
    with pytest.raises(EgressDenied):
        client.request("GET", "https://evil.example.com/x", payload={})
    assert client.log.records == []


def test_log_contains_only_payloads():
    log = EgressLog(allow={"a.example"})
    log.start("GET", "https://a.example/search", {"q": 'citation:"477 U.S. 242"'})
    assert log.contains("477 U.S. 242")
    assert not log.contains("the whole brief")
    log.record_model_call(host="m.example", path="/messages", model="x", body=b"secret doc text",
                          status=200, latency_ms=1)
    assert not log.contains("secret doc text")  # model bodies are hashed, not stored
