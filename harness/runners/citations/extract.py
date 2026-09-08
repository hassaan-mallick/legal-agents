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
        skipped and the verdict is existence-only, reported as such.

        eyecite's plaintiff is unreliable on long institutional captions after a
        connector ("Finally, Texas Department of Community Affairs v. Burdine"
        came back as "Affairs"). When the text immediately before the citation
        contains a longer "X v. Y" caption ending in the same defendant, prefer it.
        """
        if self.plaintiff and self.defendant:
            ctx = _caption_from_context(self.preceding_text, self.defendant)
            if ctx and _truncated(self.plaintiff, ctx[0]):
                return f"{ctx[0]} v. {ctx[1]}"
            return f"{_strip_connectors(self.plaintiff)} v. {self.defendant}"
        if self.defendant:
            return self.defendant
        return None


_NAME_RUN = re.compile(
    r"((?:[A-Z][\w.&'’-]*|of|the|and|for|de|du|von|&)(?:\s+(?:[A-Z][\w.&'’-]*|of|the|and|for|de|du|von|&))*)\s*$")
_VERSUS = re.compile(r"\s+v\.?\s+")
_LEADING_CONNECTORS = re.compile(
    r"^(?:see|see also|see,? e\.g\.,?|cf\.|but see|accord|finally|compare|in|and|but|also|citing|quoting|"
    r"under|per|applying|following|contra|e\.g\.),?\s+",
    re.IGNORECASE)


def _caption_from_context(preceding: str, defendant: str | None) -> tuple[str, str] | None:
    """Rebuild (plaintiff, defendant) from the words right before the citation.
    Only capitalised words and name connectors are captured, so prose stops it."""
    if not preceding or not defendant:
        return None
    window = preceding.replace("*", "").replace("_", "").rstrip()
    splits = list(_VERSUS.finditer(window))
    if not splits:
        return None
    last = splits[-1]  # the caption is the LAST "v." before the citation
    before, after = window[:last.start()], window[last.end():]
    m = _NAME_RUN.search(before)
    if not m:
        return None
    # the defendant ends where the citation numbers begin ("Liberty Lobby, Inc., 477 U.S. 242")
    deft = re.split(r",\s*\d", after.strip(), maxsplit=1)[0].strip().rstrip(",").strip()
    plaintiff = m.group(1).strip()
    if not deft or _VERSUS.search(deft):
        return None
    for _ in range(3):  # "See Finally, X" style prefixes
        plaintiff = _LEADING_CONNECTORS.sub("", plaintiff).strip()
    if not plaintiff or plaintiff.lower() in ("of", "the", "and", "for", "in", "see"):
        return None
    if defendant.split()[-1].lower().rstrip(".,") not in deft.lower():
        return None
    return plaintiff, deft


def _strip_connectors(name: str) -> str:
    for _ in range(3):
        name = _LEADING_CONNECTORS.sub("", name.strip())
    return name.strip()


def _words(name: str) -> list[str]:
    name = name.lower().replace("'", "").replace("’", "")  # ass'n → assn, ass' → ass
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", name).split()
            if w not in ("of", "the", "and", "for", "de", "du", "von")]


def _truncated(eyecite_plaintiff: str, context_plaintiff: str) -> bool:
    """eyecite kept only the tail of the caption, or dropped a stopword and left a
    double space. Accept the context caption only when it contains everything
    eyecite found and adds to it."""
    damaged = bool(re.search(r"\w['’](?:\s|$)", eyecite_plaintiff))  # "Ass'", "Nat'", "Fed'"
    e, c = _words(_strip_connectors(eyecite_plaintiff)), _words(context_plaintiff)
    if not e or not c or len(c) < len(e):
        return False
    if damaged:
        return c[-1].startswith(e[-1]) and all(any(cw.startswith(ew) for cw in c) for ew in e)
    if e[-1] != c[-1] or not set(e) <= set(c):
        return False
    return len(c) > len(e) or "  " in eyecite_plaintiff


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
    _LAST_TEXT.clear()
    for f in found:
        _LAST_TEXT[id(f)] = cleaned
    _mark_parallel(found)
    return cleaned, found


_PIN_GAP = re.compile(r"^[\s,;\d–—-]*$")
_LAST_TEXT: dict[int, str] = {}


def _between(a: ExtractedCitation, b: ExtractedCitation) -> str:
    return _LAST_TEXT.get(id(a), "")[a.end:b.start]


def _mark_parallel(cites: list[ExtractedCitation]) -> None:
    """'531 U.S. 98, 121 S. Ct. 525' is one case cited two ways."""
    for i, cite in enumerate(cites):
        if i == 0:
            continue
        prev = cites[i - 1]
        gap = cite.start - prev.end
        if gap < 0 or gap > 3:
            # a pin cite between parallels ("122 S.Ct. 2061, 2072–73, 153 L.Ed.2d 106") is
            # still the same case: allow a short gap made only of digits and punctuation
            if gap > 24 or not _PIN_GAP.match(_between(prev, cite)):
                continue
        same_case = (cite.written_name is None or cite.written_name == prev.written_name
                     or (cite.defendant and cite.defendant == prev.defendant))
        if same_case:
            cite.parallel_to = prev.parallel_to if prev.parallel_to is not None else i - 1
