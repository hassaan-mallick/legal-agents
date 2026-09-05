"""schema.yaml -> pydantic model + JSON schema.

Agent authors declare fields. The harness wraps every one in an `Extraction`
envelope so a verbatim quote (C1) and a confidence (C3) are structural: the
model cannot return a value without them, and validate cannot be talked out of
requiring them.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from harness.spec import FORBIDDEN_DISPOSITIONS, SchemaSpec


class Extraction(BaseModel):
    """What the model returns for one field. Post-verification fields are added by
    the harness in `verified.py`, never requested from the model."""

    model_config = ConfigDict(extra="forbid")

    present: bool
    value: Any = None
    quote: str | None = None
    confidence: float = Field(ge=0, le=1)
    note: str | None = None

    @model_validator(mode="after")
    def _quote_when_present(self) -> Extraction:
        if self.present and not (self.quote and self.quote.strip()):
            raise ValueError("present=true requires a verbatim quote")
        return self


def _value_type(spec) -> Any:
    match spec.type:
        case "str" | "text":
            return str | None
        case "date":
            return dt.date | str | None
        case "int":
            return int | None
        case "bool":
            return bool | None
        case "enum":
            return Literal[tuple(spec.enum)] | None  # type: ignore[valid-type]
        case "list[str]":
            return list[str] | None
        case "list[enum]":
            return list[Literal[tuple(spec.enum)]] | None  # type: ignore[valid-type]
    raise ValueError(spec.type)


def build_output_model(schema: SchemaSpec, *, professional: bool) -> type[BaseModel]:
    """Compile schema.yaml into the model the provider must satisfy."""
    fields: dict[str, Any] = {}
    for name, spec in schema.fields.items():
        typed = create_model(
            f"Extraction_{name}",
            __base__=Extraction,
            value=(_value_type(spec), None),
        )
        fields[name] = (typed, ...)
    for name, spec in schema.document_fields.items():
        if spec.type == "enum":
            fields[name] = (Literal[tuple(spec.enum)], ...)  # type: ignore[valid-type]
        elif spec.type == "bool":
            fields[name] = (bool, ...)
        else:
            fields[name] = (str, ...)
    if professional:
        # C5: the only document-level dispositions a professional-obligation
        # agent can emit. Fixed by the harness, not declarable by the agent.
        fields["disposition"] = (Literal["needs_review", "escalated"], ...)
    return create_model("Output", __config__=ConfigDict(extra="forbid"), **fields)


def _strictify(node: Any) -> Any:
    """Make a JSON schema acceptable to strict structured-output modes:
    additionalProperties false, every property required, no defaults."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        node.pop("default", None)
        node.pop("title", None)
        for key in ("properties", "$defs"):
            if key in node:
                for sub in node[key].values():
                    _strictify(sub)
        for key in ("items", "anyOf", "allOf", "oneOf"):
            if key in node:
                val = node[key]
                if isinstance(val, list):
                    for sub in val:
                        _strictify(sub)
                else:
                    _strictify(val)
    return node


def json_schema_for(model: type[BaseModel]) -> dict:
    return _strictify(model.model_json_schema())


def forbidden_tokens_in(text: str) -> list[str]:
    """Word-boundary, case-insensitive scan for C5 forbidden dispositions."""
    import re

    hits = []
    for tok in FORBIDDEN_DISPOSITIONS:
        if re.search(rf"\b{re.escape(tok)}\b", text, flags=re.IGNORECASE):
            hits.append(tok)
    return hits
