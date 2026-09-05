"""C2 — the review queue. Nothing produced by the harness is ever `final`.

Every document becomes a ReviewItem with status pending_review or escalated,
a named reviewer role, and an empty decision. Approval happens outside the run
(appended to decisions.jsonl by a human), never by rewriting the item.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ReviewStatus = Literal["pending_review", "escalated"]


@dataclass
class ReviewItem:
    agent: str
    doc_id: str
    status: ReviewStatus
    reviewer_role: str
    reviewer: str | None
    gate_point: str
    fields: dict[str, Any]
    absences_to_confirm: list[str]
    escalation_reasons: list[str]
    deviations: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    document_fields: dict[str, Any] = field(default_factory=dict)
    injection_suspected: bool = False
    decision: None = None
    created_at: str = field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())

    def to_json(self) -> dict:
        return self.__dict__.copy()


class RunWriter:
    """Writes one run's artefacts under runs/<agent>/<run_id>/."""

    def __init__(self, runs_root: Path, agent_folder: str, run_id: str | None = None):
        self.run_id = run_id or dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        self.dir = runs_root / agent_folder / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.items: list[ReviewItem] = []

    @staticmethod
    def reviewer() -> str | None:
        return os.environ.get("LA_REVIEWER") or None

    def write_item(self, item: ReviewItem) -> Path:
        self.items.append(item)
        path = self.dir / f"{item.doc_id}.json"
        path.write_text(json.dumps(item.to_json(), indent=2, default=str) + "\n")
        return path

    def write_run(self, meta: dict) -> Path:
        meta = {**meta, "run_id": self.run_id, "n_items": len(self.items),
                "n_escalated": sum(i.status == "escalated" for i in self.items)}
        (self.dir / "run.json").write_text(json.dumps(meta, indent=2, default=str) + "\n")
        self._write_queue()
        return self.dir / "run.json"

    def _write_queue(self) -> None:
        lines = [f"# Review queue — {self.run_id}", "",
                 "| doc | status | escalation reasons | reviewer |", "|---|---|---|---|"]
        for it in self.items:
            lines.append(f"| {it.doc_id} | {it.status} | {'; '.join(it.escalation_reasons) or '—'} "
                         f"| {it.reviewer or it.reviewer_role} |")
        lines += ["", "No item in this queue is final. A named human decides each one."]
        (self.dir / "review-queue.md").write_text("\n".join(lines) + "\n")
