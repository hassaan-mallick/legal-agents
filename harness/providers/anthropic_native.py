"""Anthropic Messages API via the official SDK.

Structured output through `output_config.format` (json_schema), a cached
system block, and refusal handling. No tools are ever passed. The model id
comes from the run, never from an agent file.
"""

from __future__ import annotations

import json

from harness.providers.base import BaseProvider, ModelRequest, ModelResponse


class AnthropicProvider(BaseProvider):
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

        message = self._client().messages.create(**params)

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
