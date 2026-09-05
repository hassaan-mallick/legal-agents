# Agent 002: Citation Verifier — does that case exist, and is it the case you named?

**What it does:** Finds every full case citation in a brief, checks each against CourtListener (the Free Law Project's open database), and returns a review queue: resolved, name mismatch, unresolved, or not checked.
**Tier:** 0, local — inside a firm the same interface sits in front of a paid lookup, the queue lands in the filing workflow, and the egress log is kept as evidence that no brief text left the firm.
**Cost:** zero. No model call. Extraction is local (`eyecite`); resolution is a free API.
**Reuses:** R11 in the series matrix; precursor to flagship F5 · controls C1–C6.
**Video:** pending · **Free template:** this folder.

## How it works

1. `eyecite` extracts full case citations locally. Nothing in that step touches the network.
2. Only the `{volume, reporter, page}` triple is sent to CourtListener through the guarded client. Every outbound request is written to `egress.jsonl`, and the run asserts that no document text appears in it.
3. Three verdicts that say something and one that says nothing: **RESOLVED** (the citation exists and the name in the brief matches the database), **NAME_MISMATCH** (the citation is real but belongs to a different case — the realistic fabrication, a plausible name on real numbers), **UNRESOLVED** (not in the database; explicitly not proof of fabrication), **NOT_CHECKED** (the lookup did not complete; an outage must never look like a finding).
4. The citation text as written is the C1 quote and is located in the source. Anything other than RESOLVED escalates; RESOLVED with no name to compare carries confidence 0.5 and is reported as existence-only.
5. The document disposition is fixed to `needs_review` or `escalated`. There is no `safe_to_file`.

## Results

Measured on 20 synthetic briefs generated from a pool of well-known Supreme Court citations, each brief carrying planted defects (a wholly fabricated citation, a real citation with an invented name, and in every third brief a real case with two digits transposed). See `evals/results.json` and `evals/comparison.md`. The transposed-digit case is scored UNRESOLVED on purpose: the tool cannot tell a typo from a fabrication, and the eval records that ceiling rather than hiding it. Misses are documented in [failures.md](failures.md).

## The human gate

The filing attorney reviews the queue before the table of authorities is finalised. The gate sits there because an unresolved citation is not proof of fabrication and a resolved one is not proof the case supports the proposition; the court holds the signing lawyer to both, and the tool has no authority over either.

## Run it yourself

```bash
uv sync --all-extras --dev
export COURTLISTENER_TOKEN=...   # free, optional, strongly recommended (anonymous access is throttled hard)
uv run la validate agents/002-citation-verifier
uv run la run agents/002-citation-verifier --docs brief-001
uv run la eval agents/002-citation-verifier --replay   # offline, from the committed cache
```

To check your own document: add it to `corpus/synthetic` with `la corpus add-file` (synthetic or public filings only), then run. US citation formats only; UK neutral citations are not parsed yet.
