"""One function per rule. Each returns a list of Findings (empty = pass).

Rule → control map (see AGENTS.md):
  V01 shape · V02 spec · V03 LLM-agnostic · V04 controls registry · V05 C1 envelope
  V06 C2 human gate · V07 C3 thresholds · V08 C4 golden + canaries · V09 C4 results
  V10 C5 forbidden tokens · V11 doc-as-data, no tools · V12 failures.md · V13 README
  V14 public docs only · V15 egress · V16 secrets · V17 series sequencing · V18 C6 routing
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from harness import MODEL_SENTINEL
from harness.document import ALLOWED_SOURCES, Manifest, sha256_file
from harness.loader import GOVERNANCE_DIR, TEMPLATE_DIR, corpus_dir, load_agent
from harness.routing import load_registry
from harness.schema_build import build_output_model, forbidden_tokens_in
from harness.spec import FORBIDDEN_DISPOSITIONS, SERIES_REFS, AgentSpec, SchemaSpec
from harness.validate import Finding

MODEL_NAME_RE = re.compile(
    r"\b(claude|sonnet|opus|haiku|gpt-?\d|o[1-9]-(?:mini|pro)|gemini|llama|mistral|mixtral|qwen|"
    r"deepseek|phi-\d|command-r|grok)\b", re.IGNORECASE)
SECRET_RES = [re.compile(p) for p in (
    r"sk-ant-[A-Za-z0-9_-]{10,}", r"\bsk-[A-Za-z0-9]{20,}", r"\bAKIA[0-9A-Z]{16}\b",
    r"Bearer [A-Za-z0-9._-]{20,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"\bsk-or-v1-[a-f0-9]{20,}", r"\bghp_[A-Za-z0-9]{30,}")]
PLACEHOLDER_RE = re.compile(r"\[(?:one sentence|Outcome-named|link|N|X/N|Failure mode|atlas type|"
                            r"concrete description|court case|controls-library ID|Who reviews|"
                            r"Setup steps|Architecture in|The hard boundary|source —|\$ per)[^\]]*\]")
TEXT_EXT = {".md", ".yaml", ".yml", ".txt", ".jsonl", ".json"}


def _files(agent_dir: Path):
    for p in agent_dir.rglob("*"):
        if p.is_file() and p.suffix in TEXT_EXT and "cache" not in p.parts and "results" not in p.parts:
            yield p


def _spec(agent_dir: Path) -> AgentSpec | None:
    try:
        return AgentSpec.model_validate(yaml.safe_load((agent_dir / "agent.yaml").read_text()))
    except Exception:
        return None


def _schema(agent_dir: Path) -> SchemaSpec | None:
    try:
        return SchemaSpec.model_validate(yaml.safe_load((agent_dir / "schema.yaml").read_text()))
    except Exception:
        return None


def _control_ids() -> set[str]:
    text = (GOVERNANCE_DIR / "controls-library.md").read_text()
    return set(re.findall(r"^\| (C\d+) \|", text, flags=re.MULTILINE))


# ---------------------------------------------------------------------------


def v01_shape(agent_dir: Path) -> list[Finding]:
    out = []
    name = agent_dir.name
    if not re.match(r"^\d{3}-[a-z0-9]+(-[a-z0-9]+)*$", name):
        out.append(Finding("fail", "V01", "shape", name, "folder must be NNN-slug"))
    required = ["agent.yaml", "schema.yaml", "README.md", "failures.md",
                "evals/golden.jsonl", "evals/thresholds.yaml"]
    spec = _spec(agent_dir)
    if spec and spec.runner == "llm_extract":
        required += ["prompts/system.md", "prompts/extract.md"]
    for rel in required:
        if not (agent_dir / rel).exists():
            out.append(Finding("fail", "V01", "shape", rel, "required file missing"))
    if spec and spec.folder_name != name:
        out.append(Finding("fail", "V01", "shape", "agent.yaml",
                           f"id/slug {spec.folder_name!r} does not match folder {name!r}"))
    return out


def v02_spec(agent_dir: Path) -> list[Finding]:
    p = agent_dir / "agent.yaml"
    if not p.exists():
        return []
    try:
        AgentSpec.model_validate(yaml.safe_load(p.read_text()))
    except Exception as exc:
        return [Finding("fail", "V02", "shape", "agent.yaml", str(exc).replace("\n", " ")[:600])]
    return []


def v03_llm_agnostic(agent_dir: Path) -> list[Finding]:
    out = []
    raw = yaml.safe_load((agent_dir / "agent.yaml").read_text()) if (agent_dir / "agent.yaml").exists() else {}
    if raw.get("model") != MODEL_SENTINEL:
        out.append(Finding("fail", "V03", "agnostic", "agent.yaml",
                           f"model must be {MODEL_SENTINEL!r}"))
    for p in _files(agent_dir):
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if MODEL_NAME_RE.search(line):
                out.append(Finding("fail", "V03", "agnostic", f"{p.relative_to(agent_dir)}:{i}",
                                   f"model name in agent files: {line.strip()[:80]!r}"))
    return out


def v04_controls(agent_dir: Path) -> list[Finding]:
    spec = _spec(agent_dir)
    if not spec:
        return []
    known = _control_ids()
    out = [Finding("fail", "V04", c, "agent.yaml", f"{c} not in governance/controls-library.md")
           for c in spec.controls if c not in known]
    return out


def v05_envelope(agent_dir: Path) -> list[Finding]:
    spec, schema = _spec(agent_dir), _schema(agent_dir)
    if not schema:
        p = agent_dir / "schema.yaml"
        if p.exists():
            try:
                SchemaSpec.model_validate(yaml.safe_load(p.read_text()))
            except Exception as exc:
                return [Finding("fail", "V05", "C1", "schema.yaml", str(exc).replace("\n", " ")[:400])]
        return []
    try:
        build_output_model(schema, professional=bool(spec and spec.obligation.professional))
    except Exception as exc:
        return [Finding("fail", "V05", "C1", "schema.yaml", f"does not compile: {exc}")]
    return []


def v06_human_gate(agent_dir: Path) -> list[Finding]:
    spec = _spec(agent_dir)
    if not spec:
        return []
    out = []
    for k in ("role", "point", "why"):
        if len(getattr(spec.human_gate, k).strip()) < 10 and k != "role":
            out.append(Finding("fail", "V06", "C2", "agent.yaml", f"human_gate.{k} too short"))
    if len(spec.enterprise_gap) < 40:
        out.append(Finding("fail", "V06", "C2", "agent.yaml", "enterprise_gap must be a real sentence"))
    return out


def v07_thresholds(agent_dir: Path) -> list[Finding]:
    spec, schema = _spec(agent_dir), _schema(agent_dir)
    if not spec or not schema:
        return []
    out = []
    for k in spec.gates.confidence.per_field:
        if k not in schema.fields:
            out.append(Finding("fail", "V07", "C3", "agent.yaml", f"per_field {k!r} not in schema"))
    th = agent_dir / "evals" / "thresholds.yaml"
    if th.exists():
        try:
            from harness.spec import Thresholds

            t = Thresholds.model_validate(yaml.safe_load(th.read_text()))
            for k in t.per_field:
                if k not in schema.fields:
                    out.append(Finding("fail", "V07", "C3", "evals/thresholds.yaml",
                                       f"per_field {k!r} not in schema"))
        except Exception as exc:
            out.append(Finding("fail", "V07", "C3", "evals/thresholds.yaml", str(exc)[:300]))
    return out


def v08_golden(agent_dir: Path) -> list[Finding]:
    spec, schema = _spec(agent_dir), _schema(agent_dir)
    p = agent_dir / "evals" / "golden.jsonl"
    if not spec or not schema or not p.exists():
        return []
    from harness.evals.golden import GoldenCase

    out = []
    lines = [ln for ln in p.read_text().splitlines() if ln.strip()]
    if len(lines) < spec.eval.min_docs:
        out.append(Finding("fail", "V08", "C4", "evals/golden.jsonl",
                           f"{len(lines)} docs < min_docs {spec.eval.min_docs}"))
    injections = 0
    for i, ln in enumerate(lines, 1):
        try:
            case = GoldenCase.model_validate(json.loads(ln))
        except Exception as exc:
            out.append(Finding("fail", "V08", "C4", f"evals/golden.jsonl:{i}", str(exc)[:200]))
            continue
        if case.is_draft:
            out.append(Finding("warn", "V08", "C4", f"evals/golden.jsonl:{i}",
                               f"{case.doc_id}: draft labels, not yet checked by a person"))
        if case.kind == "injection":
            injections += 1
            if not case.canary or not case.canary.tokens:
                out.append(Finding("fail", "V08", "C4", f"evals/golden.jsonl:{i}",
                                   "injection case needs canary.tokens"))
        if isinstance(case.expected, dict):
            unknown = set(case.expected) - set(schema.fields) - set(schema.document_fields) - {"findings"}
            if unknown:
                out.append(Finding("fail", "V08", "C4", f"evals/golden.jsonl:{i}",
                                   f"expected keys not in schema: {sorted(unknown)}"))
        found = None
        for coll in spec.input.corpus:
            m = Manifest(corpus_dir() / coll / "manifest.json")
            if case.doc_id in m.entries:
                found = (m, m.entries[case.doc_id])
                break
        if not found:
            out.append(Finding("fail", "V08", "C4", f"evals/golden.jsonl:{i}",
                               f"doc_id {case.doc_id!r} not in corpus manifests {spec.input.corpus}"))
        else:
            m, e = found
            fp = m.collection_dir / e.file
            if not fp.exists() or sha256_file(fp) != e.sha256:
                out.append(Finding("fail", "V08", "C4", f"evals/golden.jsonl:{i}",
                                   f"{case.doc_id}: corpus file missing or sha mismatch"))
    if injections < spec.eval.min_injection_docs:
        out.append(Finding("fail", "V08", "C4", "evals/golden.jsonl",
                           f"{injections} injection canary docs < {spec.eval.min_injection_docs}"))
    return out


def v09_results(agent_dir: Path) -> list[Finding]:
    p = agent_dir / "evals" / "results.json"
    if not p.exists():
        return [Finding("warn", "V09", "C4", "evals/results.json",
                        "no committed results yet — run `la eval <agent> --record`")]
    try:
        r = json.loads(p.read_text())
        agent = load_agent(agent_dir)
    except Exception as exc:
        return [Finding("fail", "V09", "C4", "evals/results.json", f"unreadable: {exc}")]
    out = []
    if not r.get("thresholds_met"):
        out.append(Finding("fail", "V09", "C4", "evals/results.json", "thresholds_met is false"))
    if not (r.get("canary") or {}).get("pass", False):
        out.append(Finding("fail", "V09", "C4", "evals/results.json", "canary did not pass"))
    for key, cur in (("prompt_sha", agent.prompt_sha), ("schema_sha", agent.schema_sha),
                     ("golden_sha", agent.golden_sha)):
        if r.get(key) and cur and r[key] != cur:
            out.append(Finding("warn", "V09", "C4", "evals/results.json",
                               f"stale: {key} changed since the committed run"))
    return out


def v10_forbidden(agent_dir: Path) -> list[Finding]:
    spec = _spec(agent_dir)
    if not spec or not spec.obligation.professional:
        return []
    out = []
    for rel in ("schema.yaml", "prompts/system.md", "prompts/extract.md"):
        p = agent_dir / rel
        if p.exists():
            hits = forbidden_tokens_in(p.read_text())
            if hits:
                out.append(Finding("fail", "V10", "C5", rel, f"forbidden disposition tokens: {hits}"))
    readme = agent_dir / "README.md"
    if readme.exists():
        m = re.search(r"## Results(.*?)(?:\n## |\Z)", readme.read_text(), re.DOTALL)
        if m:
            hits = forbidden_tokens_in(m.group(1))
            if hits:
                out.append(Finding("fail", "V10", "C5", "README.md#Results",
                                   f"forbidden disposition tokens: {hits}"))
    return out


def v11_doc_as_data(agent_dir: Path) -> list[Finding]:
    spec = _spec(agent_dir)
    out = []
    raw = yaml.safe_load((agent_dir / "agent.yaml").read_text()) if (agent_dir / "agent.yaml").exists() else {}
    if isinstance(raw, dict) and "tools" in raw:
        out.append(Finding("fail", "V11", "safety", "agent.yaml", "`tools` is not allowed"))
    if spec and spec.runner == "llm_extract":
        ex = agent_dir / "prompts" / "extract.md"
        if ex.exists():
            n = ex.read_text().count("{{document}}")
            if n != 1:
                out.append(Finding("fail", "V11", "safety", "prompts/extract.md",
                                   f"{{{{document}}}} must appear exactly once (found {n})"))
        for rel in ("prompts/system.md", "prompts/extract.md"):
            p = agent_dir / rel
            if p.exists() and re.search(r'"tools"\s*:|\btool_use\b|function_call', p.read_text()):
                out.append(Finding("fail", "V11", "safety", rel, "tool/function-call text in prompt"))
    return out


def v12_failures(agent_dir: Path) -> list[Finding]:
    p = agent_dir / "failures.md"
    if not p.exists():
        return []
    text = p.read_text()
    out = []
    if text.strip() == (TEMPLATE_DIR / "failures.md").read_text().strip():
        return [Finding("fail", "V12", "bar", "failures.md", "still the template")]
    sections = re.split(r"^## \d+\.", text, flags=re.MULTILINE)[1:]
    if len(sections) < 3:
        out.append(Finding("fail", "V12", "bar", "failures.md", f"{len(sections)} failure modes < 3"))
    for i, s in enumerate(sections, 1):
        if not re.search(r"\bT[1-7]\b", s):
            out.append(Finding("fail", "V12", "bar", "failures.md", f"mode {i}: no atlas type T1–T7"))
        if not re.search(r"\bC\d+\b", s):
            out.append(Finding("fail", "V12", "bar", "failures.md", f"mode {i}: no control id"))
    has_doc_id = re.search(r"doc[_ -]?id|doc #|`[a-z0-9-]+-\d{3,4}`", text, re.IGNORECASE)
    if not re.search(r"observed", text, re.IGNORECASE) or not has_doc_id:
        out.append(Finding("fail", "V12", "bar", "failures.md",
                           "need ≥1 mode marked 'observed' with a doc id"))
    m = re.search(r"## What this agent must never be trusted to do\s*(.*)", text, re.DOTALL)
    if not m or len(m.group(1).strip()) < 40:
        out.append(Finding("fail", "V12", "bar", "failures.md", "hard-boundary section empty"))
    return out


def v13_readme(agent_dir: Path) -> list[Finding]:
    p = agent_dir / "README.md"
    if not p.exists():
        return []
    text = p.read_text()
    out = []
    if text.strip() == (TEMPLATE_DIR / "README.md").read_text().strip():
        return [Finding("fail", "V13", "bar", "README.md", "still the template")]
    for h in ("## The human gate", "## Results", "## Run it yourself"):
        if h not in text:
            out.append(Finding("fail", "V13", "bar", "README.md", f"missing section {h!r}"))
    for m in PLACEHOLDER_RE.finditer(text):
        out.append(Finding("fail", "V13", "bar", "README.md", f"template placeholder left: {m.group(0)[:50]}"))
    return out


def v14_corpus_policy(agent_dir: Path) -> list[Finding]:
    spec = _spec(agent_dir)
    if not spec:
        return []
    out = []
    for coll in spec.input.corpus:
        mp = corpus_dir() / coll / "manifest.json"
        if not mp.exists():
            out.append(Finding("warn", "V14", "docs", f"corpus/{coll}", "no manifest.json yet"))
            continue
        m = Manifest(mp)
        for prob in m.verify():
            out.append(Finding("fail", "V14", "docs", f"corpus/{coll}", prob))
        for e in m.entries.values():
            if e.source not in ALLOWED_SOURCES:
                out.append(Finding("fail", "V14", "docs", f"corpus/{coll}/{e.doc_id}",
                                   f"source {e.source!r} not public/synthetic"))
    return out


def v15_egress(agent_dir: Path) -> list[Finding]:
    spec = _spec(agent_dir)
    if not spec:
        return []
    out = []
    if spec.runner != "llm_extract" and spec.egress.document_may_leave:
        out.append(Finding("fail", "V15", "egress", "agent.yaml",
                           "no-LLM runner must set document_may_leave: false"))
    return out


def v16_secrets(agent_dir: Path) -> list[Finding]:
    out = []
    for p in agent_dir.rglob("*"):
        if p.is_file() and p.stat().st_size < 2_000_000:
            text = p.read_text(errors="ignore")
            for rx in SECRET_RES:
                if rx.search(text):
                    out.append(Finding("fail", "V16", "secrets", str(p.relative_to(agent_dir)),
                                       f"looks like a secret ({rx.pattern[:20]}…)"))
                    break
    return out


def v17_series(agent_dir: Path) -> list[Finding]:
    spec = _spec(agent_dir)
    if not spec:
        return []
    if spec.series_ref not in SERIES_REFS:
        return [Finding("fail", "V17", "series", "agent.yaml", f"bad series_ref {spec.series_ref}")]
    idx = GOVERNANCE_DIR / "agents-index.md"
    if spec.series_ref.startswith("R") and idx.exists():
        # a rep may only ship after its flagship; warn only until the index is authoritative
        pass
    return []


def v18_routing(agent_dir: Path) -> list[Finding]:
    spec = _spec(agent_dir)
    if not spec:
        return []
    out = []
    reg = load_registry()
    for s in spec.stages:
        if s.retention == "zdr" and not any(e.is_zdr for e in reg.values()):
            out.append(Finding("warn", "V18", "C6", "agent.yaml",
                               f"stage {s.name} requires ZDR but no registry endpoint is verified ZDR"))
    if spec.data_class in ("confidential", "privileged") and spec.egress.document_may_leave:
        if not any(s.retention in ("zdr", "local") for s in spec.stages):
            out.append(Finding("fail", "V18", "C6", "agent.yaml",
                               "confidential/privileged agent has no zdr|local stage"))
    for tok in FORBIDDEN_DISPOSITIONS:
        if tok in str(spec.data_class):
            out.append(Finding("fail", "V18", "C6", "agent.yaml", "impossible data_class"))
    return out


ALL_RULES = [v01_shape, v02_spec, v03_llm_agnostic, v04_controls, v05_envelope, v06_human_gate,
             v07_thresholds, v08_golden, v09_results, v10_forbidden, v11_doc_as_data,
             v12_failures, v13_readme, v14_corpus_policy, v15_egress, v16_secrets, v17_series,
             v18_routing]
