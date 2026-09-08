"""ContractNLI (Stanford, CC BY 4.0) → NDA corpus + draft golden lines for agent 001.

ContractNLI labels 607 NDAs against 17 hypotheses with evidence spans. Six of
those hypotheses map onto fields in our NDA schema; the rest of the schema
(parties, dates, governing law, forum, assignment, remedies, the CI definition)
has no public label and must be filled by a person. The importer writes what it
can, leaves the rest `present: null`, and marks every line as a draft.

Source: https://stanfordnlp.github.io/contract-nli/  (Koreeda & Manning, 2021)
"""

from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path

from harness.document import Manifest

# hypothesis id → (our field, how to interpret an Entailment). IDs verified against
# the shipped dev.json on 2026-09-08; they do not match the paper's table order.
HYPOTHESIS_MAP: dict[str, tuple[str, str]] = {
    # nda-19 "Some obligations of Agreement may survive termination of Agreement."
    "nda-19": ("survival", "text"),
    # nda-16 "Receiving Party shall destroy or return some Confidential Information upon the termination."
    "nda-16": ("return_or_destroy", "return_or_destroy"),
    # nda-7 "Receiving Party may share some Confidential Information with some third-parties
    #        (including consultants, agents and professional advisors)."
    "nda-7": ("permitted_disclosures", "text"),
    # nda-13 "Receiving Party may acquire information similar to Confidential Information from a third party."
    "nda-13": ("exclusions", "third_party_rightful"),
    # nda-12 "Receiving Party may independently develop information similar to Confidential Information."
    "nda-12": ("exclusions", "independently_developed"),
    # nda-8 "Receiving Party shall notify Disclosing Party in case Receiving Party is required by law,
    #        regulation or judicial process to disclose any Confidential Information."
    "nda-8": ("exclusions", "required_by_law"),
}

ALL_FIELDS = ["parties", "effective_date", "term", "confidential_information_definition", "exclusions",
              "permitted_disclosures", "return_or_destroy", "governing_law", "jurisdiction_forum",
              "assignment", "survival", "remedies"]


_BLANKS = ("……", "_____", "[insert", "[name", "[date", "<company", "<research")


def _looks_like_blank_template(text: str) -> bool:
    low = text[:6000].lower()
    return any(b in low for b in _BLANKS)


def _load_split(root: Path, split: str) -> dict:
    for p in root.rglob(f"{split}.json"):
        return json.loads(p.read_text())
    raise FileNotFoundError(f"{split}.json not found under {root}")


def import_contract_nli(dataset_root: Path, collection_dir: Path, *, count: int = 20,
                        seed: int = 2026, out: Path | None = None,
                        max_chars: int = 60_000) -> tuple[int, Path]:
    data = _load_split(dataset_root, "train")
    dev = _load_split(dataset_root, "dev")
    labels = data["labels"]
    docs = [d for d in data["documents"] + dev["documents"]
            if len(d["text"]) <= max_chars and not _looks_like_blank_template(d["text"])]
    rng = random.Random(seed)
    rng.shuffle(docs)
    chosen = docs[:count]

    manifest = Manifest(collection_dir / "manifest.json")
    doc_dir = collection_dir / "docs"
    doc_dir.mkdir(parents=True, exist_ok=True)
    golden: list[dict] = []
    hyp_text = {k: v["hypothesis"] for k, v in labels.items()}

    for d in chosen:
        doc_id = f"cnli-{d['id']}"
        text = d["text"]
        path = doc_dir / f"{doc_id}.txt"
        header = ("> Source: ContractNLI (Stanford NLP), CC BY 4.0. A real, public NDA collected by the dataset "
                  "authors from EDGAR and the public web; used here unmodified for evaluation.\n\n")
        path.write_text(header + text)
        offset = len(header)
        src_url = d.get("url") or "https://stanfordnlp.github.io/contract-nli/"
        manifest.add_file(path, doc_id=doc_id,
                          source="SEC EDGAR" if "sec.gov" in src_url else "open dataset",
                          licence="CC BY 4.0 (ContractNLI)", url=src_url,
                          notes=f"ContractNLI id {d['id']}, file {d['file_name']}, type {d.get('document_type')}")

        spans = d["spans"]
        ann = d["annotation_sets"][0]["annotations"]
        expected: dict[str, dict] = {f: {"present": None, "value": None, "quote": None, "span": None}
                                     for f in ALL_FIELDS}
        exclusions: list[str] = []
        excl_quotes: list[tuple[str, list[int]]] = []
        for hid, (field, how) in HYPOTHESIS_MAP.items():
            a = ann.get(hid)
            if not a:
                continue
            choice = a["choice"]
            ev = [spans[i] for i in a.get("spans", [])]
            if choice == "Entailment" and ev:
                s, e = ev[0]
                quote = text[s:e].strip()
                if field == "exclusions":
                    exclusions.append(how)
                    excl_quotes.append((quote, [s + offset, e + offset]))
                elif field == "return_or_destroy":
                    expected[field] = {"present": True, "value": None, "quote": quote,
                                       "span": [s + offset, e + offset],
                                       "todo": "set value: return | destroy | return_or_destroy"}
                else:
                    expected[field] = {"present": True, "value": quote, "quote": quote,
                                       "span": [s + offset, e + offset]}
            elif choice == "NotMentioned" and field != "exclusions":
                expected[field] = {"present": False, "value": None, "quote": None, "span": None}
        if exclusions:
            q, sp = excl_quotes[0]
            expected["exclusions"] = {"present": True, "value": sorted(set(exclusions)), "quote": q, "span": sp,
                                      "todo": "confirm the full carve-out list; only three are labelled by ContractNLI"}
        golden.append({"doc_id": doc_id, "kind": "standard", "expected": expected,
                       "labelled_by": "draft: ContractNLI labels mapped by harness; NOT yet checked by a person",
                       "labelled_on": dt.date.today().isoformat(),
                       "notes": "Fields with present: null have no public label and need a person. "
                                "Hypotheses: " + "; ".join(f"{k}={hyp_text[k][:40]}" for k in HYPOTHESIS_MAP)})
    manifest.save()
    out = out or (collection_dir.parent.parent / "agents" / "001-nda-review" / "evals" / "golden-draft.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(g) for g in golden) + "\n")
    return len(golden), out
