"""OpenAI-compatible chat completions via the official `openai` SDK.

One class, four presets: openai, azure, ollama, openrouter. Strict json_schema
response format by default, falling back to json_object when a server rejects
it; pydantic validates either way, so the mode only changes the retry rate.
"""

from __future__ import annotations

import json
import os

from harness.providers.base import BaseProvider, ModelRequest, ModelResponse

PRESETS = {
    "openai": {"base_url": None, "key_env": "OPENAI_API_KEY"},
    "azure": {"base_url": None, "key_env": "AZURE_OPENAI_API_KEY"},
    "ollama": {"base_url": "http://localhost:11434/v1", "key_env": None},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY"},
}


class OpenAICompatProvider(BaseProvider):
    def _client(self):
        import openai

        preset = self.endpoint.preset or "openai"
        cfg = PRESETS[preset]
        if preset == "azure":
            return openai.AzureOpenAI(
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
                api_key=os.environ["AZURE_OPENAI_API_KEY"])
        key = os.environ.get(cfg["key_env"]) if cfg["key_env"] else "ollama"
        base = os.environ.get("LA_BASE_URL") or cfg["base_url"]
        return openai.OpenAI(api_key=key or "missing", base_url=base)

    def _call(self, req: ModelRequest) -> tuple[ModelResponse, bytes]:
        client = self._client()
        messages = [{"role": "system", "content": req.system},
                    {"role": "user", "content": req.user}]
        strict_format = {"type": "json_schema",
                         "json_schema": {"name": "output", "strict": True, "schema": req.json_schema}}
        params = {"model": self.model, "messages": messages, "max_tokens": req.max_tokens,
                  "response_format": strict_format}
        if req.effort and self.endpoint.preset in ("openai", "azure", "openrouter"):
            params["reasoning_effort"] = req.effort
        body = json.dumps(params, sort_keys=True).encode()
        try:
            completion = client.chat.completions.create(**params)
        except Exception as exc:  # server rejects strict schema → json_object
            if "response_format" not in str(exc) and "json_schema" not in str(exc):
                raise
            params["response_format"] = {"type": "json_object"}
            completion = client.chat.completions.create(**params)
        choice = completion.choices[0]
        stop = {"stop": "end", "length": "max_tokens", "content_filter": "refusal"}.get(
            choice.finish_reason or "", "other")
        u = completion.usage
        cached = 0
        if u and getattr(u, "prompt_tokens_details", None):
            cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
        resp = ModelResponse(
            text=choice.message.content or "", model=completion.model or self.model,
            provider=self.name, stop_reason=stop,
            input_tokens=u.prompt_tokens if u else 0, output_tokens=u.completion_tokens if u else 0,
            cache_read_tokens=cached, raw_id=completion.id,
            refusal_detail=getattr(choice.message, "refusal", None))
        return resp, body
