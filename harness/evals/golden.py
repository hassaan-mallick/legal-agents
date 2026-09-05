"""golden.jsonl — one line per document, labelled by a human, never by a model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExpectedField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    present: bool
    value: Any = None
    quote: str | None = None
    span: tuple[int, int] | None = None


class Canary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tokens: list[str] = Field(min_length=1)
    forbidden: dict[str, Any] = Field(default_factory=dict)


class GoldenCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_id: str
    kind: Literal["standard", "sparse", "injection"] = "standard"
    twin_of: str | None = None
    canary: Canary | None = None
    expected: dict[str, Any] | Literal["@twin"]
    labelled_by: str | None = None
    labelled_on: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _twin(self) -> GoldenCase:
        if self.expected == "@twin" and not self.twin_of:
            raise ValueError("expected '@twin' requires twin_of")
        if self.kind == "injection" and not self.canary:
            raise ValueError("injection cases need a canary")
        if self.kind != "injection" and not self.labelled_by:
            raise ValueError("golden cases must record labelled_by (a person)")
        return self


def load_golden(path: Path) -> list[GoldenCase]:
    cases = [GoldenCase.model_validate(json.loads(ln))
             for ln in path.read_text().splitlines() if ln.strip()]
    by_id = {c.doc_id: c for c in cases}
    for c in cases:
        if c.expected == "@twin":
            c.expected = dict(by_id[c.twin_of].expected)  # type: ignore[arg-type]
    return cases
