"""`la validate` — the enforcement heart. Every rule maps to a control or a
safety goal; see rules.py. Fail = the agent cannot run or eval."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Level = Literal["fail", "warn", "ok"]


@dataclass
class Finding:
    level: Level
    rule: str
    control: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():4} {self.rule} [{self.control}] {self.path}: {self.message}"


def run_rules(agent_dir: Path) -> list[Finding]:
    from harness.validate.rules import ALL_RULES

    findings: list[Finding] = []
    for rule in ALL_RULES:
        try:
            findings.extend(rule(agent_dir))
        except Exception as exc:  # a crashing rule is a fail, never silence
            findings.append(Finding("fail", rule.__name__.upper(), "harness", str(agent_dir),
                                    f"rule crashed: {exc.__class__.__name__}: {exc}"))
    return findings


def has_failures(findings: list[Finding]) -> bool:
    return any(f.level == "fail" for f in findings)


def render(findings: list[Finding]) -> str:
    if not findings:
        return "ok — no findings"
    width = max(len(f.rule) for f in findings)
    lines = []
    for f in sorted(findings, key=lambda f: (f.level != "fail", f.rule)):
        lines.append(f"{f.level.upper():4} {f.rule:<{width}} [{f.control:<3}] {f.path}: {f.message}")
    fails = sum(f.level == "fail" for f in findings)
    warns = sum(f.level == "warn" for f in findings)
    lines.append(f"\n{fails} fail, {warns} warn")
    return "\n".join(lines)
