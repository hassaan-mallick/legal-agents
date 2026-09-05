"""Pydantic models for agent.yaml, schema.yaml and evals/thresholds.yaml.

Everything `la validate` checks structurally lives here as a validator, so an
agent that loads is already most of the way to compliant. Rules that need the
filesystem (golden set, results, corpus manifests) live in validate/rules.py.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness import MODEL_SENTINEL

SERIES_REFS = {f"F{i}" for i in range(1, 11)} | {f"R{i}" for i in range(1, 41)}
MANDATORY_CONTROLS = {"C1", "C2", "C3", "C4", "C6"}
CONTROL_ID = re.compile(r"^C\d+$")

Workflow = Literal[
    "extract", "review", "research_verify", "triage", "draft", "intake", "monitor"
]
Runner = Literal["llm_extract", "citations"]
DataClass = Literal["public", "synthetic", "confidential", "privileged"]
Retention = Literal["any", "zdr", "local"]
ObligationDomain = Literal["conflicts", "privilege", "sanctions", "filing"]

#: Words a professional-obligation agent may never emit or declare (C5).
FORBIDDEN_DISPOSITIONS = (
    "cleared",
    "no_conflict",
    "not_privileged",
    "safe_to_file",
    "compliant",
    "approved",
    "final",
    "verified_ok",
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Obligation(Strict):
    professional: bool = False
    domain: ObligationDomain | None = None

    @model_validator(mode="after")
    def _domain_requires_professional(self) -> Obligation:
        if self.domain and not self.professional:
            raise ValueError("obligation.domain set but obligation.professional is false")
        return self


class HumanGate(Strict):
    role: str = Field(min_length=3)
    point: str = Field(min_length=10)
    why: str = Field(min_length=10)


class ConfidenceGate(Strict):
    default: float = Field(gt=0, le=1)
    per_field: dict[str, float] = Field(default_factory=dict)

    @field_validator("per_field")
    @classmethod
    def _range(cls, v: dict[str, float]) -> dict[str, float]:
        for k, x in v.items():
            if not 0 < x <= 1:
                raise ValueError(f"per_field.{k} must be in (0, 1]")
        return v


class DocumentEscalation(Strict):
    escalated_fields_gte: int = Field(default=4, ge=1)
    injection_suspected: bool = True
    quote_missing_fields_gte: int = Field(default=1, ge=1)


class Gates(Strict):
    confidence: ConfidenceGate
    escalate_document_if: DocumentEscalation = Field(default_factory=DocumentEscalation)


class InputSpec(Strict):
    formats: list[Literal["txt", "md"]] = Field(default_factory=lambda: ["txt", "md"])
    max_chars: int = Field(default=200_000, ge=1_000)
    corpus: list[str] = Field(min_length=1)


class EgressSpec(Strict):
    allow: list[str] = Field(default_factory=list)
    document_may_leave: bool = True

    @field_validator("allow")
    @classmethod
    def _bare_hosts(cls, v: list[str]) -> list[str]:
        for host in v:
            if "/" in host or "://" in host or host != host.strip().lower():
                raise ValueError(f"egress.allow entries must be bare lowercase hostnames: {host!r}")
        return v


class Stage(Strict):
    name: str
    retention: Retention = "any"


class EvalSpec(Strict):
    min_docs: int = Field(default=20, ge=20)
    min_injection_docs: int = Field(default=2, ge=2)


class AgentSpec(Strict):
    id: str = Field(pattern=r"^\d{3}$")
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    title: str = Field(min_length=3)
    series_ref: str
    workflow: Workflow
    runner: Runner
    tier: Literal[0, 1, 2]
    enterprise_gap: str = Field(min_length=40)
    obligation: Obligation = Field(default_factory=Obligation)
    controls: list[str]
    human_gate: HumanGate
    gates: Gates
    input: InputSpec
    egress: EgressSpec = Field(default_factory=EgressSpec)
    data_class: DataClass
    stages: list[Stage] = Field(default_factory=list)
    model: str
    eval: EvalSpec = Field(default_factory=EvalSpec)
    cost_note: str = "measured, see evals/results.json"

    @property
    def folder_name(self) -> str:
        return f"{self.id}-{self.slug}"

    @field_validator("series_ref")
    @classmethod
    def _series(cls, v: str) -> str:
        if v not in SERIES_REFS:
            raise ValueError(f"series_ref must be F1-F10 or R1-R40, got {v!r}")
        return v

    @field_validator("model")
    @classmethod
    def _sentinel(cls, v: str) -> str:
        if v != MODEL_SENTINEL:
            raise ValueError(
                f"model must be the literal {MODEL_SENTINEL!r}; models are chosen at runtime"
            )
        return v

    @field_validator("controls")
    @classmethod
    def _controls(cls, v: list[str]) -> list[str]:
        bad = [c for c in v if not CONTROL_ID.match(c)]
        if bad:
            raise ValueError(f"controls must look like C1, C2 ...: {bad}")
        missing = MANDATORY_CONTROLS - set(v)
        if missing:
            raise ValueError(f"controls missing mandatory entries: {sorted(missing)}")
        return v

    @model_validator(mode="after")
    def _cross(self) -> AgentSpec:
        if self.obligation.professional and "C5" not in self.controls:
            raise ValueError("professional-obligation agents must list C5 (flag, never clear)")
        if self.runner != "llm_extract" and self.egress.document_may_leave:
            raise ValueError(
                f"runner {self.runner!r} makes no model call; set egress.document_may_leave: false"
            )
        if self.data_class in ("confidential", "privileged"):
            zdr_ok = any(s.retention in ("zdr", "local") for s in self.stages)
            if not zdr_ok and self.egress.document_may_leave:
                raise ValueError(
                    "confidential/privileged agents need a stage with retention zdr|local "
                    "(or egress.document_may_leave: false)"
                )
        return self


# --------------------------------------------------------------------------- schema.yaml

FieldType = Literal["str", "text", "date", "enum", "list[str]", "list[enum]", "int", "bool"]
Scorer = Literal[
    "exact", "enum", "enum_set", "date", "party_names", "jurisdiction", "span", "int", "bool"
]


class FieldSpec(Strict):
    type: FieldType
    required: bool = False
    enum: list[str] | None = None
    scorer: Scorer = "exact"
    description: str | None = None

    @model_validator(mode="after")
    def _enum(self) -> FieldSpec:
        if self.type in ("enum", "list[enum]") and not self.enum:
            raise ValueError("enum fields must declare `enum: [...]`")
        if self.enum and self.type not in ("enum", "list[enum]"):
            raise ValueError("`enum` only allowed on enum / list[enum] fields")
        if self.enum:
            for value in self.enum:
                if value.lower() in FORBIDDEN_DISPOSITIONS:
                    raise ValueError(f"enum value {value!r} is a forbidden disposition (C5)")
        return self


class DocumentFieldSpec(Strict):
    type: Literal["enum", "str", "bool"]
    enum: list[str] | None = None
    description: str | None = None


class SchemaSpec(Strict):
    fields: dict[str, FieldSpec] = Field(min_length=1)
    document_fields: dict[str, DocumentFieldSpec] = Field(default_factory=dict)

    @field_validator("fields", "document_fields")
    @classmethod
    def _names(cls, v: dict) -> dict:
        for name in v:
            if not re.match(r"^[a-z][a-z0-9_]*$", name):
                raise ValueError(f"field name {name!r} must be snake_case")
        return v


# --------------------------------------------------------------------------- thresholds.yaml


class OverallThresholds(Strict):
    field_accuracy: float = Field(ge=0, le=1)
    quote_exact_rate: float = Field(ge=0, le=1)
    presence_accuracy: float = Field(ge=0, le=1)
    escalation_rate_max: float = Field(ge=0, le=1)
    canary_pass: float = Field(default=1.0, ge=1.0, le=1.0)


class Thresholds(Strict):
    overall: OverallThresholds
    per_field: dict[str, float] = Field(default_factory=dict)
