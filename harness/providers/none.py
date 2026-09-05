"""A provider that refuses. Used by no-LLM runners so an agent that declares
`document_may_leave: false` cannot accidentally call a model."""

from __future__ import annotations

from harness.providers.base import BaseProvider, ModelRequest, ModelResponse


class NoModelProvider(BaseProvider):
    def _call(self, req: ModelRequest) -> tuple[ModelResponse, bytes]:
        raise RuntimeError("this agent makes no model calls; a call was attempted")
