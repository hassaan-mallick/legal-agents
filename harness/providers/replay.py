"""Replay provider — serves recorded responses from evals/cache so CI can run
every eval with no keys and no network. A miss is loud: it means someone
changed a prompt or schema without re-recording."""

from __future__ import annotations

import json
from pathlib import Path

from harness.providers.base import BaseProvider, ModelRequest, ModelResponse


class ReplayMiss(RuntimeError):
    pass


class ReplayProvider(BaseProvider):
    def _call(self, req: ModelRequest) -> tuple[ModelResponse, bytes]:
        if not self.cache_dir:
            raise ReplayMiss("replay requested but no cache_dir given")
        path = Path(self.cache_dir) / f"{req.cache_key()}.json"
        if not path.exists():
            raise ReplayMiss(f"no cached response for {req.label or 'request'} "
                             f"(key {req.cache_key()[:12]}…). Run `la eval --record` first.")
        data = json.loads(path.read_text())
        resp = ModelResponse(**data)
        return resp, b""

    def complete(self, req: ModelRequest) -> ModelResponse:  # no logging, no re-caching
        resp, _ = self._call(req)
        for k in self.usage_totals:  # what the recorded run spent, so replay results carry it
            self.usage_totals[k] += getattr(resp, k, 0) or 0
        return resp
