"""usage.jsonl — tokens and cost per model call. Port of record() in the
mallick.tech engine's llm.mjs. Dollars only when pricing.yaml knows the model."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import yaml

PRICING_PATH = Path(__file__).with_name("pricing.yaml")


def load_pricing() -> dict:
    if PRICING_PATH.exists():
        return yaml.safe_load(PRICING_PATH.read_text()) or {}
    return {}


def usd_estimate(provider: str, model: str, input_tokens: int, output_tokens: int,
                 cache_read: int = 0, cache_write: int = 0) -> float | None:
    pricing = load_pricing().get(provider, {}).get(model)
    if not pricing:
        return None
    per = 1_000_000
    cost = (input_tokens - cache_read) / per * pricing.get("input", 0)
    cost += output_tokens / per * pricing.get("output", 0)
    cost += cache_read / per * pricing.get("cache_read", pricing.get("input", 0) * 0.1)
    cost += cache_write / per * pricing.get("cache_write", pricing.get("input", 0) * 1.25)
    return round(cost, 6)


def record(path: Path, *, stage: str, provider: str, model: str, stop: str, input_tokens: int,
           output_tokens: int, cache_read: int = 0, cache_write: int = 0, latency_ms: int = 0,
           **extra) -> dict:
    row = {"at": dt.datetime.now(dt.UTC).isoformat(), "stage": stage, "provider": provider,
           "model": model, "stop": stop, "input": input_tokens, "output": output_tokens,
           "cacheRead": cache_read, "cacheWrite": cache_write, "latencyMs": latency_ms,
           "usd": usd_estimate(provider, model, input_tokens, output_tokens, cache_read, cache_write),
           **extra}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    return row
