"""Build checker.zip: the Python the browser checker runs.

    uv run --extra citations python checker/bundle.py [--out DIR]

The page lives on mallick.tech (/tools/citation-checker/); its copy of the zip
is public/tools/citation-checker/py/ in that site. Rebuild and copy it there
whenever extract.py, classify.py or the pinned packages change.

The zip holds the harness citation files exactly as the CLI runs them, the
pure-Python packages at the versions in uv.lock (eyecite, reporters-db,
courts-db, rapidfuzz's Python fallback), and two stand-ins for C extensions
that have no wasm build. lxml and regex come from Pyodide itself.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata as md
import json
import zipfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "public" / "py"

HARNESS = [
    "harness/__init__.py",
    "harness/runners/__init__.py",
    "harness/runners/citations/__init__.py",
    "harness/runners/citations/extract.py",
    "harness/runners/citations/classify.py",
    "harness/runners/citations/resolution.py",
]
PACKAGES = {"eyecite": "eyecite", "reporters_db": "reporters-db", "courts_db": "courts-db", "rapidfuzz": "rapidfuzz"}
SKIP_SUFFIXES = (".so", ".pyd", ".pyi", ".pyc", ".c", ".cpp", ".h", ".hpp")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    out = ap.parse_args().out
    out.mkdir(parents=True, exist_ok=True)
    agent = yaml.safe_load((ROOT / "agents/002-citation-verifier/agent.yaml").read_text())
    threshold = agent["gates"]["confidence"]["default"]
    versions = {dist: md.version(dist) for dist in PACKAGES.values()}

    with zipfile.ZipFile(out / "checker.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in HARNESS:
            z.write(ROOT / rel, rel)
        for f in ("browser.py", "ahocorasick.py", "fast_diff_match_patch.py"):
            z.write(HERE / "py" / f, f)
        for mod in PACKAGES:
            pkg = Path(importlib.import_module(mod).__file__).parent
            for f in sorted(pkg.rglob("*")):
                if f.is_dir() or "__pycache__" in f.parts or "__pyinstaller" in f.parts:
                    continue
                if f.suffix in SKIP_SUFFIXES:
                    continue
                z.write(f, f"{mod}/{f.relative_to(pkg)}")

    manifest = {"packages": versions, "confidence_threshold": threshold}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    size = (out / "checker.zip").stat().st_size / 1e6
    print(f"wrote {out / 'checker.zip'} ({size:.1f} MB) {versions}")


if __name__ == "__main__":
    main()
