# Legal Agents

Legal AI agents built in public by [Hassaan Mallick](https://mallick.tech), a former lawyer building AI-native law firm infrastructure. Every agent here is published with its full definition, a test set with known right answers, measured results, and documented failure modes.

**The rule that governs everything in this repo: no quote, no claim.** Every extraction cites its source and the harness locates the quote in the document. Every agent has a named human gate. Every agent ships with the ways it fails, backed by real court cases where those failures have actually happened.

**Agents are LLM-agnostic.** An agent is plain files: a spec, a schema, prompts, a corpus, a hand-labelled golden set, and a failures file. No model name appears inside one. The same agent runs on any endpoint in the provider registry, and the eval reports quality per model and per route, so "which model, and does zero data retention cost accuracy?" is a measured number rather than an opinion.

**Governance is code.** The six controls in [`governance/controls-library.md`](governance/controls-library.md) are code paths in the harness. `la validate` refuses an agent that does not meet the bar; `la run` and `la eval` refuse to start on one that fails validation. `la run` also refuses an unmeasured agent, one with draft labels or no committed results. The only exception is explicit: `la run --unmeasured` waives the C4 evidence rules, prints what it waived, and records the waiver in `run.json`. (Until 2026-09-09 both commands waived those rules silently, so the gate described here did not fire. Found by inspection; closed.)

## What's here

- [`agents/`](agents/) — one folder per agent: `agent.yaml`, `schema.yaml`, `prompts/`, `evals/` (golden set, committed results, cross-model comparison), `README.md`, `failures.md`
- [`harness/`](harness/) — the Python package and the `la` command: validation, ZDR-aware routing, provider adapters, quote verification, review queue, evals
- [`governance/`](governance/) — the controls library, the failure atlas of real court cases, the framework in progress, and the generated agents index
- [`corpus/`](corpus/) — public (SEC EDGAR) and synthetic documents with sha256 manifests; never client data
- [`AGENTS.md`](AGENTS.md) — the working rules for anyone, human or AI assistant, editing this repo

## Agents

| # | Agent | Series | Model calls | Status |
|---|---|---|---|---|
| 001 | [NDA Review](agents/001-nda-review/) — 12 terms per agreement, every one quoted | F1 | yes, any provider | scaffolded; golden set pending |
| 002 | [Citation Verifier](agents/002-citation-verifier/) — does that case exist, and is it the case you named? | R11 | none | measured |

## Ground rules

1. **Public and synthetic documents only.** SEC EDGAR contracts, public court filings, generated test data. Never client documents, ever.
2. **Agents flag; they never clear.** Conflicts, privilege, sanctions, filings: anywhere a professional obligation sits, the agent escalates to a named human.
3. **Nothing ships without a test set.** 20 documents minimum, known right answers, injection canaries, results published, including the misses.
4. **Every agent declares its deployment tier** and states plainly what would have to change to run inside a firm's environment.
5. **Confidential text only goes to verified zero-retention endpoints.** The registry says which those are, and "unverified" is the default.

## Run it

```bash
brew install uv                      # or see https://docs.astral.sh/uv/
uv sync --all-extras --dev
uv run la validate --all
uv run la eval agents/002-citation-verifier --replay
uv run la run agents/001-nda-review --docs synthetic --provider <registry name> --model <model id>
```

Each agent folder is self-contained. Read the `failures.md` before you read anything else. These are reference implementations for learning and adaptation, not production systems.
