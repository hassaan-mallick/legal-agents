"""Local de-identification for the split route.

Regex-based, no network, no model. Replaces party-like names, emails, phone
numbers, monetary amounts and dates with stable placeholders and keeps the
reversible map on disk under runs/ only. This is deliberately simple: the point
of the split route is that the hosted model never sees the identifiers, and the
quality cost of that is then measured per route by `la eval`.

A missed entity is a known failure mode (document it in failures.md); the
answer is a better local NER step, not sending the original upstream.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_ORG_SUFFIX = r"(?:Inc\.?|LLC|L\.L\.C\.|Ltd\.?|Limited|Corp\.?|Corporation|plc|LLP|GmbH|S\.A\.|Co\.?)"
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("PHONE", re.compile(r"\+?\d[\d\s().-]{8,}\d")),
    ("ORG", re.compile(rf"\b(?:[A-Z][\w&'-]+,?\s){{1,5}}{_ORG_SUFFIX}")),
    ("MONEY", re.compile(r"(?:\$|£|€|USD|GBP|EUR)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:million|billion|m|bn))?")),
    ("DATE", re.compile(r"\b(?:\d{1,2}(?:st|nd|rd|th)?\s+)?" + _MONTHS + r"\s+\d{1,2}?,?\s*\d{4}\b")),
]


@dataclass
class RedactionMap:
    forward: dict[str, str] = field(default_factory=dict)   # original -> placeholder
    reverse: dict[str, str] = field(default_factory=dict)   # placeholder -> original
    counters: dict[str, int] = field(default_factory=dict)

    def placeholder(self, kind: str, original: str) -> str:
        if original in self.forward:
            return self.forward[original]
        self.counters[kind] = self.counters.get(kind, 0) + 1
        ph = f"[{kind}_{self.counters[kind]}]"
        self.forward[original] = ph
        self.reverse[ph] = original
        return ph

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"reverse": self.reverse}, indent=2) + "\n")


def redact(text: str) -> tuple[str, RedactionMap]:
    rmap = RedactionMap()
    out = text
    for kind, pattern in PATTERNS:
        def _sub(m: re.Match, kind=kind) -> str:
            return rmap.placeholder(kind, m.group(0))
        out = pattern.sub(_sub, out)
    return out, rmap


def reidentify(text: str, rmap: RedactionMap) -> str:
    for ph, original in sorted(rmap.reverse.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(ph, original)
    return text
