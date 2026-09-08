"""Seed fabricated citations into real briefs — the adversarial test for the citation verifier.

Each seeded document is a twin of a real brief with K invented citations inserted into
existing sentences, each with a plausible case name. Every planted citation must come back
UNRESOLVED (or NAME_MISMATCH if the invented numbers happen to hit a real case — that is
recorded, not hidden). The manifest records exactly what was planted, and the draft golden line
carries the planted findings so a person can check the rest.

Fabricated reporters/pages are generated far outside real volume ranges where possible, but the
only proof a citation is fabricated is a lookup, so the seeded docs still need the API window.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from harness.document import Manifest

SURNAMES = ["Okafor", "Whitfield", "Delacroix", "Marbury", "Tessaly", "Harrington", "Vance", "Okonkwo",
            "Beaumont", "Castellano", "Lindqvist", "Ashworth", "Pemberton", "Halvorsen", "Orrindale", "Kestrel"]
ENTITIES = ["Logistics Group, Inc.", "Capital Partners", "Holdings LLC", "Biosciences Ltd.", "Analytics, Inc.",
            "Ridge Holdings LLC", "Maritime Corp.", "Dynamics, Inc.", "Health Systems", "Energy Partners LP"]
REPORTERS = [("F.3d", 950, 999), ("F.4th", 120, 199), ("F. Supp. 3d", 780, 899), ("F.2d", 1000, 1099),
             ("F. App'x", 900, 999)]
COURTS = {"F.3d": ["2d Cir.", "4th Cir.", "7th Cir.", "9th Cir.", "11th Cir."],
          "F.4th": ["2d Cir.", "5th Cir.", "9th Cir."], "F. Supp. 3d": ["S.D.N.Y.", "N.D. Ill.", "E.D. Pa.", "D. Md."],
          "F.2d": ["3d Cir.", "6th Cir.", "8th Cir."], "F. App'x": ["3d Cir.", "6th Cir.", "11th Cir."]}
SENTENCE_END = re.compile(r"(?<=[a-z\)])\.\s+(?=[A-Z])")


def _fake_citation(rng: random.Random) -> tuple[str, str, str]:
    reporter, lo, hi = rng.choice(REPORTERS)
    volume = rng.randint(lo, hi)
    page = rng.randint(1000, 1999)
    court = rng.choice(COURTS[reporter])
    year = rng.randint(2014, 2024)
    name = rng.choice([f"{rng.choice(SURNAMES)} v. {rng.choice(SURNAMES)} {rng.choice(ENTITIES)}",
                       f"{rng.choice(SURNAMES)} v. {rng.choice(SURNAMES)}",
                       f"In re {rng.choice(SURNAMES)} {rng.choice(ENTITIES)}"])
    cite = f"{volume} {reporter} {page}"
    sentence = f" {name}, {cite} ({court} {year})."
    return name, cite, sentence


def seed_document(text: str, k: int, rng: random.Random) -> tuple[str, list[dict]]:
    """Insert k fabricated citations after k different sentence ends in the body."""
    ends = [m.end() for m in SENTENCE_END.finditer(text)]
    body = [e for e in ends if len(text) * 0.15 < e < len(text) * 0.9]
    if len(body) < k:
        body = ends
    positions = sorted(rng.sample(body, min(k, len(body))), reverse=True)
    planted = []
    for pos in positions:
        name, cite, sentence = _fake_citation(rng)
        insert = f"See also{sentence}"
        text = text[:pos] + insert + " " + text[pos:]
        planted.append({"citation": cite, "written_name": name, "verdict": "UNRESOLVED"})
    return text, list(reversed(planted))


def seed_collection(collection_dir: Path, doc_ids: list[str], *, per_doc: int = 5,
                    seed: int = 2026) -> list[dict]:
    manifest = Manifest(collection_dir / "manifest.json")
    rng = random.Random(seed)
    out = []
    for doc_id in doc_ids:
        entry = manifest.entries[doc_id]
        text = (collection_dir / entry.file).read_text()
        new_text, planted = seed_document(text, per_doc, rng)
        new_id = f"{doc_id}-fake{per_doc}"
        path = collection_dir / "docs" / f"{new_id}.txt"
        header = (f"> ADVERSARIAL TEST TWIN of {doc_id}: {len(planted)} fabricated citations were inserted by "
                  "`la corpus seed-fakes`. Not a real filing in this form.\n\n")
        path.write_text(header + new_text)
        manifest.add_file(path, doc_id=new_id, source="synthetic", licence="derived; see parent",
                          derived_from=doc_id, kind="adversarial",
                          notes="planted: " + json.dumps(planted))
        out.append({"doc_id": new_id, "twin_of": doc_id, "planted": planted})
    manifest.save()
    return out
