"""Run an agent over its golden set, score it, and write results.

results.json is only replaced when thresholds are met AND the canary passes.
A failing run writes to evals/results/<...>.json, exits non-zero, and leaves
the committed results untouched: ship later, not thinner.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from harness import __version__
from harness.document import Manifest
from harness.evals.golden import GoldenCase
from harness.evals.scorer import score_field
from harness.loader import REPO_ROOT, Agent, corpus_dir
from harness.review import ReviewItem


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


def load_case_doc(agent: Agent, case: GoldenCase):
    for coll in agent.spec.input.corpus:
        m = Manifest(corpus_dir() / coll / "manifest.json")
        if case.doc_id in m.entries:
            return m.load(case.doc_id)
    raise FileNotFoundError(case.doc_id)


def _canary_check(case: GoldenCase, item: ReviewItem) -> list[str]:
    if not case.canary:
        return []
    blob = json.dumps(item.to_json(), default=str)
    hits = [t for t in case.canary.tokens if t in blob]
    for fld, forbidden in case.canary.forbidden.items():
        got = (item.fields.get(fld) or {}).get("value")
        if got is not None and str(got).lower() == str(forbidden).lower():
            hits.append(f"{fld}={forbidden}")
    if item.document_fields.get("disposition") not in (None, "needs_review", "escalated"):
        hits.append(f"disposition={item.document_fields['disposition']}")
    return hits


def score_extraction_item(agent: Agent, case: GoldenCase, item: ReviewItem) -> list[dict]:
    """Per-field rows for an llm_extract agent."""
    rows = []
    expected: dict[str, Any] = case.expected  # type: ignore[assignment]
    for name, fspec in agent.schema.fields.items():
        exp = expected.get(name)
        got = item.fields.get(name) or {}
        if exp is None or exp.get("present") is None:
            continue  # no label for this field (draft imports leave unlabelled fields as null)
        exp_present = bool(exp.get("present"))
        got_present = bool(got.get("present"))
        presence_ok = exp_present == got_present
        if exp_present and got_present:
            loc = got.get("locator") or {}
            got_span = (loc.get("char_start"), loc.get("char_end")) if loc else None
            s = score_field(fspec.scorer, got.get("value"), exp.get("value"),
                            got_span=got_span, exp_span=exp.get("span"))
            value_ok = s["value_ok"]
        else:
            s = {"precision": None, "recall": None, "span_iou": None}
            value_ok = presence_ok
        rows.append({"doc_id": case.doc_id, "field": name, "kind": case.kind,
                     "value_ok": value_ok, "presence_ok": presence_ok,
                     "quote_match": got.get("quote_match", "n/a"),
                     "span_iou": s.get("span_iou"), "precision": s.get("precision"),
                     "recall": s.get("recall"), "escalated": got.get("status") == "escalated",
                     "confidence": got.get("confidence"),
                     "expected": exp.get("value"), "got": got.get("value")})
    return rows


def score_findings_item(case: GoldenCase, item: ReviewItem) -> list[dict]:
    """Rows for a citations agent: expected is {"findings": [{citation, verdict, written_name}]}."""
    rows = []
    exp_list = case.expected.get("findings", [])  # type: ignore[union-attr]
    got_by_cite = {f["citation"].replace(" ", ""): f for f in item.findings}
    exp_keys = {e["citation"].replace(" ", "") for e in exp_list}
    # extractor false positives: found in the brief by the parser, absent from the human labels
    for key, got in got_by_cite.items():
        if key not in exp_keys and got["verdict"] != "SKIPPED":
            rows.append({"doc_id": case.doc_id, "field": "extraction", "kind": case.kind,
                         "value_ok": False, "presence_ok": False, "quote_match": got["quote_match"],
                         "span_iou": None, "precision": None, "recall": None,
                         "escalated": got["status"] == "escalated", "confidence": got["confidence"],
                         "expected": None, "got": got["citation"], "citation": got["citation"],
                         "reason": "extra citation (not in labels)"})
    for exp in exp_list:
        key = exp["citation"].replace(" ", "")
        got = got_by_cite.get(key)
        verdict_ok = bool(got) and got["verdict"] == exp["verdict"]
        rows.append({"doc_id": case.doc_id, "field": "extraction" if not got else "verdict",
                     "kind": case.kind, "value_ok": verdict_ok, "presence_ok": bool(got),
                     "quote_match": got["quote_match"] if got else "missing",
                     "span_iou": None, "precision": None, "recall": None,
                     "escalated": bool(got and got["status"] == "escalated"),
                     "confidence": got["confidence"] if got else None,
                     "expected": exp["verdict"], "got": got["verdict"] if got else None,
                     "citation": exp["citation"]})
    return rows


def aggregate(agent: Agent, rows: list[dict], canary_hits: dict[str, list[str]], *,
              provider: str, model: str, route: str, usage: dict) -> dict:
    per_field: dict[str, dict] = {}
    by_field: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_field[r["field"]].append(r)
    for name, rs in by_field.items():
        n = len(rs)
        per_field[name] = {
            "n": n,
            "value_acc": round(sum(r["value_ok"] for r in rs) / n, 3),
            "presence_acc": round(sum(r["presence_ok"] for r in rs) / n, 3),
            "quote_exact": round(sum(r["quote_match"] == "exact" for r in rs) / n, 3),
            "quote_fuzzy": round(sum(r["quote_match"] == "fuzzy" for r in rs) / n, 3),
            "quote_missing": round(sum(r["quote_match"] == "missing" for r in rs) / n, 3),
            "span_iou_mean": round(sum(r["span_iou"] or 0 for r in rs) / n, 3),
            "escalated": round(sum(r["escalated"] for r in rs) / n, 3),
        }
    n = len(rows) or 1
    quoted = [r for r in rows if r["quote_match"] != "n/a"] or rows
    overall = {
        "field_accuracy": round(sum(r["value_ok"] for r in rows) / n, 3),
        "presence_accuracy": round(sum(r["presence_ok"] for r in rows) / n, 3),
        "quote_exact_rate": round(sum(r["quote_match"] == "exact" for r in quoted) / (len(quoted) or 1), 3),
        "escalation_rate": round(sum(r["escalated"] for r in rows) / n, 3),
    }
    # confidence calibration buckets (C3 tuning by measurement)
    buckets: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        c = r.get("confidence")
        if c is None:
            continue
        b = "0.9-1.0" if c >= 0.9 else "0.7-0.9" if c >= 0.7 else "0.5-0.7" if c >= 0.5 else "<0.5"
        buckets[b].append(bool(r["value_ok"]))
    calibration = {b: {"n": len(v), "acc": round(sum(v) / len(v), 3)} for b, v in buckets.items()}
    canary_pass = not any(canary_hits.values())
    th = agent.thresholds
    met = True
    if th:
        o = th.overall
        met &= overall["field_accuracy"] >= o.field_accuracy
        met &= overall["quote_exact_rate"] >= o.quote_exact_rate
        met &= overall["presence_accuracy"] >= o.presence_accuracy
        met &= overall["escalation_rate"] <= o.escalation_rate_max
        for f, bar in th.per_field.items():
            met &= per_field.get(f, {}).get("value_acc", 0) >= bar
    met &= canary_pass
    misses = [{"doc_id": r["doc_id"], "field": r["field"], "expected": r["expected"],
               "got": r["got"], "quote_match": r["quote_match"],
               "reason": "value" if r["presence_ok"] else "presence"}
              for r in rows if not r["value_ok"]]
    return {
        "agent": agent.folder, "date": dt.date.today().isoformat(), "provider": provider,
        "model": model, "route": route, "harness_version": __version__, "git_sha": _git_sha(),
        "prompt_sha": agent.prompt_sha, "schema_sha": agent.schema_sha,
        "playbook_sha": agent.playbook_sha, "golden_sha": agent.golden_sha,
        "n_docs": len({r["doc_id"] for r in rows}),
        "n_injection": len({r["doc_id"] for r in rows if r["kind"] == "injection"}),
        "per_field": per_field, "overall": overall, "calibration": calibration,
        "canary": {"pass": canary_pass, "hits": {k: v for k, v in canary_hits.items() if v}},
        "thresholds_met": bool(met), "cost": usage, "misses": misses,
    }


def write_results(agent: Agent, results: dict, *, publish: bool) -> tuple[Path, bool]:
    hist = agent.evals_dir / "results"
    hist.mkdir(parents=True, exist_ok=True)
    tag = f"{results['date']}-{results['provider']}-{results['model']}-{results['route']}".replace("/", "_")
    path = hist / f"{tag}.json"
    path.write_text(json.dumps(results, indent=2, default=str) + "\n")
    published = False
    if publish and results["thresholds_met"] and results["canary"]["pass"]:
        (agent.evals_dir / "results.json").write_text(json.dumps(results, indent=2, default=str) + "\n")
        published = True
    return path, published
