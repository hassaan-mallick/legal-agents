# Browser build of the citation verifier

The free checker at [mallick.tech/tools/citation-checker](https://mallick.tech/tools/citation-checker/)
runs agent 002 in the visitor's browser. This folder builds the Python it runs.

- `bundle.py` zips `harness/runners/citations/{extract,classify,resolution}.py` exactly as the CLI runs them,
  plus eyecite, reporters-db, courts-db and rapidfuzz's pure-Python fallback at the versions in `uv.lock`.
- `py/browser.py` is the glue the page calls: `extract_json(text)` and `classify_json(index, resolution)`.
  It applies the same branches as `runner.run_document` (parallel → SKIPPED, Westlaw/Lexis → NOT_CHECKED).
- `py/ahocorasick.py` and `py/fast_diff_match_patch.py` stand in for C extensions with no wasm build.
  lxml and regex come from Pyodide.

The page does the CourtListener lookup itself, so the document never leaves the browser; only
`{volume, reporter, page}` does. CourtListener refuses cross-origin POST, so the browser uses the search
endpoint (the CLI's anonymous backend), with the visitor's own token if they give one.

```bash
uv run --extra citations python checker/bundle.py --out ../mallicktech-site/public/tools/citation-checker/py
cd checker && npm install && npm run test:pyodide   # loads the zip in real Pyodide and checks two verdicts
```

Parity, measured 2026-09-30: over the 93 documents in `corpus/` (1,596 citations), the bundle with its
stand-ins gives the same verdict, status, confidence and explanation as the native harness for every
citation, given the same lookup answers.
