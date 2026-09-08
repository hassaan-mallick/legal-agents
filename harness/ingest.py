"""Document ingestion: PDF → text with page breaks and provenance.

Page boundaries become form feeds (\\f) so `Document.page_of()` can report the
page a quote sits on. Layout noise that breaks citation parsing (hyphenation
across line ends, running headers repeated on every page) is cleaned
conservatively; nothing else is rewritten, because the text is the evidence.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_LINE_NUMBER = re.compile(r"^\s*\d{1,2}\s{2,}", re.M)  # pleading-paper line numbers
_PAGE_STAMP = re.compile(r"Case\s+\S+\s+Document\s+\d+.*?Page\s+\d+\s+of\s+\d+", re.I)


@dataclass
class IngestResult:
    text: str
    pages: int
    dropped_header_lines: int


def _strip_repeated_headers(pages: list[str]) -> tuple[list[str], int]:
    """Drop lines that appear on most pages (running headers/footers)."""
    if len(pages) < 3:
        return pages, 0
    counts: Counter[str] = Counter()
    for p in pages:
        for line in {ln.strip() for ln in p.splitlines() if ln.strip()}:
            counts[line] += 1
    repeated = {ln for ln, n in counts.items() if n >= max(3, int(len(pages) * 0.6)) and len(ln) < 120}
    dropped = 0
    out = []
    for p in pages:
        kept = []
        for ln in p.splitlines():
            if ln.strip() in repeated:
                dropped += 1
                continue
            kept.append(ln)
        out.append("\n".join(kept))
    return out, dropped


def pdf_to_text(path: Path) -> IngestResult:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        txt = page.extract_text() or ""
        txt = _PAGE_STAMP.sub("", txt)
        txt = _LINE_NUMBER.sub("", txt)
        pages.append(txt)
    pages, dropped = _strip_repeated_headers(pages)
    text = "\f".join(p.strip("\n") + "\n" for p in pages)
    return IngestResult(text=text, pages=len(pages), dropped_header_lines=dropped)


def ingest(path: Path) -> IngestResult:
    if path.suffix.lower() == ".pdf":
        return pdf_to_text(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return IngestResult(text=text, pages=text.count("\f") + 1, dropped_header_lines=0)
