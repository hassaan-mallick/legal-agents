"""The hand-labelling workbench: builds without a model, and merge refuses drafts and unlocatable quotes."""

from __future__ import annotations

import json
from pathlib import Path

from harness.evals.workbench import build, merge
from harness.loader import load_agent

GOOD_QUOTE = "two (2) years from the Effective Date"


def _row(quote: str | None, who: str, present: bool = True) -> str:
    cell = {"present": present, "value": "two (2) years" if present else None,
            "quote": quote if present else None, "span": None}
    return json.dumps({"doc_id": "fx-001", "kind": "standard", "expected": {"example_field": cell},
                       "labelled_by": who, "labelled_on": "2026-09-20", "notes": "document_type=type_a"})


def test_build_embeds_documents_and_candidates(compliant_agent: Path, tmp_path: Path):
    agent = load_agent(compliant_agent)
    out = build(agent, tmp_path / "label.html")
    page = out.read_text()
    assert "fx-001" in page and "example_field" in page
    assert "Use selected text as quote" in page
    # no provider or model name is baked into the page
    assert "anthropic" not in page.lower() and "openai" not in page.lower()


def test_merge_refuses_draft_labels(compliant_agent: Path, tmp_path: Path):
    agent = load_agent(compliant_agent)
    before = (compliant_agent / "evals" / "golden.jsonl").read_text()
    labels = tmp_path / "labels.jsonl"
    labels.write_text(_row(GOOD_QUOTE, "draft: from a run") + "\n")
    r = merge(agent, labels)
    assert r["merged"] == 0 and any("labelled_by" in e for e in r["errors"])
    assert (compliant_agent / "evals" / "golden.jsonl").read_text() == before


def test_merge_refuses_quote_not_in_source(compliant_agent: Path, tmp_path: Path):
    agent = load_agent(compliant_agent)
    labels = tmp_path / "labels.jsonl"
    labels.write_text(_row("roughly a couple of years or so", "Hassaan Mallick") + "\n")
    r = merge(agent, labels)
    assert r["merged"] == 0 and any("not found in source" in e for e in r["errors"])


def test_merge_writes_span_and_signature(compliant_agent: Path, tmp_path: Path):
    agent = load_agent(compliant_agent)
    labels = tmp_path / "labels.jsonl"
    labels.write_text(_row(GOOD_QUOTE, "Hassaan Mallick") + "\n")
    r = merge(agent, labels)
    assert r["errors"] == [] and r["replaced"] == 1
    rows = {json.loads(ln)["doc_id"]: json.loads(ln)
            for ln in (compliant_agent / "evals" / "golden.jsonl").read_text().splitlines() if ln.strip()}
    cell = rows["fx-001"]["expected"]["example_field"]
    assert cell["span"] == [182, 219] and rows["fx-001"]["labelled_by"] == "Hassaan Mallick"
    assert rows["fx-001"]["notes"].startswith("document_type=")
    # the other documents are untouched
    assert rows["fx-002"]["expected"]["example_field"]["span"] == [182, 219]


def test_merge_absent_field_clears_value(compliant_agent: Path, tmp_path: Path):
    agent = load_agent(compliant_agent)
    labels = tmp_path / "labels.jsonl"
    labels.write_text(_row(None, "Hassaan Mallick", present=False) + "\n")
    r = merge(agent, labels)
    assert r["errors"] == []
    row = next(json.loads(ln) for ln in (compliant_agent / "evals" / "golden.jsonl").read_text().splitlines()
               if ln.strip() and json.loads(ln)["doc_id"] == "fx-001")
    assert row["expected"]["example_field"] == {"present": False, "value": None, "quote": None, "span": None}
