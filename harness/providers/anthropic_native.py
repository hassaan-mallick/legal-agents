"""Anthropic Messages API via the official SDK.

Structured output through `output_config.format` (json_schema), a cached
system block, and refusal handling. No tools are ever passed. The model id
comes from the run, never from an agent file.

The constrained decoder has schema limits (compiled-grammar size, at most 16
nullable/union parameters). A twelve-field envelope schema exceeds them, so
when the API rejects the schema the call is retried unconstrained with the
schema written into the user turn; the harness still validates the JSON
against the pydantic model and runs its repair pass, so the guarantee moves
from the decoder to the validator rather than disappearing.
"""

from __future__ import annotations

import json

import anthropic

from harness.providers.base import BaseProvider, ModelRequest, ModelResponse

_SCHEMA_SUFFIX = ("\n\nReturn exactly one JSON object, no prose, no code fence, conforming to this "
                  "JSON Schema (every property is required; use null where the schema allows it):\n```json\n")


class AnthropicProvider(BaseProvider):
    _unconstrained = False  # set once the API has rejected this run's schema

    def _client(self):
        import anthropic

        return anthropic.Anthropic()

    def _call(self, req: ModelRequest) -> tuple[ModelResponse, bytes]:
        params: dict = {
            "model": self.model,
            "max_tokens": req.max_tokens,
            "system": [{"type": "text", "text": req.system,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": req.user}],
            "output_config": {"format": {"type": "json_schema", "schema": req.json_schema}},
        }
        if req.effort:
            params["output_config"]["effort"] = req.effort
        body = json.dumps(params, sort_keys=True).encode()

        client = self._client()
        try:
            if self._unconstrained:
                raise anthropic.BadRequestError.__new__(anthropic.BadRequestError)
            message = client.messages.create(**params)
        except anthropic.BadRequestError as exc:  # schema too large for the grammar → unconstrained JSON
            msg = str(exc) if not self._unconstrained else "schema"
            if not any(k in msg for k in ("grammar", "output_config", "union types", "schema")):
                raise
            self._unconstrained = True  # sticky: the schema will not shrink between documents
            params["output_config"].pop("format")
            if not params["output_config"]:
                params.pop("output_config")
            params["messages"] = [{"role": "user", "content": req.user + _SCHEMA_SUFFIX
                                   + json.dumps(req.json_schema, sort_keys=True) + "\n```"}]
            body = json.dumps(params, sort_keys=True).encode()
            message = client.messages.create(**params)

        stop = {"end_turn": "end", "max_tokens": "max_tokens", "refusal": "refusal"}.get(
            message.stop_reason or "", "other")
        detail = None
        if stop == "refusal" and getattr(message, "stop_details", None):
            sd = message.stop_details
            detail = f"{getattr(sd, 'category', None)}: {getattr(sd, 'explanation', '')}"
        text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
        u = message.usage
        resp = ModelResponse(
            text=text, model=message.model, provider=self.name, stop_reason=stop,
            input_tokens=u.input_tokens, output_tokens=u.output_tokens,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            raw_id=getattr(message, "id", None), refusal_detail=detail)
        return resp, body
