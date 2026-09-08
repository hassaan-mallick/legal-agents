# Resuming the real-brief run

CourtListener's free API limits a new account to roughly a hundred lookups an hour and cuts off both the token and the anonymous path for about a day after a few hundred requests (observed 2026-09-08; see `failures.md` mode 8). Twenty-eight real briefs plus ten adversarial twins (fifty planted fabricated citations, `la corpus seed-fakes`) hold about 1,400 citations, so the first full pass takes several daily windows. Every resolved lookup is cached under `evals/cache/courtlistener/`, so each resume costs only the lookups still missing.

```bash
# 1. wait until the token window is open (429 = still limited)
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "Authorization: Token $COURTLISTENER_TOKEN" \
  -d "volume=477&reporter=U.S.&page=242" https://www.courtlistener.com/api/rest/v4/citation-lookup/

# 2. resume; it stops loudly (exit 3) when the quota trips and resumes from cache next time
uv run la run agents/002-citation-verifier --docs recap-briefs --backend lookup

# 3. when a run finishes with exit 0, everything is cached: rebuild the picture offline
uv run la run agents/002-citation-verifier --docs recap-briefs --replay
uv run la report agents/002-citation-verifier
uv run la golden draft agents/002-citation-verifier --only-resolved --out agents/002-citation-verifier/evals/golden-draft-recap.jsonl
uv run la report agents/002-citation-verifier --html runs/review-latest.html   # the page a lawyer opens
```

Do not run more than one resolver at a time against the API, and do not probe the endpoint while a run is going: both count against the same quota. If the project needs more than the free tier, Free Law Project offers research access; ask before pointing anything at their API on a client's behalf.

When every brief is resolved: merge `golden-draft-recap.jsonl` (after a person has checked and signed each line) and `golden-adversarial.jsonl` into `golden.jsonl`, run `la eval --replay`, and the results table is the real-brief number for the case study.
