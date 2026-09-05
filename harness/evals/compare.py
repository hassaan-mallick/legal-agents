"""evals/results/*.json → evals/comparison.md, rows = provider/model/route."""

from __future__ import annotations

import json
from pathlib import Path


def build_comparison(evals_dir: Path) -> str:
    rows = []
    for p in sorted((evals_dir / "results").glob("*.json")):
        r = json.loads(p.read_text())
        o = r["overall"]
        cost = r.get("cost") or {}
        rows.append((r["date"], r["provider"], r["model"], r.get("route", "-"),
                     o["field_accuracy"], o["quote_exact_rate"], o["escalation_rate"],
                     "pass" if r["canary"]["pass"] else "FAIL",
                     cost.get("tokens_per_doc"), cost.get("usd_per_doc"),
                     "yes" if r["thresholds_met"] else "no"))
    lines = ["# Model / route comparison", "",
             "Same golden set, same prompts, same harness. Only the endpoint and route change.", "",
             "| date | provider | model | route | field acc | quote exact | escalation | canary "
             "| tok/doc | $/doc | thresholds |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| " + " | ".join("—" if v is None else str(v) for v in r) + " |")
    if not rows:
        lines.append("| — | no runs yet | | | | | | | | | |")
    text = "\n".join(lines) + "\n"
    (evals_dir / "comparison.md").write_text(text)
    return text


def regressions(current: dict, baseline: dict, *, points: float = 0.02) -> list[str]:
    out = []
    for f, cur in current.get("per_field", {}).items():
        base = baseline.get("per_field", {}).get(f)
        if base and cur["value_acc"] + points < base["value_acc"]:
            out.append(f"{f}: {base['value_acc']:.3f} → {cur['value_acc']:.3f}")
    return out
