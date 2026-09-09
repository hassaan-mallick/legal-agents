"""Every rule has a fixture that fails it."""

from pathlib import Path

import pytest
import yaml

from harness.validate import has_failures, run_rules

FIX = Path(__file__).resolve().parent / "fixtures" / "agents"


def rules_hit(agent_dir: Path, level="fail") -> set[str]:
    return {f.rule for f in run_rules(agent_dir) if f.level == level}


def test_compliant_fixture_only_warns_on_missing_results():
    fails = rules_hit(FIX / "900-compliant")
    assert fails == set(), fails
    assert "V09" in rules_hit(FIX / "900-compliant", level="warn")


def _mutate(compliant_agent: Path, **spec_overrides):
    raw = yaml.safe_load((compliant_agent / "agent.yaml").read_text())
    raw.update(spec_overrides)
    (compliant_agent / "agent.yaml").write_text(yaml.safe_dump(raw))


def test_v01_missing_file(compliant_agent):
    (compliant_agent / "failures.md").unlink()
    assert "V01" in rules_hit(compliant_agent)


def test_v02_bad_spec(compliant_agent):
    _mutate(compliant_agent, tier=7)
    assert "V02" in rules_hit(compliant_agent)


def test_v03_model_name_in_prompt(compliant_agent):
    (compliant_agent / "prompts" / "system.md").write_text("You are claude-opus, extract things.")
    assert "V03" in rules_hit(compliant_agent)


def test_v03_model_not_sentinel(compliant_agent):
    _mutate(compliant_agent, model="some-model-id")
    hits = rules_hit(compliant_agent)
    assert "V03" in hits and "V02" in hits


def test_v04_unknown_control(compliant_agent):
    _mutate(compliant_agent, controls=["C1", "C2", "C3", "C4", "C6", "C99"])
    assert "V04" in rules_hit(compliant_agent)


def test_v05_schema_does_not_compile(compliant_agent):
    (compliant_agent / "schema.yaml").write_text("fields:\n  bad:\n    type: enum\n")
    assert "V05" in rules_hit(compliant_agent)


def test_v06_enterprise_gap_too_short(compliant_agent):
    _mutate(compliant_agent, enterprise_gap="tbd")
    hits = rules_hit(compliant_agent)
    assert "V02" in hits or "V06" in hits


def test_v07_threshold_unknown_field(compliant_agent):
    (compliant_agent / "evals" / "thresholds.yaml").write_text(
        "overall: {field_accuracy: 0.8, quote_exact_rate: 0.9, presence_accuracy: 0.9, escalation_rate_max: 0.3}\n"
        "per_field: {nope: 0.9}\n")
    assert "V07" in rules_hit(compliant_agent)


def test_v08_too_few_docs_and_no_canary(compliant_agent):
    lines = (compliant_agent / "evals" / "golden.jsonl").read_text().splitlines()
    (compliant_agent / "evals" / "golden.jsonl").write_text(lines[0] + "\n")
    assert "V08" in rules_hit(compliant_agent)


def test_v09_results_failing(compliant_agent):
    (compliant_agent / "evals" / "results.json").write_text('{"thresholds_met": false, "canary": {"pass": true}}')
    assert "V09" in rules_hit(compliant_agent)


def test_v10_forbidden_token_in_prompt(compliant_agent):
    _mutate(compliant_agent, obligation={"professional": True, "domain": "filing"},
            controls=["C1", "C2", "C3", "C4", "C5", "C6"])
    (compliant_agent / "prompts" / "system.md").write_text("Mark the document as cleared when done.")
    assert "V10" in rules_hit(compliant_agent)


def test_v11_document_placeholder_twice(compliant_agent):
    (compliant_agent / "prompts" / "extract.md").write_text("{{document}}\n{{document}}")
    assert "V11" in rules_hit(compliant_agent)


def test_v11_tools_key(compliant_agent):
    _mutate(compliant_agent, tools=[{"name": "search"}])
    hits = rules_hit(compliant_agent)
    assert "V11" in hits or "V02" in hits


