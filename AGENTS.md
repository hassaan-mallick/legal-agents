# AGENTS.md — legal-agents

Read this first. It is the only instruction file in this repo. `CLAUDE.md` imports it; `.cursor/rules/` mirrors the parts that matter per folder.

Legal AI agents built in public by Hassaan Mallick, a former lawyer. Every agent here is plain files run by one Python harness. The model is chosen at runtime, never inside an agent. Governance is code, not a checklist.

**The one rule: no quote, no claim.** Every extraction carries a verbatim quote the harness locates in the source. If it cannot be located, the claim is escalated, not reported.

## Non-negotiables

1. **Public or synthetic documents only.** SEC EDGAR exhibits, public court filings, or documents written here. Never a client document, never a real matter. `corpus/*/manifest.json` records the source and sha256 of every file.
2. **Agents flag; they never clear.** No output is `final`, `cleared`, `approved`, `compliant`, or `safe_to_file`. Output is a review queue with a named human gate.
3. **No model or provider names under `agents/`.** `agent.yaml` says `model: provider_chosen_at_runtime`. Models are selected with `--provider` / `--model` (or `LA_PROVIDER` / `LA_MODEL`) from `harness/providers/registry.yaml`. `la validate` greps for model names and fails.
4. **No secrets in files.** Environment variables only (`.env.example` lists the names). `la scan` runs in CI.
5. **Confidential or privileged text goes only to endpoints with verified zero data retention.** `zdr: true` plus a `verified_on` date in the registry; everything else is `unverified`. The harness refuses otherwise (control C6). The split route redacts locally first.
6. **Nothing ships below the rep bar:** a 20-document golden set labelled by a person, at least two injection canary documents, `evals/results.json` committed with thresholds met, at least three failure modes in `failures.md` with one observed, tier declared and the enterprise gap stated.
7. **Never edit `golden.jsonl` to make a run pass.** Never let a model pre-fill labels. Never lower `thresholds.yaml` after seeing a result. Draft labels (from `la golden draft` or a public dataset importer) carry `labelled_by: draft…` and stay drafts until a person checks every line and signs them; results on draft labels say so.
8. **Never run live evals without being asked.** They cost money. `la eval --replay` is free and is what CI runs.

## Layout

```
AGENTS.md · CLAUDE.md (@AGENTS.md) · .cursor/rules/      instructions
harness/            the Python package; CLI `la`
  spec.py           agent.yaml / schema.yaml / thresholds.yaml models (structural validation)
  schema_build.py   wraps every field in {present, value, quote, confidence, note}   (C1, C3)
  document.py       corpus manifests, sha256, normalisation, locators
  quote.py          locate every quote in the source; missing → escalated               (C1)
  gate.py           confidence gates, forbidden-disposition scan                         (C3, C5)
  review.py         ReviewItem: pending_review | escalated, never final                  (C2)
  routing.py        retention-class routing over providers/registry.yaml                 (C6)
  redact.py         local de-identification for the split route
  egress.py         allowlist + egress log; the only network chokepoint
  providers/        anthropic_native, openai_compat (openai/azure/ollama/openrouter), replay, none
  runners/          llm_extract (generic), citations (no model)
  validate/rules.py V01–V18, one function per rule
  evals/            golden loader, deterministic scorers, results, comparison
agents/NNN-slug/    agent.yaml schema.yaml prompts/ [playbook.yaml] evals/ README.md failures.md
corpus/             edgar-nda/ synthetic/ injections/ — each with manifest.json
governance/         controls-library.md failure-atlas.md framework.md agents-index.md
_template/          copy to start a new agent
tests/              pytest; fixture agents under tests/fixtures/agents/
runs/               gitignored output: review queues, run.json, egress.jsonl, usage.jsonl
```

## Commands

