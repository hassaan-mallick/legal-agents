"""The answer a lookup gives. Kept apart from resolve.py so it imports nothing
network-bound: the browser checker (checker/) loads this, extract.py and
classify.py as they are, and does the lookup itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
    backend: str | None = None  # search | lookup — which endpoint answered
    candidates: list[str] = field(default_factory=list)  # other case names at this citation (status 300)

    def to_json(self) -> dict:
        return self.__dict__.copy()
