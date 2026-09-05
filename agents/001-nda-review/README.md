# Agent 001: NDA Review Agent — 12 terms per agreement, every one quoted

**What it does:** Reads a confidentiality agreement and returns the twelve terms a reviewing lawyer checks first, each with the verbatim clause it came from, plus deviations from a stated playbook.
**Tier:** 0 cloud demo on public documents — inside a firm the documents come from the DMS through permission-scoped retrieval and the model runs in the firm's tenancy on a verified zero-retention endpoint.
**Cost:** measured per run; see `evals/results.json` and `evals/comparison.md` once the first eval has run.
**Reuses:** flagship architecture F1 · controls C1, C2, C3, C4, C6.
**Video:** pending · **Free template:** this folder — clone the repo and run.

## How it works

1. The harness loads an NDA from the corpus (sha256-checked) and wraps it as data inside a delimited block. The model gets no tools.
2. One structured call extracts twelve fields; the schema forces a verbatim quote and a confidence on every field.
3. Every quote is located in the source text. A quote that is not there escalates the field with confidence zero.
4. Confidence below the per-field threshold escalates. Absent terms are listed as "absences to confirm" so a negative claim is still reviewed.
5. Playbook rules run in code over the extracted values and report deviations with the quote they were judged on.
6. Output is a review queue item, never a final answer. The same run can be pointed at any model in the provider registry; the split route redacts party names locally before the model sees the text.

## Results

Not yet measured. This agent ships when a 20-document golden set (EDGAR NDAs plus injection twins) has been hand-labelled and `la eval` has written `evals/results.json` with thresholds met. Until then `la validate agents/001-nda-review` reports V08 and V09 as failing, which is correct.

## The human gate

The supervising associate on the matter reviews every item before any term or deviation flag is copied into the negotiation tracker or sent to the client. The gate sits there because a deviation flag is a negotiation position: a wrong one costs credibility with the counterparty, so each is confirmed against the quoted clause first.

## Run it yourself

```bash
uv sync --all-extras --dev
uv run la validate agents/001-nda-review
uv run la run agents/001-nda-review --docs synthetic --provider <registry name> --model <model id>
uv run la run agents/001-nda-review --docs synthetic --provider ollama-local --model <local model> --route local
```

Providers live in `harness/providers/registry.yaml`. Public and synthetic documents only; to try your own documents, add them to a corpus collection with `la corpus add-file` and keep them public or synthetic.