```bash
uv sync --all-extras --dev                    # setup (Python 3.13)
uv run la validate <agent> | --all            # the bar; fails loudly
uv run la run <agent> --docs <collection|doc_id> --provider <name> --model <id> [--route best-quality|zdr|local|split]
uv run la eval <agent> --replay               # offline from evals/cache (CI)
uv run la eval <agent> --provider X --model Y --record   # live; writes cache + results (ask first)
uv run la compare <agent>                     # evals/comparison.md across provider/model/route
uv run la corpus verify | add-file (txt/md/pdf) | inject | fetch-recap | import-contract-nli | make-briefs
uv run la golden locate --doc <doc_id> --quote "..."   # prints the span for hand-labelling
uv run la golden draft <agent>                # a run → draft labels; NOT labels until a person signs labelled_by
uv run la scan                                # secrets scan
uv run la governance sync                     # regenerate agents-index.md and "Also used by"
uv run pytest && uv run ruff check .
```

Env: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AZURE_OPENAI_*`, `OPENROUTER_API_KEY`, `COURTLISTENER_TOKEN`, `LA_PROVIDER`, `LA_MODEL`, `LA_ROUTE`, `LA_EFFORT`, `LA_REVIEWER`, `EDGAR_USER_AGENT`.

## How to add an agent

1. Copy `_template/` to `agents/NNN-slug/` (NNN = next number; `series_ref` from `50-agents.md` in the curriculum).
2. Fill `agent.yaml` (human gate, tier, enterprise gap, data class, controls) and `schema.yaml` (fields + scorer).
3. Write `prompts/system.md` in lawyer language and keep `{{document}}` exactly once in `prompts/extract.md`.
4. Add documents to a corpus collection (`la corpus add-file`), create injection twins (`la corpus inject`).
5. Hand-label `evals/golden.jsonl` (use `la golden locate` for spans). Set `evals/thresholds.yaml` before running.
6. `la eval <agent> --provider … --model … --record` on at least two providers; commit `evals/cache`, `evals/results/`, `results.json`, `comparison.md`.
7. Write `failures.md` from `results.json` `misses[]`; add court cases to `governance/failure-atlas.md`.
8. `la validate <agent>` passes. `la governance sync`.

## Definition of done for any change under `agents/**`

`uv run la validate <agent>` passes and `uv run la eval <agent> --replay` passes. If you changed prompts or schema, the replay cache is stale: `--record` was run (with permission) and cache + results were committed. Paste the eval summary table in the PR description.

## Harness conventions

- pydantic v2 everywhere; argparse for the CLI; no new dependencies without updating `uv.lock`.
- The only network code is `egress.py` and `providers/*`. Nothing else imports httpx or the SDKs. A test enforces this.
- Every validate rule has a fixture agent under `tests/fixtures/agents/` that fails it.
- No LLM-as-judge. Scorers are deterministic. If a free-text field ever needs a judge, it needs a human-labelled calibration set first.
- Results are only published when thresholds and the canary pass. A failing run writes to `evals/results/` and exits non-zero.

## Governance cross-references

`governance/controls-library.md` holds C1–C6 with the code that enforces each. `governance/failure-atlas.md` holds real court failures by type T1–T7. Each agent's `failures.md` maps its modes to a T-type and a C-id and records observed failures with a doc id. IDs are permanent. `governance/agents-index.md` is generated.

## Series context

The 50-agent plan and the rep bar live in `../../hassaan-mallick/legal-ai-curriculum/50-agents.md` and `sprint-plan.md`. A rep agent may only be built after the flagship it reuses has shipped.

## What AI assistants (Claude Code, Cursor) must not do here

- Run live evals or `la run` against a paid provider without being asked.
- Fetch documents from anywhere other than SEC EDGAR or write synthetic ones without saying so in the file.
- "Fix" a failing canary or threshold by editing `golden.jsonl`, `thresholds.yaml`, or the injection templates.
- Write a model, provider, or vendor name into anything under `agents/`.
- Add a `tools` key, a tool definition, or function-calling text to any agent prompt.
- Mark anything as final, cleared, approved, or verified.
