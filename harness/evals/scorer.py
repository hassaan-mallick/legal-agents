"""Deterministic per-field scorers. No model judges anything here."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from rapidfuzz import fuzz

from harness.quote import span_iou

JURISDICTION_ALIASES = {
    "ny": "new york", "new york state": "new york", "state of new york": "new york",
    "de": "delaware", "state of delaware": "delaware",
    "ca": "california", "state of california": "california",
    "england": "england and wales", "english law": "england and wales", "uk": "england and wales",
    "england & wales": "england and wales", "laws of england and wales": "england and wales",
    "tx": "texas", "il": "illinois", "ma": "massachusetts",
}
_SUFFIX = re.compile(r"\b(inc|llc|l\.l\.c|ltd|limited|corp|corporation|plc|llp|gmbh|co)\b\.?", re.I)
_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def score_exact(got: Any, exp: Any) -> bool:
    return _norm(got) == _norm(exp)


def score_enum(got: Any, exp: Any) -> bool:
    return _norm(got) == _norm(exp)


def score_enum_set(got: Any, exp: Any) -> tuple[bool, float, float]:
    g, e = set(map(_norm, got or [])), set(map(_norm, exp or []))
    if not e and not g:
        return True, 1.0, 1.0
    p = len(g & e) / len(g) if g else 0.0
    r = len(g & e) / len(e) if e else 0.0
    return g == e, p, r


def parse_date(s: Any) -> dt.date | None:
    if isinstance(s, dt.date):
        return s
    if not s:
        return None
    text = str(s).strip()
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%d %B %Y", "%b %d, %Y", "%d %b %Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text), fmt).date()
        except ValueError:
            continue
    m = re.search(rf"({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})", text, re.I)
    if m:
        return parse_date(f"{m.group(1)} {m.group(2)}, {m.group(3)}")
    return None


def score_date(got: Any, exp: Any) -> bool:
    g, e = parse_date(got), parse_date(exp)
    return g is not None and g == e


def _name(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", _SUFFIX.sub("", str(s).lower())).split())


def score_party_names(got: Any, exp: Any) -> bool:
    g, e = [_name(x) for x in (got or [])], [_name(x) for x in (exp or [])]
    if len(g) != len(e):
        return False
    return all(any(fuzz.token_set_ratio(a, b) >= 90 for b in e) for a in g) and \
        all(any(fuzz.token_set_ratio(a, b) >= 90 for a in g) for b in e)


def score_jurisdiction(got: Any, exp: Any) -> bool:
    def canon(s: Any) -> str:
        n = _norm(s).replace("the ", "").replace("laws of ", "").replace("state of ", "")
        return JURISDICTION_ALIASES.get(n, n)
    return canon(got) == canon(exp)


def score_span(got_span: tuple[int, int] | None, exp_span: tuple[int, int] | None) -> float:
    if not got_span or not exp_span:
        return 0.0
    return span_iou(tuple(got_span), tuple(exp_span))


def score_field(scorer: str, got: Any, exp: Any, *, got_span=None, exp_span=None) -> dict:
    """Returns {value_ok, precision, recall, span_iou}."""
    out = {"value_ok": False, "precision": None, "recall": None, "span_iou": None}
    match scorer:
        case "exact" | "int" | "bool":
            out["value_ok"] = score_exact(got, exp)
        case "enum":
            out["value_ok"] = score_enum(got, exp)
        case "enum_set":
            ok, p, r = score_enum_set(got, exp)
            out.update(value_ok=ok, precision=p, recall=r)
        case "date":
            out["value_ok"] = score_date(got, exp)
        case "party_names":
            out["value_ok"] = score_party_names(got, exp)
        case "jurisdiction":
            out["value_ok"] = score_jurisdiction(got, exp)
        case "span":
            iou = score_span(got_span, exp_span)
            out.update(value_ok=iou >= 0.5, span_iou=iou)
        case _:
            out["value_ok"] = score_exact(got, exp)
    return out
