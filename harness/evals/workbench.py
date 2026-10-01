"""Hand-labelling workbench for golden.jsonl.

A static page a person opens in a browser to label every field of every golden
document. No model is involved anywhere in this file: the candidate passages are
plain keyword hits in the source text, offered only to save scrolling. The person
reads the clause, sets the value, and the quote is the evidence. Exported lines
carry the person's name in `labelled_by`; `merge` refuses drafts and refuses any
quote the harness cannot locate in the source (C1 applies to labels too).
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

from harness.document import Manifest
from harness.evals.golden import load_golden
from harness.loader import Agent, corpus_dir
from harness.quote import locate

# Keyword hints per field. Sentence-level, case-insensitive, deliberately broad:
# a miss costs the person a scroll, a false hit costs a glance.
CANDIDATES: dict[str, list[str]] = {
    "parties": [
        '\\bby and between\\b',
        '\\bbetween\\b.{0,200}\\band\\b',
        '\\bentered into\\b',
    ],
    "effective_date": [
        '\\beffective (date|as of)\\b',
        '\\bdated as of\\b',
        '\\bmade (and entered into )?(as of|on|this)\\b',
        '\\b(january|february|march|april|may|june|july|august|september|october|november|december)\\s+\\d{1,2},?\\s+(19|20)\\d{2}\\b',
        '\\b\\d{1,2}(st|nd|rd|th)? day of\\b',
    ],
    "term": [
        '\\bterm of this agreement\\b',
        '\\b(remain|continue) in (full )?(force|effect)\\b',
        '\\bshall (terminate|expire)\\b',
        '\\bperiod of\\b.{0,40}\\b(year|month)s?\\b',
        '\\bterminat(e|ion) (of|this)\\b',
        '\\banniversary\\b',
    ],
    "confidential_information_definition": [
        '[\\"“”\']confidential information[\\"“”\']\\s*(means|shall mean|includes|refers|is defined|as used)',
        '\\bconfidential information\\b.{0,30}\\b(means|shall mean|shall include)\\b',
        '\\bproprietary information[\\"“”\']?\\s*(means|shall mean)\\b',
    ],
    "exclusions": [
        '\\b(does|shall|will) not (include|apply)\\b',
        '\\bexclud',
        '\\bpublicly (available|known)\\b',
        '\\bpublic domain\\b',
        '\\bindependently developed\\b',
        '\\balready (known|in the possession)\\b',
        '\\brightfully\\b',
        '\\brequired (by|to be disclosed by) (law|court|order)\\b',
        '\\bsubpoena\\b',
    ],
    "permitted_disclosures": [
        '\\bneed[- ]to[- ]know\\b',
        r'\bdisclos\w+ .{0,80}\b(employees|officers|directors|affiliates|representatives'
        r'|advisors|advisers|agents|contractors)\b',
        '\\bmay (disclose|share)\\b',
    ],
    "return_or_destroy": [
        '\\breturn(ed)?\\b.{0,60}\\b(destroy|destruction)',
        '\\bdestroy|destruction\\b',
        '\\breturn (all|any|the) \\b',
    ],
    "governing_law": [
        '\\bgoverned by\\b',
        '\\blaws of (the )?(state|commonwealth|province)?\\b',
        '\\bconstrued (in accordance|under)\\b',
        '\\bgoverning law\\b',
    ],
    "jurisdiction_forum": [
        '\\bcourts? (of|in|located|sitting)\\b',
        '\\bjurisdiction\\b',
        '\\bvenue\\b',
        '\\barbitrat',
        '\\bforum\\b',
    ],
    "assignment": [
        '\\bassign',
    ],
    "survival": [
        '\\bsurviv',
        '\\b(after|following|upon) (the )?(termination|expiration|expiry)\\b',
        '\\bfor a period of\\b.{0,60}\\b(after|following)\\b',
        '\\bperpetu',
        '\\btrade secret',
    ],
    "remedies": [
        '\\binjunct',
        '\\bequitable relief\\b',
        '\\bspecific performance\\b',
        '\\bindemnif',
        '\\bliquidated damages\\b',
        '\\birreparable\\b',
        '\\bremed(y|ies)\\b',
    ],
}

_SENT = re.compile(r"[^\n]+")
# a sentence ends at . ; : ! ? followed by space and a capital, quote or bracket
_SPLIT = re.compile(r".+?(?:(?<=[.;:!?])\s+(?=[A-Z(\"“])|$)")


def _sentences(text: str) -> list[tuple[int, int, str]]:
    """Paragraph lines split at sentence ends, each with its original offsets."""
    out: list[tuple[int, int, str]] = []
    for m in _SENT.finditer(text):
        line, base = m.group(0), m.start()
        pos = 0
        for sm in _SPLIT.finditer(line):
            s = sm.group(0)
            if s.strip():
                out.append((base + sm.start(), base + sm.end(), s))
            pos = sm.end()
        if pos < len(line) and line[pos:].strip():
            out.append((base + pos, base + len(line), line[pos:]))
    return out


def _candidates(text: str, patterns: list[str], limit: int = 10) -> list[dict]:
    hits: list[dict] = []
    seen: set[int] = set()
    rx = [re.compile(p, re.I | re.S) for p in patterns]
    for start, end, s in _sentences(text):
        if start in seen:
            continue
        if any(r.search(s) for r in rx):
            seen.add(start)
            hits.append({"start": start, "end": end, "text": s.strip()[:700]})
        if len(hits) >= limit:
            break
    return hits


def _load_doc(agent: Agent, doc_id: str):
    for coll in agent.spec.input.corpus:
        m = Manifest(corpus_dir() / coll / "manifest.json")
        if doc_id in m.entries:
            return m.load(doc_id)
    raise FileNotFoundError(doc_id)


def build(agent: Agent, out: Path) -> Path:
    cases = load_golden(agent.evals_dir / "golden.jsonl")
    docs = []
    for c in cases:
        if c.kind == "injection":
            continue
        doc = _load_doc(agent, c.doc_id)
        expected = c.expected if isinstance(c.expected, dict) else {}
        docs.append({
            "doc_id": c.doc_id,
            "text": doc.text,
            "draft": expected,
            "draft_by": c.labelled_by or "",
            "notes": c.notes,
            "candidates": {f: _candidates(doc.text, pats) for f, pats in CANDIDATES.items()},
        })
    fields = [{"name": n, "type": f.type, "enum": f.enum, "description": f.description, "scorer": f.scorer}
              for n, f in agent.schema.fields.items()]
    doc_fields = [{"name": n, "enum": getattr(f, "enum", None), "description": getattr(f, "description", None)}
                  for n, f in agent.schema.document_fields.items()]
    payload = {"agent": agent.folder, "fields": fields, "document_fields": doc_fields, "docs": docs,
               "built": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    page = _PAGE.replace("__TITLE__", html.escape(agent.spec.title)).replace(
        "__DATA__", json.dumps(payload).replace("</", "<\\/"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def merge(agent: Agent, labels: Path, *, allow_unquoted: bool = False) -> dict:
    """Fold exported lines into golden.jsonl. Refuses drafts and unlocatable quotes."""
    new: dict[str, dict] = {}
    errors: list[str] = []
    for ln in labels.read_text().splitlines():
        if not ln.strip():
            continue
        row = json.loads(ln)
        who = (row.get("labelled_by") or "").strip()
        if not who or who.lower().startswith("draft"):
            errors.append(f"{row.get('doc_id')}: labelled_by must be a person's name, got {who!r}")
            continue
        doc = _load_doc(agent, row["doc_id"])
        expected = row["expected"]
        for name in agent.schema.fields:
            cell = expected.get(name)
            if cell is None or cell.get("present") is None:
                errors.append(f"{row['doc_id']}.{name}: unlabelled (present is null)")
                continue
            if cell["present"]:
                q = cell.get("quote")
                if not q:
                    if not allow_unquoted:
                        errors.append(f"{row['doc_id']}.{name}: present but no quote")
                    cell["span"] = None
                    continue
                r = locate(doc, q)
                if r.match == "missing" or not r.locator:
                    errors.append(f"{row['doc_id']}.{name}: quote not found in source: {q[:60]!r}")
                    continue
                cell["span"] = [r.locator.char_start, r.locator.char_end]
                cell["quote"] = q
            else:
                cell["value"], cell["quote"], cell["span"] = None, None, None
            cell.pop("todo", None)
        new[row["doc_id"]] = {
            "doc_id": row["doc_id"], "kind": row.get("kind", "standard"), "expected": expected,
            "labelled_by": who, "labelled_on": row.get("labelled_on") or dt.date.today().isoformat(),
            "notes": row.get("notes", ""),
        }
    if errors:
        return {"merged": 0, "errors": errors}
    path = agent.evals_dir / "golden.jsonl"
    out_lines = []
    replaced = 0
    for ln in path.read_text().splitlines():
        if not ln.strip():
            continue
        row = json.loads(ln)
        if row["doc_id"] in new:
            out_lines.append(json.dumps(new.pop(row["doc_id"]), ensure_ascii=False))
            replaced += 1
        else:
            out_lines.append(ln)
    for row in new.values():  # documents not yet in golden.jsonl
        out_lines.append(json.dumps(row, ensure_ascii=False))
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return {"merged": replaced + len(new), "replaced": replaced, "added": len(new), "errors": []}


_PAGE = (Path(__file__).with_name("workbench_page.html")).read_text(encoding="utf-8")
