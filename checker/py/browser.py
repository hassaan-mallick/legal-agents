"""Glue between the page and the harness. Runs inside Pyodide.

extract.py and classify.py are the files the CLI runs, unchanged. The page does
the CourtListener lookup itself (only {volume, reporter, page} leaves) and hands
each answer back here to be classified, so a verdict in the browser is the
verdict `la run` would give for the same lookup answer.
"""

from __future__ import annotations

import os

os.environ.setdefault("RAPIDFUZZ_IMPLEMENTATION", "python")

import json  # noqa: E402

from harness.runners.citations.classify import Verdict, classify, uncheckable  # noqa: E402
from harness.runners.citations.extract import extract  # noqa: E402
from harness.runners.citations.resolution import Resolution  # noqa: E402

#: agents/002-citation-verifier/agent.yaml gates.confidence.default, copied in by bundle.py
CONFIDENCE_THRESHOLD = float(os.environ.get("CHECKER_CONFIDENCE_THRESHOLD", "0.6"))

_cites: list = []


def extract_json(text: str) -> str:
    _, cites = extract(text)
    _cites[:] = cites
    out = []
    for i, c in enumerate(cites):
        out.append({"index": i, "text": c.text, "volume": c.volume, "reporter": c.reporter,
                    "page": c.page, "key": c.key, "written_name": c.written_name,
                    "parallel_to": c.parallel_to, "uncheckable": uncheckable(c)})
    return json.dumps(out)


def _finding_json(f) -> dict:
    status = "escalated" if f.needs_review else ("skipped" if f.verdict is Verdict.SKIPPED else "extracted")
    if status == "extracted" and f.confidence < CONFIDENCE_THRESHOLD:
        status = "escalated"
    return {"verdict": f.verdict.value, "confidence": round(f.confidence, 2), "status": status,
            "similarity": f.similarity, "explanation": f.explanation, "needs_review": f.needs_review}


def classify_json(index: int, resolution_json: str) -> str:
    """The same branches as runner.run_document: parallel → SKIPPED, proprietary
    reporter → NOT_CHECKED without a lookup, otherwise classify the answer."""
    from harness.runners.citations.classify import Finding

    cite = _cites[index]
    if cite.parallel_to is not None:
        f = Finding(cite, Resolution(found=False), Verdict.SKIPPED,
                    explanation="Parallel citation of the preceding case.")
    elif uncheckable(cite):
        f = classify(cite, Resolution(found=False))
    else:
        f = classify(cite, Resolution(**json.loads(resolution_json)))
    return json.dumps(_finding_json(f))
