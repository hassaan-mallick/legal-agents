"""The adapter contract, and the single chokepoint every model call goes through.

`ModelRequest` has no `tools` field on purpose: extraction calls never get
tools, so a document cannot talk the model into taking an action (V11).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from harness.egress import EgressLog
from harness.routing import Endpoint, load_registry
from harness.usage import record as record_usage

Effort = Literal["low", "medium", "high"]
StopReason = Literal["end", "max_tokens", "refusal", "other"]


class ModelRequest(BaseModel):
    system: str
    user: str
    json_schema: dict
    max_tokens: int = 16_000
    effort: Effort | None = None
    label: str = ""

    def cache_key(self) -> str:
        blob = json.dumps({"s": self.system, "u": self.user, "j": self.json_schema},
                          sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()


class ModelResponse(BaseModel):
    text: str
    model: str
    provider: str
    stop_reason: StopReason
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    raw_id: str | None = None
    latency_ms: int = 0
    refusal_detail: str | None = None


class ModelRefused(RuntimeError):
    pass


class ModelTruncated(RuntimeError):
    pass


class Provider(Protocol):
    name: str
    model: str
    endpoint: Endpoint

    def complete(self, req: ModelRequest) -> ModelResponse: ...


class BaseProvider:
    """Shared logging around `_call`. Subclasses implement `_call` only."""

    name: str
    model: str
    endpoint: Endpoint

    def __init__(self, endpoint: Endpoint, model: str, *, egress: EgressLog | None = None,
                 usage_path: Path | None = None, cache_dir: Path | None = None):
        self.endpoint = endpoint
        self.name = endpoint.name
        self.model = model
        self.egress = egress or EgressLog(allow={endpoint.host})
        self.usage_path = usage_path
        self.cache_dir = cache_dir  # when set, responses are written for replay

    def _call(self, req: ModelRequest) -> tuple[ModelResponse, bytes]:  # pragma: no cover
        raise NotImplementedError

    def complete(self, req: ModelRequest) -> ModelResponse:
        t0 = dt.datetime.now()
        resp, body = self._call(req)
        resp.latency_ms = int((dt.datetime.now() - t0).total_seconds() * 1000)
        resp.provider = self.name
        self.egress.record_model_call(host=self.endpoint.host, path="/messages", model=resp.model,
                                      body=body, status=200, latency_ms=resp.latency_ms,
                                      note=req.label)
        if self.usage_path:
            record_usage(self.usage_path, stage=req.label or "call", provider=self.name,
                         model=resp.model, stop=resp.stop_reason, input_tokens=resp.input_tokens,
                         output_tokens=resp.output_tokens, cache_read=resp.cache_read_tokens,
                         cache_write=resp.cache_write_tokens, latency_ms=resp.latency_ms)
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{req.cache_key()}.json").write_text(
                json.dumps(resp.model_dump(), indent=2) + "\n")
        if resp.stop_reason == "refusal":
            raise ModelRefused(resp.refusal_detail or "model declined the request")
        if resp.stop_reason == "max_tokens":
            raise ModelTruncated("response hit max_tokens before finishing")
        return resp


def resolve_provider(provider: str | None, model: str | None, *, egress: EgressLog | None = None,
                     usage_path: Path | None = None, cache_dir: Path | None = None,
                     replay: bool = False) -> BaseProvider:
    """CLI flag > env > error. Never a file inside the repo."""
    provider = provider or os.environ.get("LA_PROVIDER")
    model = model or os.environ.get("LA_MODEL")
    if replay:
        from harness.providers.replay import ReplayProvider

        reg = load_registry()
        ep = reg.get(provider or "", Endpoint("replay", "replay", "replay", None, True, True,
                                               "2026-01-01", 0, "offline replay"))
        return ReplayProvider(ep, model or "replay", cache_dir=cache_dir, egress=egress)
    if not provider or not model:
        raise SystemExit("choose a model at runtime: --provider <registry name> --model <id> "
                         "(or LA_PROVIDER / LA_MODEL). Agents never name models.")
    reg = load_registry()
    if provider not in reg:
        raise SystemExit(f"unknown provider {provider!r}; registry has {sorted(reg)}")
    ep = reg[provider]
    kwargs = dict(egress=egress, usage_path=usage_path, cache_dir=cache_dir)
    if ep.adapter == "anthropic_native":
        from harness.providers.anthropic_native import AnthropicProvider

        return AnthropicProvider(ep, model, **kwargs)
    if ep.adapter == "openai_compat":
        from harness.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(ep, model, **kwargs)
    raise SystemExit(f"unknown adapter {ep.adapter!r} for {provider}")