def test_v12_template_failures(compliant_agent):
    from harness.loader import TEMPLATE_DIR

    (compliant_agent / "failures.md").write_text((TEMPLATE_DIR / "failures.md").read_text())
    assert "V12" in rules_hit(compliant_agent)


def test_v13_template_readme(compliant_agent):
    from harness.loader import TEMPLATE_DIR

    (compliant_agent / "README.md").write_text((TEMPLATE_DIR / "README.md").read_text())
    assert "V13" in rules_hit(compliant_agent)


def test_v15_no_llm_runner_must_not_leak(compliant_agent):
    _mutate(compliant_agent, runner="citations",
            egress={"allow": ["www.courtlistener.com"], "document_may_leave": True})
    hits = rules_hit(compliant_agent)
    assert "V02" in hits or "V15" in hits


def test_v16_secret_in_folder(compliant_agent):
    # built at runtime so `la scan` does not flag this source file
    (compliant_agent / "notes.md").write_text("key: " + "sk-ant-" + "abcdefghij" * 4)
    assert "V16" in rules_hit(compliant_agent)


def test_v18_confidential_without_zdr_stage(compliant_agent):
    _mutate(compliant_agent, data_class="privileged", stages=[])
    hits = rules_hit(compliant_agent)
    assert "V02" in hits or "V18" in hits


@pytest.mark.parametrize("agent", ["001-nda-review", "002-citation-verifier"])
def test_real_agents_load(agent):
    from harness.loader import AGENTS_DIR, load_agent

    a = load_agent(AGENTS_DIR / agent)
    assert a.spec.model == "provider_chosen_at_runtime"
    findings = run_rules(AGENTS_DIR / agent)
    # never a model-name, secrets, or C5 failure in the real agents
    assert not {f.rule for f in findings if f.level == "fail"} & {"V03", "V10", "V11", "V16"}
    assert isinstance(has_failures(findings), bool)


# --------------------------------------------------------------- the gate itself
# Until 2026-09-09 `la run` and `la eval` silently waived V08/V09/V12, so an agent
# with no golden set or failing results still ran. These pin the closed gate.


def _break_v08(agent_dir: Path) -> None:
    lines = (agent_dir / "evals" / "golden.jsonl").read_text().splitlines()
    (agent_dir / "evals" / "golden.jsonl").write_text(lines[0] + "\n")


def test_run_gate_refuses_agent_failing_evidence_rules(compliant_agent, capsys):
    from harness.cli import _must_validate

    _break_v08(compliant_agent)
    with pytest.raises(SystemExit, match="refusing to run"):
        _must_validate(compliant_agent)


def test_run_gate_refuses_unmeasured_agent_on_warnings_alone(compliant_agent):
    from harness.cli import _must_validate

    # the compliant fixture has no results.json: V09 warns, nothing fails
    assert _must_validate(compliant_agent) == []
    with pytest.raises(SystemExit, match="unmeasured"):
        _must_validate(compliant_agent, require_measured=True)


def test_run_gate_waives_only_by_explicit_flag_and_returns_waiver(compliant_agent, capsys):
    from harness.cli import EVIDENCE_RULES, _must_validate

    _break_v08(compliant_agent)
    waived = _must_validate(compliant_agent, waive=EVIDENCE_RULES, require_measured=True)
    assert {f.rule for f in waived} == {"V08", "V09"}
    assert "WAIVED" in capsys.readouterr().out


def test_eval_gate_waives_results_but_not_golden_set(compliant_agent):
    from harness.cli import _must_validate

    (compliant_agent / "evals" / "results.json").write_text(
        '{"thresholds_met": false, "canary": {"pass": true}}')
    waived = _must_validate(compliant_agent, waive=("V09",))
    assert {f.rule for f in waived} == {"V09"}
    _break_v08(compliant_agent)
    with pytest.raises(SystemExit):
        _must_validate(compliant_agent, waive=("V09",))


def test_waiver_never_hides_a_non_evidence_failure(compliant_agent):
    from harness.cli import EVIDENCE_RULES, _must_validate

    (compliant_agent / "failures.md").unlink()  # V01 shape failure
    with pytest.raises(SystemExit):
        _must_validate(compliant_agent, waive=EVIDENCE_RULES)
