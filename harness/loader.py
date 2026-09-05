"""Agent folder -> Agent object, with content hashes for provenance."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from harness.spec import AgentSpec, SchemaSpec, Thresholds

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
CORPUS_DIR = REPO_ROOT / "corpus"
GOVERNANCE_DIR = REPO_ROOT / "governance"
TEMPLATE_DIR = REPO_ROOT / "_template"
RUNS_DIR = REPO_ROOT / "runs"
GUARD_PREAMBLE = REPO_ROOT / "harness" / "prompts" / "guard_preamble.md"


def corpus_dir() -> Path:
    """LA_CORPUS_DIR overrides the repo corpus (used by the test fixtures)."""
    return Path(os.environ["LA_CORPUS_DIR"]) if os.environ.get("LA_CORPUS_DIR") else CORPUS_DIR


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Agent:
    dir: Path
    spec: AgentSpec
    schema: SchemaSpec
    thresholds: Thresholds | None
    system_prompt: str | None
    extract_prompt: str | None
    playbook: dict | None

    @property
    def folder(self) -> str:
        return self.dir.name

    @property
    def prompt_sha(self) -> str:
        return sha((self.system_prompt or "") + "\n---\n" + (self.extract_prompt or ""))

    @property
    def schema_sha(self) -> str:
        return sha((self.dir / "schema.yaml").read_text())

    @property
    def playbook_sha(self) -> str | None:
        p = self.dir / "playbook.yaml"
        return sha(p.read_text()) if p.exists() else None

    @property
    def golden_sha(self) -> str | None:
        p = self.dir / "evals" / "golden.jsonl"
        return sha(p.read_text()) if p.exists() else None

    @property
    def evals_dir(self) -> Path:
        return self.dir / "evals"


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def load_agent(agent_dir: Path) -> Agent:
    agent_dir = agent_dir.resolve()
    spec = AgentSpec.model_validate(yaml.safe_load((agent_dir / "agent.yaml").read_text()))
    schema = SchemaSpec.model_validate(yaml.safe_load((agent_dir / "schema.yaml").read_text()))
    th_path = agent_dir / "evals" / "thresholds.yaml"
    thresholds = Thresholds.model_validate(yaml.safe_load(th_path.read_text())) if th_path.exists() else None
    pb_path = agent_dir / "playbook.yaml"
    playbook = yaml.safe_load(pb_path.read_text()) if pb_path.exists() else None
    return Agent(dir=agent_dir, spec=spec, schema=schema, thresholds=thresholds,
                 system_prompt=_read(agent_dir / "prompts" / "system.md"),
                 extract_prompt=_read(agent_dir / "prompts" / "extract.md"),
                 playbook=playbook)


def all_agent_dirs() -> list[Path]:
    return sorted(p for p in AGENTS_DIR.iterdir() if p.is_dir() and (p / "agent.yaml").exists())
