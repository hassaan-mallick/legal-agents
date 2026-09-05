"""Egress allowlist and log — the only place network requests are allowed.

Ported from the citation-verifier's EgressLog and made repo-wide. Every module
that needs the network goes through `guarded_client()`; a test asserts nothing
else imports httpx/requests. Model calls record a body hash (the body contains
the document by necessity); non-model calls record the payload verbatim.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx


class EgressDenied(RuntimeError):
    pass


@dataclass
class EgressRecord:
    at: str
    method: str
    host: str
    path: str
    payload: dict | None = None
    body_sha256: str | None = None
    body_bytes: int = 0
    contains_document: bool = False
    status: int | None = None
    latency_ms: int | None = None
    note: str = ""
    model: str | None = None

    def to_json(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "", 0, False)} | {
            "at": self.at, "method": self.method, "host": self.host, "path": self.path}


@dataclass
class EgressLog:
    allow: set[str] = field(default_factory=set)
    records: list[EgressRecord] = field(default_factory=list)

    def check(self, url: str) -> str:
        host = urlparse(url).hostname or ""
        if host not in self.allow:
            raise EgressDenied(f"egress to {host!r} is not allowlisted (allowed: {sorted(self.allow)})")
        return host

    def record_model_call(self, *, host: str, path: str, model: str, body: bytes,
                          status: int | None, latency_ms: int, note: str = "") -> EgressRecord:
        rec = EgressRecord(at=_now(), method="POST", host=host, path=path, model=model,
                           body_sha256=hashlib.sha256(body).hexdigest(), body_bytes=len(body),
                           contains_document=True, status=status, latency_ms=latency_ms, note=note)
        self.records.append(rec)
        return rec

    def start(self, method: str, url: str, payload: dict | None, note: str = "") -> EgressRecord:
        host = self.check(url)
        rec = EgressRecord(at=_now(), method=method, host=host, path=urlparse(url).path,
                           payload=payload, note=note)
        self.records.append(rec)
        return rec

    def contains(self, needle: str) -> bool:
        """Assert-helper: did any verbatim payload contain `needle`?"""
        blob = json.dumps([r.payload for r in self.records if r.payload]).lower()
        return needle.lower() in blob

    def write(self, path: Path) -> None:
        with path.open("a") as fh:
            for r in self.records:
                fh.write(json.dumps(r.to_json()) + "\n")

    def as_text(self) -> str:
        if not self.records:
            return "(nothing sent)"
        out = []
        for i, r in enumerate(self.records, 1):
            what = json.dumps(r.payload) if r.payload else f"body sha256={r.body_sha256} ({r.body_bytes} bytes)"
            out.append(f"{i}. {r.method} {r.host}{r.path}\n   {what}\n   status: {r.status}"
                       + (f"  ({r.note})" if r.note else ""))
        return "\n".join(out)


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


class GuardedClient:
    """httpx wrapper that refuses non-allowlisted hosts and logs every call."""

    def __init__(self, log: EgressLog, *, user_agent: str, timeout: float = 30.0):
        self.log = log
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": user_agent})

    def request(self, method: str, url: str, *, payload: dict | None = None, note: str = "",
                **kwargs) -> tuple[httpx.Response | None, EgressRecord]:
        rec = self.log.start(method, url, payload, note)
        t0 = dt.datetime.now()
        try:
            resp = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            rec.note = f"network error: {exc.__class__.__name__}"
            return None, rec
        rec.status = resp.status_code
        rec.latency_ms = int((dt.datetime.now() - t0).total_seconds() * 1000)
        return resp, rec

    def close(self) -> None:
        self._client.close()


def guarded_client(allow: set[str], user_agent: str) -> GuardedClient:
    return GuardedClient(EgressLog(allow=set(allow)), user_agent=user_agent)
