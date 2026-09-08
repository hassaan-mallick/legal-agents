# Corpus

Public and synthetic documents only. Never a client document, never a real matter. Every collection has a `manifest.json` with a sha256 per file; `la corpus verify` recomputes them and `la validate` refuses an agent whose golden set points at a file that has changed.

| Collection | Source | Licence | Notes |
|---|---|---|---|
| `edgar-nda/` | SEC EDGAR exhibits (EX-10.x confidentiality / non-disclosure agreements) | US public record | Fetch with a real contact in `EDGAR_USER_AGENT` (SEC fair-access rules, ≤10 req/s). Convert to `.txt`, keep the accession number and URL in the manifest. |
| `recap-briefs/` | Filed federal court documents via CourtListener RECAP | US public record | `la corpus fetch-recap`; the PDF is kept locally, the text is committed with the source URL. |
| `contract-nli/` | ContractNLI NDAs (Stanford) | CC BY 4.0 | `la corpus import-contract-nli`; draft labels only until a person checks them. |
| `synthetic/` | Written or generated here | CC0 | Sparse NDAs, synthetic briefs (`la corpus make-briefs`), citation pool. Every synthetic doc says so in its first lines. |
| `injections/` | Templates | CC0 | Prompt-injection paragraphs with a `{{CANARY}}` slot. `la corpus inject` writes a twin document and records the canary in the manifest. |

## Adding a document

```bash
uv run la corpus add-file synthetic path/to/doc.md --source synthetic --doc-id my-doc-001
uv run la corpus inject synthetic --doc my-doc-001 --template ignore-instructions.md
uv run la corpus verify
```

`source` must be one of `SEC EDGAR`, `public court filing`, `open dataset` (a published dataset under an open licence, recorded in the manifest), `synthetic`. Anything else fails V14.
