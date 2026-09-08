"""Verdicts. Four that say something and one that says nothing.

Renamed from the July build: VERIFIED → RESOLVED, because "existence is not
support" and the word VERIFIED is exactly the C5 trap. No verdict asserts a
citation is fake; the output is a review queue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from rapidfuzz import fuzz

from harness.runners.citations.extract import ExtractedCitation
from harness.runners.citations.resolve import Resolution


class Verdict(StrEnum):
    RESOLVED = "RESOLVED"
    NAME_MISMATCH = "NAME_MISMATCH"
    UNRESOLVED = "UNRESOLVED"
    NOT_CHECKED = "NOT_CHECKED"  # the lookup failed; says nothing about the citation
    SKIPPED = "SKIPPED"  # parallel citation of the one above it


# Chosen by measurement (see failures.md): same-case names scored 76–100 on
# token_set_ratio, different cases 20–38. 60 sits in the empty gap.
NAME_MATCH_THRESHOLD = 60

_NOISE = re.compile(r"\b(in re|ex parte|matter of|estate of|v\.?|inc|llc|co|corp|ltd|the|of|et al)\b")

#: Bluebook T6/T10 abbreviations as they appear in briefs → the word the database uses.
#: Real briefs abbreviate captions ("Sable Commc'ns of Cal. v. FCC"); databases do not.
#: Observed on recap-377506294, recap-436884607, recap-454600796 (2026-09-08).
BLUEBOOK = {
    "commc'ns": "communications", "commcns": "communications", "cal": "california", "grp": "group",
    "mod": "modern", "dev": "development", "enters": "enterprises", "equip": "equipment",
    "cnty": "county", "cty": "county", "dep't": "department", "dept": "department",
    "ass'n": "association", "assn": "association", "nat'l": "national", "natl": "national",
    "serv": "service", "servs": "services", "mktg": "marketing", "ins": "insurance",
    "env't": "environmental", "envt": "environmental", "envtl": "environmental",
    "transp": "transportation", "res": "resources", "def": "defense", "fed'n": "federation",
    "fedn": "federation", "soc": "society", "cong": "congress", "admin": "administrative",
    "off": "office", "cts": "courts", "comm'rs": "commissioners", "commrs": "commissioners",
    "comm'n": "commission", "commn": "commission", "agric": "agriculture", "rd": "road",
    "mfg": "manufacturing", "sys": "systems", "tech": "technology", "techs": "technologies",
    "int'l": "international", "intl": "international", "bd": "board", "educ": "education",
    "sch": "school", "dist": "district", "hosp": "hospital", "med": "medical", "ctr": "center",
    "indus": "industries", "prods": "products", "prod": "products", "mgmt": "management",
    "bhd": "brotherhood", "union": "union", "auth": "authority", "pub": "public", "util": "utility",
    "elec": "electric", "gen": "general", "am": "america", "n": "north", "s": "south", "e": "east",
    "w": "west", "fin": "financial", "sec": "securities", "exch": "exchange", "hous": "housing",
    "sav": "savings", "tr": "trust", "bros": "brothers", "consol": "consolidated", "ry": "railway",
    "r.r": "railroad", "rr": "railroad", "inst": "institute", "univ": "university", "coll": "college",
    "pharm": "pharmaceutical", "pharms": "pharmaceuticals", "labs": "laboratories", "lab": "laboratory",
    "cnstr": "construction", "constr": "construction", "eng'g": "engineering", "engg": "engineering",
    "ret": "retirement", "emp": "employment", "emps": "employees", "hum": "human", "rel": "relations",
    "reg'l": "regional", "regl": "regional", "prot": "protection", "conservancy": "conservancy",
}


def _expand(word: str) -> str:
    w = word.lower().strip(".,;:")
    return BLUEBOOK.get(w, BLUEBOOK.get(w.replace("’", "'"), w))


def _normalise_name(name: str) -> str:
    expanded = " ".join(_expand(w) for w in name.replace("’", "'").split())
    lowered = _NOISE.sub(" ", expanded.lower())
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", lowered).split())


def name_similarity(written: str, resolved: str) -> float:
    return fuzz.token_set_ratio(_normalise_name(written), _normalise_name(resolved))


@dataclass
class Finding:
    citation: ExtractedCitation
    resolution: Resolution
    verdict: Verdict
    similarity: float | None = None
    explanation: str = ""

    @property
    def confidence(self) -> float:
        """C3: confidence that the citation is what the document says it is."""
        match self.verdict:
            case Verdict.RESOLVED:
                return (self.similarity / 100) if self.similarity is not None else 0.5
            case Verdict.NAME_MISMATCH | Verdict.UNRESOLVED | Verdict.NOT_CHECKED:
                return 0.0
            case _:
                return 1.0

    @property
    def needs_review(self) -> bool:
        return self.verdict in (Verdict.NAME_MISMATCH, Verdict.UNRESOLVED, Verdict.NOT_CHECKED)


#: Proprietary citations no open database can resolve. A miss there says nothing
#: about the case, so it is NOT_CHECKED, never UNRESOLVED.
UNCHECKABLE_REPORTERS = {"wl", "lexis", "u.s. dist. lexis", "u.s. app. lexis", "westlaw"}


def uncheckable(cite: ExtractedCitation) -> bool:
    rep = cite.reporter.lower().strip()
    return rep in UNCHECKABLE_REPORTERS or "lexis" in rep or rep == "wl"


def classify(cite: ExtractedCitation, resolution: Resolution) -> Finding:
    if uncheckable(cite):
        return Finding(cite, resolution, Verdict.NOT_CHECKED, explanation=(
            f"{cite.reporter} is a proprietary citation (Westlaw/Lexis) that open databases do not "
            "index. Not checked here; verify in the source service."))
    if resolution.unavailable:
        return Finding(cite, resolution, Verdict.NOT_CHECKED, explanation=(
            f"The lookup did not complete ({resolution.error}). This says nothing about the "
            "citation — it was never checked. Re-run before relying on this document."))
    if not resolution.found:
        reason = resolution.error or "not found in CourtListener"
        return Finding(cite, resolution, Verdict.UNRESOLVED, explanation=(
            f"{reason}. NOT proof of fabrication — coverage is thinner for unpublished opinions, "
            "very recent decisions and state trial courts. Check it by hand."))
    written = cite.written_name
    resolved = resolution.case_name or resolution.case_name_full
    if not written or not resolved:
        return Finding(cite, resolution, Verdict.RESOLVED, explanation=(
            "Citation resolves. No case name was attached in the document, so the name could "
            "not be checked — existence only."))
    score = name_similarity(written, resolved)
    if score >= NAME_MATCH_THRESHOLD:
        return Finding(cite, resolution, Verdict.RESOLVED, similarity=score,
                       explanation=f"Resolves to {resolved}. Name matches ({score:.0f}%).")
    return Finding(cite, resolution, Verdict.NAME_MISMATCH, similarity=score, explanation=(
        f'Citation is real, but it belongs to "{resolved}" — the document calls it '
        f'"{written}" ({score:.0f}% similar). Either the name or the citation is wrong.'))
