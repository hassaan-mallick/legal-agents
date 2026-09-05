"""Citation resolution against CourtListener (Free Law Project).

THE ONE RULE: the document text never appears in an outbound request. Only
{volume, reporter, page} leaves, through the guarded client, and every payload
is in the egress log verbatim.

`found=False` and `unavailable=True` are DIFFERENT ANSWERS. The first means
CourtListener looked and has no such case. The second means the lookup did not
complete. Reporting an outage as not-found tells a lawyer a real case is
suspect, which is the single worst thing this tool could do.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from harness.egress import EgressLog, GuardedClient

HOST = "www.courtlistener.com"
SEARCH_URL = f"https://{HOST}/api/rest/v4/search/"
LOOKUP_URL = f"https://{HOST}/api/rest/v4/citation-lookup/"
MIN_SECONDS_BETWEEN_CALLS = 1.2
ANON_SECONDS_BETWEEN_CALLS = 5.0
MAX_RETRIES = 4
USER_AGENT = "legal-agents/0.1 citation verifier (https://github.com/hassaan-mallick/legal-agents)"


@dataclass
class Resolution:
    found: bool
    unavailable: bool = False
    case_name: str | None = None
    case_name_full: str | None = None
    court: str | None = None
    date_filed: str | None = None
    precedential_status: str | None = None
    absolute_url: str | None = None
    cluster_id: int | None = None
    all_citations: list[str] = field(default_factory=list)
    error: str | None = None

    def to_json(self) -> dict:
        return self.__dict__.copy()


def _normalise_cite(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class Resolver:
    """Resolves citations with an on-disk cache so evals and CI never touch the API."""

    def __init__(self, *, egress: EgressLog | None = None, cache_dir: Path | None = None,
                 offline: bool = False, token: str | None = None, backend: str = "auto"):
        self.token = token or os.environ.get("COURTLISTENER_TOKEN") or None
        self.backend = ("lookup" if self.token else "search") if backend == "auto" else backend
        self.egress = egress or EgressLog(allow={HOST})
        self.client = GuardedClient(self.egress, user_agent=USER_AGENT)
        self.cache_dir = cache_dir
        self.offline = offline
        self._mem: dict[str, Resolution] = {}
        self._last_call = 0.0

    # -- cache ------------------------------------------------------------
    def _cache_path(self, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / (key.replace("|", "_").replace(" ", "").replace(".", "") + ".json")

    def _cached(self, key: str) -> Resolution | None:
        if key in self._mem:
            return self._mem[key]
        p = self._cache_path(key)
        if p and p.exists():
            r = Resolution(**json.loads(p.read_text()))
            self._mem[key] = r
            return r
        return None

    def _store(self, key: str, r: Resolution) -> None:
        self._mem[key] = r
        p = self._cache_path(key)
        if p and not r.unavailable:  # never cache an outage as a fact
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(r.to_json(), indent=2) + "\n")

    # -- politeness -------------------------------------------------------
    def _throttle(self) -> None:
        gap = MIN_SECONDS_BETWEEN_CALLS if self.token else ANON_SECONDS_BETWEEN_CALLS
        elapsed = time.monotonic() - self._last_call
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_call = time.monotonic()

    def _request(self, method: str, url: str, payload: dict, **kwargs):
        delay = 2.0
        for attempt in range(MAX_RETRIES):
            resp, rec = self.client.request(method, url, payload=payload, note="citation only",
                                            **kwargs)
            if resp is None:
                return None, rec
            if resp.status_code == 429:
                wait = delay
                ra = resp.headers.get("Retry-After")
                if ra:
                    try:
                        wait = max(wait, float(ra))
                    except ValueError:
                        pass
                if attempt < MAX_RETRIES - 1:
                    rec.note = f"429, backing off {wait:.0f}s (attempt {attempt + 1})"
                    time.sleep(wait)
                    delay *= 2
                    continue
                rec.note = "429 after retries — lookup unavailable"
                return None, rec
            if resp.status_code >= 500:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                rec.note = f"server {resp.status_code} — lookup unavailable"
                return None, rec
            return resp, rec
        return None, None

    # -- public -----------------------------------------------------------
    def resolve(self, volume: str, reporter: str, page: str) -> Resolution:
        key = f"{volume}|{reporter}|{page}".lower()
        cached = self._cached(key)
        if cached:
            return cached
        if self.offline:
            return Resolution(found=False, unavailable=True,
                              error="offline: no cached resolution for this citation")
        self._throttle()
        if self.backend == "lookup" and self.token:
            result = self._via_lookup(volume, reporter, page)
        else:
            result = self._via_search(volume, reporter, page)
        self._store(key, result)
        return result

    def _via_search(self, volume: str, reporter: str, page: str) -> Resolution:
        cite = f"{volume} {reporter} {page}"
        # MUST be the fielded citation: query; a quoted free-text query does not phrase-match.
        params = {"q": f'citation:"{cite}"', "type": "o"}
        resp, rec = self._request("GET", SEARCH_URL, dict(params), params=params)
        if resp is None:
            return Resolution(found=False, unavailable=True,
                              error=(rec.note if rec else None) or "lookup did not complete")
        if resp.status_code >= 400:
            return Resolution(found=False, unavailable=True, error=f"HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            return Resolution(found=False, unavailable=True, error=str(exc))
        target = _normalise_cite(cite)
        for result in data.get("results", []):
            listed = result.get("citation") or []
            if any(_normalise_cite(c) == target for c in listed):
                return Resolution(found=True, case_name=result.get("caseName"),
                                  case_name_full=result.get("caseNameFull"),
                                  court=result.get("court"), date_filed=result.get("dateFiled"),
                                  precedential_status=result.get("status"),
                                  absolute_url=result.get("absolute_url"),
                                  cluster_id=result.get("cluster_id"), all_citations=listed)
        return Resolution(found=False)

    def _via_lookup(self, volume: str, reporter: str, page: str) -> Resolution:
        payload = {"volume": volume, "reporter": reporter, "page": page}
        resp, rec = self._request("POST", LOOKUP_URL, dict(payload), data=payload,
                                  headers={"Authorization": f"Token {self.token}"})
        if resp is None:
            return Resolution(found=False, unavailable=True,
                              error=(rec.note if rec else None) or "lookup did not complete")
        if resp.status_code >= 400:
            return Resolution(found=False, unavailable=True, error=f"HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            return Resolution(found=False, unavailable=True, error=str(exc))
        entries = data if isinstance(data, list) else [data]
        if not entries:
            return Resolution(found=False)
        entry = entries[0]
        clusters = entry.get("clusters") or []
        if entry.get("status") == 200 and clusters:
            c = clusters[0]
            return Resolution(found=True, case_name=c.get("case_name"),
                              case_name_full=c.get("case_name_full"), court=c.get("court_id"),
                              date_filed=c.get("date_filed"),
                              precedential_status=c.get("precedential_status"),
                              absolute_url=c.get("absolute_url"), cluster_id=c.get("id"),
                              all_citations=list(entry.get("normalized_citations") or []))
        return Resolution(found=False, error=entry.get("error_message") or f"status {entry.get('status')}")
