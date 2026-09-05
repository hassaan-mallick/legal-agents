"""Citation extraction. Runs locally; nothing here makes a network call.
The document text reaches resolve.py only as {volume, reporter, page} triples.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_EMPHASIS = re.compile(r"[*_]{1,3}")
NAME_WINDOW_CHARS = 120


@dataclass
class ExtractedCitation:
    text: str  # exactly as written — this is the C1 quote
    volume: str
    reporter: str
    page: str
    start: int
    end: int
    plaintiff: str | None = None
    defendant: str | None = None
    preceding_text: str = ""
    parallel_to: int | None = field(default=None)

    @property
    def key(self) -> str:
        return f"{self.volume}|{self.reporter}|{self.page}".lower()

    @property
    def written_name(self) -> str | None:
        """Conservative: None rather than a guess. None means the name check is
        skipped and the verdict is existence-only, reported as such."""
        if self.plaintiff and self.defendant:
            return f"{self.plaintiff} v. {self.defendant}"
        if self.defendant:
            return self.defendant
        return None


def extract(text: str) -> tuple[str, list[ExtractedCitation]]:
    """Find every full case citation. Returns (cleaned_text, citations); spans
    are offsets into the cleaned text."""
    from eyecite import clean_text, get_citations
    from eyecite.models import FullCaseCitation

    cleaned = clean_text(_EMPHASIS.sub("", text), ["all_whitespace"])
    found: list[ExtractedCitation] = []
    for cite in get_citations(cleaned):
        if not isinstance(cite, FullCaseCitation):
            continue
        groups = cite.groups or {}
        volume, reporter, page = groups.get("volume"), groups.get("reporter"), groups.get("page")
        if not (volume and reporter and page):
            continue
        start, end = cite.span()
        meta = cite.metadata
        found.append(ExtractedCitation(
            text=cite.matched_text(), volume=volume, reporter=reporter, page=page,
            start=start, end=end,
            # eyecite's metadata.year is unreliable on multi-citation documents; unused.
            plaintiff=(getattr(meta, "plaintiff", None) or None),
            defendant=(getattr(meta, "defendant", None) or None),
            preceding_text=cleaned[max(0, start - NAME_WINDOW_CHARS):start]))
    _mark_parallel(found)
    return cleaned, found


def _mark_parallel(cites: list[ExtractedCitation]) -> None:
    """'531 U.S. 98, 121 S. Ct. 525' is one case cited two ways."""
    for i, cite in enumerate(cites):
        if i == 0:
            continue
        prev = cites[i - 1]
        gap = cite.start - prev.end
        if gap < 0 or gap > 3:
            continue
        if cite.written_name is None or cite.written_name == prev.written_name:
            cite.parallel_to = i - 1
