"""C1 — locate every quote in its source document.

No quote, no claim. A quote the harness cannot find in the source is treated as
missing and the field is escalated with confidence 0. Fuzzy matching exists only
for reformatting noise (line wraps, OCR ligatures), never for paraphrase: the
threshold is high on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from harness.document import Document, normalise

FUZZY_THRESHOLD = 95.0
MIN_QUOTE_CHARS = 8

QuoteMatch = Literal["exact", "fuzzy", "missing"]


@dataclass
class Locator:
    char_start: int
    char_end: int
    page: int
    heading: str | None

    def to_json(self) -> dict:
        return self.__dict__.copy()


@dataclass
class QuoteResult:
    match: QuoteMatch
    locator: Locator | None = None
    score: float | None = None

    def to_json(self) -> dict:
        return {"match": self.match, "score": self.score,
                "locator": self.locator.to_json() if self.locator else None}


def locate(doc: Document, quote: str | None) -> QuoteResult:
    if not quote or len(quote.strip()) < MIN_QUOTE_CHARS:
        return QuoteResult("missing")
    q_norm, _ = normalise(quote)
    q_norm = q_norm.strip()
    if not q_norm:
        return QuoteResult("missing")

    hay = doc.normalised
    idx = hay.lower().find(q_norm.lower())
    if idx >= 0:
        return QuoteResult("exact", _locator(doc, idx, idx + len(q_norm)), 100.0)

    # rapidfuzz alignment gives the best-matching window inside the haystack.
    if len(q_norm) > 2000 or len(hay) == 0:
        return QuoteResult("missing")
    aligned = fuzz.partial_ratio_alignment(q_norm.lower(), hay.lower())
    if aligned is None or aligned.score < FUZZY_THRESHOLD:
        return QuoteResult("missing", score=aligned.score if aligned else None)
    return QuoteResult("fuzzy", _locator(doc, aligned.dest_start, aligned.dest_end), aligned.score)


def _locator(doc: Document, n_start: int, n_end: int) -> Locator:
    s, e = doc.to_original_span(n_start, n_end)
    return Locator(char_start=s, char_end=e, page=doc.page_of(s), heading=doc.heading_before(s))


def span_iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0
