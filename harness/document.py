"""Documents, corpus manifests and locators.

A `Document` keeps the original text and a normalised copy with an offset map
back to the original, so a quote located in the normalised text reports a span
in the file the lawyer actually has. Page breaks are form feeds (`\\f`) in the
text; EDGAR exhibits converted to text carry them, synthetic docs may not.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_SOURCES = {"SEC EDGAR", "public court filing", "open dataset", "synthetic"}
HEADING_RE = re.compile(r"^\s*(?:(?:\d+|[IVXLC]+|[A-Z])[.)]\s+)?[A-Z][A-Z \-/&,']{3,}\s*$")

_QUOTE_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                            "–": "-", "—": "-", " ": " "})


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalise(text: str) -> tuple[str, list[int]]:
    """Return (normalised, offset_map) where offset_map[i] is the index in the
    original text of normalised character i.

    Normalisation: NFKC, straight quotes/dashes, hyphenation across line breaks
    removed, all whitespace runs collapsed to one space. Case is preserved so
    quotes stay verbatim; comparison functions lower-case both sides.
    """
    out: list[str] = []
    offsets: list[int] = []
    i = 0
    n = len(text)
    pending_space = False
    while i < n:
        ch = text[i]
        # hyphen + newline(s) = word broken across lines: drop both
        if ch == "-" and i + 1 < n and text[i + 1] in "\r\n":
            j = i + 1
            while j < n and text[j] in "\r\n ":
                j += 1
            i = j
            continue
        if ch.isspace() or ch == " ":
            pending_space = True
            i += 1
            continue
        if pending_space and out:
            out.append(" ")
            offsets.append(i - 1)
        pending_space = False
        norm = unicodedata.normalize("NFKC", ch).translate(_QUOTE_MAP)
        for c in norm:
            out.append(c)
            offsets.append(i)
        i += 1
    return "".join(out), offsets


@dataclass
class Document:
    doc_id: str
    text: str
    sha256: str
    source: str = "synthetic"
    path: Path | None = None
    normalised: str = field(init=False, repr=False)
    offset_map: list[int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.normalised, self.offset_map = normalise(self.text)

    @classmethod
    def from_path(cls, path: Path, doc_id: str | None = None, source: str = "synthetic") -> Document:
        text = path.read_text(encoding="utf-8")
        return cls(doc_id=doc_id or path.stem, text=text, sha256=sha256_text(text), source=source,
                   path=path)

    def to_original_span(self, start: int, end: int) -> tuple[int, int]:
        """Map a span in normalised text to a span in the original text."""
        if not self.offset_map:
            return (0, 0)
        s = self.offset_map[min(start, len(self.offset_map) - 1)]
        e = self.offset_map[min(max(end - 1, 0), len(self.offset_map) - 1)] + 1
        return (s, e)

    def page_of(self, original_offset: int) -> int:
        return self.text.count("\f", 0, original_offset) + 1

    def heading_before(self, original_offset: int) -> str | None:
        head = self.text[:original_offset]
        for line in reversed(head.splitlines()):
            if HEADING_RE.match(line):
                return line.strip()[:120]
        return None


# --------------------------------------------------------------------------- manifests


@dataclass
class ManifestEntry:
    doc_id: str
    file: str
    sha256: str
    bytes: int
    collection: str
    source: str
    licence: str = ""
    url: str | None = None
    accession: str | None = None
    filer: str | None = None
    form: str | None = None
    filed: str | None = None
    fetched_at: str | None = None
    derived_from: str | None = None
    kind: str = "standard"  # standard | sparse | injection
    notes: str = ""

    def to_json(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.collection_dir = path.parent
        self.collection = self.collection_dir.name
        self.entries: dict[str, ManifestEntry] = {}
        if path.exists():
            data = json.loads(path.read_text())
            for raw in data.get("documents", []):
                entry = ManifestEntry(**raw)
                self.entries[entry.doc_id] = entry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"collection": self.collection,
                   "documents": [e.to_json() for e in self.entries.values()]}
        self.path.write_text(json.dumps(payload, indent=2) + "\n")

    def load(self, doc_id: str) -> Document:
        entry = self.entries[doc_id]
        path = self.collection_dir / entry.file
        doc = Document.from_path(path, doc_id=doc_id, source=entry.source)
        if sha256_file(path) != entry.sha256:
            raise ValueError(f"{doc_id}: file sha256 does not match manifest (tampered or edited)")
        return doc

    def verify(self) -> list[str]:
        problems = []
        for doc_id, entry in self.entries.items():
            path = self.collection_dir / entry.file
            if not path.exists():
                problems.append(f"{doc_id}: missing file {entry.file}")
                continue
            if sha256_file(path) != entry.sha256:
                problems.append(f"{doc_id}: sha256 mismatch")
            if entry.source not in ALLOWED_SOURCES:
                problems.append(f"{doc_id}: source {entry.source!r} not allowed")
        return problems

    def add_file(self, path: Path, *, doc_id: str, source: str, **meta) -> ManifestEntry:
        if source not in ALLOWED_SOURCES:
            raise ValueError(f"source must be one of {sorted(ALLOWED_SOURCES)}")
        entry = ManifestEntry(doc_id=doc_id, file=str(path.relative_to(self.collection_dir)),
                              sha256=sha256_file(path), bytes=path.stat().st_size,
                              collection=self.collection, source=source, **meta)
        self.entries[doc_id] = entry
        return entry


def find_manifest(corpus_root: Path, doc_id: str, collections: list[str]) -> tuple[Manifest, ManifestEntry] | None:
    for coll in collections:
        m = Manifest(corpus_root / coll / "manifest.json")
        if doc_id in m.entries:
            return m, m.entries[doc_id]
    return None
