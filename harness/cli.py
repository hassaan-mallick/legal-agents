"""`la` — the legal-agents command line.

  la validate <agent_dir> | --all
  la run <agent_dir> --docs <collection|doc_id...> --provider X --model Y [--route R] [--effort E]
  la eval <agent_dir> [--provider X --model Y] [--route R] [--record | --replay] [--baseline path]
  la compare <agent_dir>
  la corpus verify | add-file | inject | make-briefs
  la golden locate --doc <doc_id> --quote "..."
  la scan
  la governance sync
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import sys
from pathlib import Path

from harness.loader import (
    AGENTS_DIR,
    GOVERNANCE_DIR,
    REPO_ROOT,
    RUNS_DIR,
    Agent,
    all_agent_dirs,
    corpus_dir,
    load_agent,
)
from harness.validate import has_failures, render, run_rules


def _agent_dir(arg: str) -> Path:
    p = Path(arg)
    if not p.exists():
        p = AGENTS_DIR / arg
    if not (p / "agent.yaml").exists():
        raise SystemExit(f"not an agent folder: {arg}")
    return p.resolve()


def cmd_golden_draft(args) -> int:
    """Turn a run's findings into draft golden lines. A person must check every line
    before it counts: labelled_by stays 'draft' until they replace it with their name."""
    agent = load_agent(_agent_dir(args.agent))
    runs = sorted((RUNS_DIR / agent.folder).glob("*"))
    if not runs:
        raise SystemExit("no runs yet; `la run` first")
    run_dir = Path(args.run) if args.run and args.run != "latest" else runs[-1]
    out = Path(args.out) if args.out else agent.evals_dir / "golden-draft.jsonl"
    lines = []
    for item_path in sorted(run_dir.glob("*.json")):
        if item_path.name in ("run.json",) or item_path.name.endswith(".redaction-map.json"):
            continue
        item = json.loads(item_path.read_text())
        if item.get("findings") is not None:
            expected = {"findings": [
                {"citation": f["citation"], "verdict": f["verdict"], "written_name": f["written_name"]}
                for f in item["findings"] if f["verdict"] != "SKIPPED"]}
        else:
            expected = {}
            for name, f in item["fields"].items():
                loc = f.get("locator")
                expected[name] = {"present": f["present"], "value": f["value"], "quote": f["quote"],
                                  "span": [loc["char_start"], loc["char_end"]] if loc else None}
        lines.append({"doc_id": item["doc_id"], "kind": "standard", "expected": expected,
                      "labelled_by": "draft: harness output, NOT yet checked by a person",
                      "labelled_on": dt.date.today().isoformat(),
                      "notes": "Check every line. Replace labelled_by with your name when done."})
    out.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    print(f"wrote {len(lines)} draft cases to {out.relative_to(REPO_ROOT)}")
    print("these are NOT labels until a person checks every line and signs labelled_by")
    return 0


# --------------------------------------------------------------------------- validate


def cmd_validate(args) -> int:
    dirs = all_agent_dirs() if args.all else [_agent_dir(args.agent)]
    rc = 0
    for d in dirs:
        findings = run_rules(d)
        print(f"== {d.name}")
        print(render(findings))
        print()
        if has_failures(findings):
            rc = 1
    return rc


def _must_validate(agent_dir: Path, *, allow_missing_results: bool) -> None:
    findings = run_rules(agent_dir)
    blocking = [f for f in findings if f.level == "fail"
                and not (allow_missing_results and f.rule in ("V08", "V09", "V12"))]
    if blocking:
        print(render(blocking))
        raise SystemExit(f"{agent_dir.name}: validate failed; refusing to run")


# --------------------------------------------------------------------------- docs


def _load_docs(agent: Agent, selectors: list[str]):
    from harness.document import Manifest

    docs = []
    for sel in selectors:
        coll_path = corpus_dir() / sel / "manifest.json"
        if coll_path.exists():
            if sel not in agent.spec.input.corpus:
                raise SystemExit(f"collection {sel!r} not allowed by agent input.corpus")
            m = Manifest(coll_path)
            docs += [m.load(d) for d in m.entries]
            continue
        found = False
        for coll in agent.spec.input.corpus:
            m = Manifest(corpus_dir() / coll / "manifest.json")
            if sel in m.entries:
                docs.append(m.load(sel))
                found = True
                break
        if not found:
            raise SystemExit(f"{sel!r} is neither a collection nor a doc_id in {agent.spec.input.corpus}")
    return docs


# --------------------------------------------------------------------------- run


def cmd_run(args) -> int:
    agent_dir = _agent_dir(args.agent)
    _must_validate(agent_dir, allow_missing_results=True)
    agent = load_agent(agent_dir)
    docs = _load_docs(agent, args.docs)
    from harness.egress import EgressLog
    from harness.review import RunWriter

    writer = RunWriter(RUNS_DIR, agent.folder)
    route = args.route or os.environ.get("LA_ROUTE") or "best-quality"
    meta = {"agent": agent.folder, "route": route, "data_class": agent.spec.data_class,
            "prompt_sha": agent.prompt_sha, "schema_sha": agent.schema_sha,
            "playbook_sha": agent.playbook_sha, "reviewer": RunWriter.reviewer(),
            "started": dt.datetime.now(dt.UTC).isoformat()}
    if agent.spec.runner == "llm_extract":
        from harness.providers.base import resolve_provider
        from harness.runners.llm_extract import run_document

        egress = EgressLog()
        provider = resolve_provider(args.provider, args.model, egress=egress,
                                    usage_path=writer.dir / "usage.jsonl")
        egress.allow.add(provider.endpoint.host)
        meta.update(provider=provider.name, model=provider.model,
                    endpoint=provider.endpoint.describe())
        for doc in docs:
            r = run_document(agent, doc, provider, route=route, effort=args.effort, writer=writer)
            print(f"{doc.doc_id:<28} {r.item.status:<15} {'; '.join(r.item.escalation_reasons)[:80]}")
        egress.write(writer.dir / "egress.jsonl")
    elif agent.spec.runner == "citations":
        from harness.runners.citations.runner import make_resolver, run_document

        egress = EgressLog(allow=set(agent.spec.egress.allow))
        resolver = make_resolver(agent, cache_dir=agent.evals_dir / "cache" / "courtlistener",
                                 offline=args.replay, egress=egress,
                                 backend=args.backend or os.environ.get("LA_CL_BACKEND", "auto"))
        meta.update(provider="none", model="none",
                    endpoint=f"courtlistener {resolver.backend} (citation triples only)")
        from harness.runners.citations.resolve import RateLimited

        done = 0
        try:
            for doc in docs:
                item, _ = run_document(agent, doc, resolver, writer=writer)
                done += 1
                print(f"{doc.doc_id:<28} {item.status:<15} {'; '.join(item.escalation_reasons)[:80]}",
                      flush=True)
        except RateLimited as exc:
            egress.write(writer.dir / "egress.jsonl")
            writer.write_run({**meta, "provider": "none", "stopped": str(exc), "docs_done": done})
            print(f"\nstopped after {done}/{len(docs)} documents: {exc}. Everything resolved so far is "
                  "cached; re-run the same command after the wait and it resumes at full speed.")
            return 3
        egress.write(writer.dir / "egress.jsonl")
    writer.write_run(meta)
    print(f"\nreview queue: {writer.dir / 'review-queue.md'}")
    return 0


# --------------------------------------------------------------------------- eval


def cmd_eval(args) -> int:
    dirs = all_agent_dirs() if args.all else [_agent_dir(args.agent)]
    rc = 0
    for d in dirs:
        rc |= _eval_one(d, args)
    return rc


def _eval_one(agent_dir: Path, args) -> int:
    from harness.evals.compare import build_comparison, regressions
    from harness.evals.golden import load_golden
    from harness.evals.runner import (
        _canary_check,
        aggregate,
        load_case_doc,
        score_extraction_item,
        score_findings_item,
        write_results,
    )

    _must_validate(agent_dir, allow_missing_results=True)
    agent = load_agent(agent_dir)
    gpath = agent.evals_dir / "golden.jsonl"
    if not gpath.exists():
        print(f"{agent.folder}: no golden.jsonl — nothing to eval")
        return 1
    cases = load_golden(gpath)
    route = args.route or os.environ.get("LA_ROUTE") or "best-quality"
    rows, canary_hits, usage = [], {}, {"input_tokens": 0, "output_tokens": 0}
    provider_name, model_name = "none", "none"

    if agent.spec.runner == "llm_extract":
        from harness.egress import EgressLog
        from harness.providers.base import resolve_provider
        from harness.runners.llm_extract import run_document

        cache_dir = agent.evals_dir / "cache" / "model"
        egress = EgressLog()
        provider = resolve_provider(args.provider, args.model, egress=egress, cache_dir=cache_dir,
                                    replay=args.replay)
        egress.allow.add(provider.endpoint.host)
        provider_name, model_name = provider.name, provider.model
        for case in cases:
            doc = load_case_doc(agent, case)
            r = run_document(agent, doc, provider, route=route, effort=args.effort, writer=None)
            rows += score_extraction_item(agent, case, r.item)
            canary_hits[case.doc_id] = _canary_check(case, r.item)
    else:
        from harness.egress import EgressLog
        from harness.runners.citations.runner import make_resolver, run_document

        egress = EgressLog(allow=set(agent.spec.egress.allow))
        resolver = make_resolver(agent, cache_dir=agent.evals_dir / "cache" / "courtlistener",
                                 offline=args.replay, egress=egress)
        for case in cases:
            doc = load_case_doc(agent, case)
            item, _ = run_document(agent, doc, resolver, writer=None)
            rows += score_findings_item(case, item)
            canary_hits[case.doc_id] = _canary_check(case, item)
            if egress.contains(doc.text[:60]):
                canary_hits[case.doc_id].append("DOCUMENT TEXT EGRESSED")

    n_docs = len(cases) or 1
    usage["tokens_per_doc"] = round((usage["input_tokens"] + usage["output_tokens"]) / n_docs)
    results = aggregate(agent, rows, canary_hits, provider=provider_name, model=model_name,
                        route=route, usage=usage)
    path, published = write_results(agent, results, publish=not args.no_publish)
    build_comparison(agent.evals_dir)
    o = results["overall"]
    print(f"== {agent.folder}  {provider_name}/{model_name}/{route}")
    print(f"field accuracy {o['field_accuracy']:.3f} · presence {o['presence_accuracy']:.3f} · "
          f"quote exact {o['quote_exact_rate']:.3f} · escalation {o['escalation_rate']:.3f} · "
          f"canary {'pass' if results['canary']['pass'] else 'FAIL'} · "
          f"thresholds {'met' if results['thresholds_met'] else 'NOT met'}")
    for name, pf in results["per_field"].items():
        print(f"  {name:<36} acc {pf['value_acc']:.2f}  presence {pf['presence_acc']:.2f}  "
              f"quote exact {pf['quote_exact']:.2f}  escalated {pf['escalated']:.2f}")
    if results["misses"]:
        print(f"  misses: {len(results['misses'])} (see {path.name})")
    if args.baseline:
        base = json.loads(Path(args.baseline).read_text())
        regs = regressions(results, base)
        if regs:
            print("REGRESSIONS vs baseline:\n  " + "\n  ".join(regs))
            return 1
    print(f"written {path.relative_to(REPO_ROOT)}" + ("; results.json updated" if published else
                                                       "; results.json NOT updated"))
    return 0 if results["thresholds_met"] else 1


def cmd_compare(args) -> int:
    from harness.evals.compare import build_comparison

    agent = load_agent(_agent_dir(args.agent))
    print(build_comparison(agent.evals_dir))
    return 0


# --------------------------------------------------------------------------- corpus


def cmd_corpus(args) -> int:
    from harness.document import Manifest

    if args.corpus_cmd == "verify":
        rc = 0
        for mp in sorted(corpus_dir().glob("*/manifest.json")):
            probs = Manifest(mp).verify()
            print(f"{mp.parent.name}: {len(Manifest(mp).entries)} docs, {len(probs)} problems")
            for p in probs:
                print("  " + p)
                rc = 1
        return rc
    if args.corpus_cmd == "add-file":
        m = Manifest(corpus_dir() / args.collection / "manifest.json")
        src = Path(args.file)
        dest_dir = m.collection_dir / "docs"
        dest_dir.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() == ".pdf":
            from harness.ingest import pdf_to_text

            ing = pdf_to_text(src)
            dest = dest_dir / (src.stem + ".txt")
            dest.write_text(ing.text)
            print(f"converted {src.name}: {ing.pages} pages, {ing.dropped_header_lines} header lines dropped")
        else:
            dest = dest_dir / src.name
            if src.resolve() != dest.resolve():
                dest.write_bytes(src.read_bytes())
        e = m.add_file(dest, doc_id=args.doc_id or src.stem, source=args.source,
                       licence=args.licence or ("US public record" if args.source == "SEC EDGAR" else "CC0 (author)"),
                       url=args.url, notes=args.notes or "")
        m.save()
        print(f"added {e.doc_id} ({e.sha256[:12]}) to {args.collection}")
        return 0
    if args.corpus_cmd == "inject":
        return _corpus_inject(args)
    if args.corpus_cmd == "make-briefs":
        return _corpus_make_briefs(args)
    if args.corpus_cmd == "import-contract-nli":
        from harness.importers.contract_nli import import_contract_nli

        n, out = import_contract_nli(Path(args.dataset), corpus_dir() / "contract-nli", count=args.count,
                                     seed=args.seed, out=Path(args.out) if args.out else None)
        print(f"imported {n} NDAs; draft golden at {out}")
        print("every line is labelled_by: draft until a person checks it")
        return 0
    if args.corpus_cmd == "fetch-recap":
        from harness.recap import fetch_briefs

        added = fetch_briefs(corpus_dir() / args.collection, query=args.query, count=args.count,
                             min_pages=args.min_pages, max_pages=args.max_pages,
                             token=os.environ.get("COURTLISTENER_TOKEN"))
        print(f"added {len(added)} briefs to {args.collection}")
        return 0
    return 2


def _corpus_inject(args) -> int:
    from harness.document import Manifest

    m = Manifest(corpus_dir() / args.collection / "manifest.json")
    if args.doc not in m.entries:
        raise SystemExit(f"{args.doc} not in {args.collection}")
    src = m.entries[args.doc]
    template = (corpus_dir() / "injections" / args.template).read_text()
    canary = f"CANARY-{random.Random(args.doc + args.template).randrange(16**6):06x}"
    payload = template.replace("{{CANARY}}", canary)
    text = (m.collection_dir / src.file).read_text()
    # Insert after the first paragraph so it sits inside the document body.
    parts = text.split("\n\n", 1)
    new_text = parts[0] + "\n\n" + payload + "\n\n" + (parts[1] if len(parts) > 1 else "")
    new_id = f"{args.doc}-inj{args.n}"
    dest = m.collection_dir / "docs" / f"{new_id}{Path(src.file).suffix}"
    dest.write_text(new_text)
    m.add_file(dest, doc_id=new_id, source="synthetic", licence="CC0 (author)",
                   derived_from=args.doc, kind="injection",
                   notes=f"injection twin of {args.doc}; template {args.template}; canary {canary}")
    m.save()
    print(json.dumps({"doc_id": new_id, "canary": canary, "twin_of": args.doc}))
    return 0


def _corpus_make_briefs(args) -> int:
    """Generate synthetic briefs for the citation verifier from the confirmed pool."""
    import yaml

    from harness.document import Manifest

    pool = yaml.safe_load((corpus_dir() / "synthetic" / "citation-pool.yaml").read_text())
    real = [c for c in pool["citations"] if c["status"] == "real"]
    fab = [c for c in pool["citations"] if c["status"] == "fabricated"]
    rng = random.Random(args.seed)
    m = Manifest(corpus_dir() / "synthetic" / "manifest.json")
    golden = []
    topics = ["summary judgment", "a motion to dismiss", "retaliation", "pretext", "pleading standards",
              "the burden-shifting framework", "qualified immunity", "expert testimony"]
    for i in range(1, args.count + 1):
        doc_id = f"brief-{i:03d}"
        picks = rng.sample(real, 3)
        defects = []
        expected = []
        paras = [f"# DEFENDANT'S MEMORANDUM No. {i}\n\n> SYNTHETIC TEST DOCUMENT. Parties, facts and "
                 "docket are invented. Citation defects are recorded in evals/golden.jsonl.\n"]
        for c in picks:
            paras.append(f"On {rng.choice(topics)}, the Court has been clear. *{c['name']}*, "
                         f"{c['cite']} ({c['year']}).")
            expected.append({"citation": c["cite"], "verdict": "RESOLVED", "written_name": c["name"]})
        # defect 1: wholly fabricated
        f = rng.choice(fab)
        paras.append(f"The same principle controls here. *{f['name']}*, {f['cite']} ({f['year']}).")
        expected.append({"citation": f["cite"], "verdict": "UNRESOLVED", "written_name": f["name"]})
        defects.append("fabricated")
        # defect 2: real citation, invented name (the realistic fabrication)
        c = rng.choice([x for x in real if x not in picks])
        fake_name = rng.choice(["Harrington v. Vance Capital Partners", "In re Delacroix Holdings",
                                "Whitfield v. Marbury Logistics Group", "Okafor v. Tessaly Corp."])
        paras.append(f"See also *{fake_name}*, {c['cite']} ({c['year']}).")
        expected.append({"citation": c["cite"], "verdict": "NAME_MISMATCH", "written_name": fake_name})
        defects.append("name-mismatch")
        # defect 3 (every third brief): real case, transposed digits — a false alarm the tool cannot tell apart
        if i % 3 == 0:
            c = rng.choice([x for x in real if x not in picks and x.get("typo")])
            paras.append(f"Finally, *{c['name']}*, {c['typo']} ({c['year']}).")
            expected.append({"citation": c["typo"], "verdict": "UNRESOLVED", "written_name": c["name"],
                             "note": "real case, digits transposed — indistinguishable from fabrication"})
            defects.append("typo")
        paras.append("Accordingly, Defendant respectfully requests that the motion be granted.")
        text = "\n\n".join(paras) + "\n"
        dest = m.collection_dir / "docs" / f"{doc_id}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
        m.add_file(dest, doc_id=doc_id, source="synthetic", licence="CC0 (author)",
                   notes="generated by `la corpus make-briefs`; defects: " + ", ".join(defects))
        golden.append({"doc_id": doc_id, "kind": "standard", "expected": {"findings": expected},
                       "labelled_by": pool.get("confirmed_by", "Hassaan Mallick"),
                       "labelled_on": pool.get("confirmed_on"),
                       "notes": "; ".join(defects)})
    m.save()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(g) for g in golden) + "\n")
    print(f"wrote {args.count} briefs and {out}")
    return 0


# --------------------------------------------------------------------------- golden helper


def cmd_golden(args) -> int:
    from harness.document import Manifest
    from harness.quote import locate

    for mp in corpus_dir().glob("*/manifest.json"):
        m = Manifest(mp)
        if args.doc in m.entries:
            doc = m.load(args.doc)
            r = locate(doc, args.quote)
            print(json.dumps(r.to_json(), indent=2))
            if r.locator:
                print("span:", [r.locator.char_start, r.locator.char_end])
            return 0 if r.match != "missing" else 1
    raise SystemExit(f"{args.doc} not found in any corpus")


# --------------------------------------------------------------------------- report


def cmd_report(args) -> int:
    """Summarise a run: per-verdict counts, per-document status, and the items a human must look at."""
    from collections import Counter

    agent = load_agent(_agent_dir(args.agent))
    runs = sorted((RUNS_DIR / agent.folder).glob("*"))
    if not runs:
        raise SystemExit("no runs yet")
    run_dir = Path(args.run) if args.run and args.run != "latest" else runs[-1]
    items = [json.loads(p.read_text()) for p in sorted(run_dir.glob("*.json"))
             if p.name != "run.json" and not p.name.endswith(".redaction-map.json")]
    verdicts, statuses = Counter(), Counter()
    needs_human = []
    for it in items:
        statuses[it["status"]] += 1
        for f in it.get("findings", []):
            verdicts[f["verdict"]] += 1
            if f["status"] == "escalated":
                needs_human.append((it["doc_id"], f["verdict"], f["citation"], (f.get("written_name") or "")[:50]))
        for f in (it.get("fields") or {}).values():
            verdicts[f["status"]] += 1
    # NOT_CHECKED has three very different causes; never report them as one number
    reasons = Counter()
    for it in items:
        for f in it.get("findings", []):
            if f["verdict"] == "NOT_CHECKED":
                ex = f.get("explanation", "")
                reasons["proprietary reporter (Westlaw/Lexis)" if "proprietary" in ex else
                        "not looked up yet (offline / quota)" if "offline" in ex else
                        "lookup failed (rate limit / outage)"] += 1
    print(f"run {run_dir.name}: {len(items)} documents")
    print("documents:", dict(statuses))
    print("findings: ", dict(verdicts))
    if reasons:
        print("not checked:", dict(reasons))
    if needs_human:
        print(f"\n{len(needs_human)} findings need a human:")
        for doc, v, cite, name in needs_human[: args.limit]:
            print(f"  {doc:<20} {v:<14} {cite:<22} {name}")
        if len(needs_human) > args.limit:
            print(f"  … {len(needs_human) - args.limit} more")
    return 0


# --------------------------------------------------------------------------- scan


def cmd_scan(args) -> int:
    import subprocess

    from harness.validate.rules import SECRET_RES

    files = subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard"],
                                    cwd=REPO_ROOT).decode().splitlines()
    rc = 0
    for rel in files:
        p = REPO_ROOT / rel
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        text = p.read_text(errors="ignore")
        for rx in SECRET_RES:
            m = rx.search(text)
            if m:
                print(f"SECRET? {rel}: {m.group(0)[:12]}…")
                rc = 1
                break
    print("clean" if rc == 0 else "secrets found")
    return rc


# --------------------------------------------------------------------------- governance


def cmd_governance(args) -> int:
    import yaml

    rows = []
    for d in all_agent_dirs():
        spec = yaml.safe_load((d / "agent.yaml").read_text())
        results = d / "evals" / "results.json"
        met = results.exists() and json.loads(results.read_text()).get("thresholds_met")
        status = "shipped" if met else "in progress"
        rows.append((d.name, spec.get("series_ref"), spec.get("runner"), spec.get("tier"),
                     spec.get("data_class"), ", ".join(spec.get("controls", [])), status))
    lines = ["# Agents index", "", "Generated by `la governance sync`. Do not edit by hand.", "",
             "| agent | series | runner | tier | data class | controls | status |",
             "|---|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    (GOVERNANCE_DIR / "agents-index.md").write_text("\n".join(lines) + "\n")
    # refresh "Also used by" in controls-library.md
    lib = GOVERNANCE_DIR / "controls-library.md"
    text = lib.read_text()
    usage: dict[str, list[str]] = {}
    for r in rows:
        for c in r[5].split(", "):
            usage.setdefault(c, []).append(r[0])
    def _fix(m: re.Match) -> str:
        cid = m.group(1)
        users = ", ".join(usage.get(cid, []))
        return f"| {cid} | {m.group(2)} | {m.group(3)} | {m.group(4)} | {users} |"
    text = re.sub(r"^\| (C\d+) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$", _fix, text, flags=re.MULTILINE)
    lib.write_text(text)
    print("\n".join(lines))
    return 0


# --------------------------------------------------------------------------- main


def _load_dotenv() -> None:
    """Read REPO_ROOT/.env (git-ignored) into the environment. Values are never
    printed or logged; existing environment variables win."""
    env = REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    ap = argparse.ArgumentParser(prog="la", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="check an agent folder against the bar")
    v.add_argument("agent", nargs="?")
    v.add_argument("--all", action="store_true")
    v.set_defaults(fn=cmd_validate)

    r = sub.add_parser("run", help="run an agent over documents → review queue")
    r.add_argument("agent")
    r.add_argument("--docs", nargs="+", required=True, help="collection names or doc_ids")
    r.add_argument("--provider")
    r.add_argument("--model")
    r.add_argument("--route", choices=["best-quality", "zdr", "local", "split"])
    r.add_argument("--effort", choices=["low", "medium", "high"])
    r.add_argument("--replay", action="store_true", help="citations: cached lookups only")
    r.add_argument("--backend", choices=["auto", "search", "lookup"],
                   help="citations: CourtListener backend (search = anonymous, IP-throttled; lookup = token)")
    r.set_defaults(fn=cmd_run)

    e = sub.add_parser("eval", help="run the golden set, score, write results")
    e.add_argument("agent", nargs="?")
    e.add_argument("--all", action="store_true")
    e.add_argument("--provider")
    e.add_argument("--model")
    e.add_argument("--route", choices=["best-quality", "zdr", "local", "split"])
    e.add_argument("--effort", choices=["low", "medium", "high"])
    e.add_argument("--record", action="store_true", help="live calls, write replay cache")
    e.add_argument("--replay", action="store_true", help="offline, cache only (CI)")
    e.add_argument("--baseline", help="results.json to compare against for regressions")
    e.add_argument("--no-publish", action="store_true", help="never touch results.json")
    e.set_defaults(fn=cmd_eval)

    c = sub.add_parser("compare", help="rebuild evals/comparison.md")
    c.add_argument("agent")
    c.set_defaults(fn=cmd_compare)

    co = sub.add_parser("corpus", help="corpus manifests")
    cs = co.add_subparsers(dest="corpus_cmd", required=True)
    cs.add_parser("verify")
    af = cs.add_parser("add-file")
    af.add_argument("collection")
    af.add_argument("file")
    af.add_argument("--doc-id")
    af.add_argument("--source", required=True,
                    choices=["SEC EDGAR", "public court filing", "open dataset", "synthetic"])
    af.add_argument("--licence")
    af.add_argument("--url")
    af.add_argument("--notes")
    inj = cs.add_parser("inject")
    inj.add_argument("collection")
    inj.add_argument("--doc", required=True)
    inj.add_argument("--template", required=True)
    inj.add_argument("--n", type=int, default=1)
    ic = cs.add_parser("import-contract-nli", help="import NDAs + draft labels from the ContractNLI dataset")
    ic.add_argument("--dataset", required=True, help="path to the unzipped contract-nli folder")
    ic.add_argument("--count", type=int, default=20)
    ic.add_argument("--seed", type=int, default=2026)
    ic.add_argument("--out")
    fr = cs.add_parser("fetch-recap", help="download public briefs from CourtListener RECAP")
    fr.add_argument("collection", nargs="?", default="recap-briefs")
    fr.add_argument("--query", default='"memorandum of law in support of motion for summary judgment"')
    fr.add_argument("--count", type=int, default=30)
    fr.add_argument("--min-pages", type=int, default=6)
    fr.add_argument("--max-pages", type=int, default=40)
    mb = cs.add_parser("make-briefs")
    mb.add_argument("--count", type=int, default=20)
    mb.add_argument("--seed", type=int, default=2026)
    mb.add_argument("--out", default=str(AGENTS_DIR / "002-citation-verifier" / "evals" / "golden.jsonl"))
    co.set_defaults(fn=cmd_corpus)

    g = sub.add_parser("golden", help="helpers for hand-labelling")
    gs = g.add_subparsers(dest="golden_cmd", required=True)
    gl = gs.add_parser("locate")
    gl.add_argument("--doc", required=True)
    gl.add_argument("--quote", required=True)
    gl.set_defaults(fn=cmd_golden)
    gd = gs.add_parser("draft", help="turn a run into draft golden lines for a person to check")
    gd.add_argument("agent")
    gd.add_argument("--run", default="latest")
    gd.add_argument("--out")
    gd.set_defaults(fn=cmd_golden_draft)

    rp = sub.add_parser("report", help="summarise a run (verdict counts, items needing a human)")
    rp.add_argument("agent")
    rp.add_argument("--run", default="latest")
    rp.add_argument("--limit", type=int, default=40)
    rp.set_defaults(fn=cmd_report)

    s = sub.add_parser("scan", help="secrets scan over tracked files")
    s.set_defaults(fn=cmd_scan)

    gv = sub.add_parser("governance", help="regenerate governance/agents-index.md")
    gvs = gv.add_subparsers(dest="gov_cmd", required=True)
    gvs.add_parser("sync")
    gv.set_defaults(fn=cmd_governance)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
