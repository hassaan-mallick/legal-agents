from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "agents"


@pytest.fixture
def compliant_agent(tmp_path: Path) -> Path:
    """A copy of the compliant fixture agent, editable per test."""
    dest = tmp_path / "agents" / "900-compliant"
    shutil.copytree(FIXTURES / "900-compliant", dest)
    return dest


@pytest.fixture
def nda_doc():
    from harness.document import Document

    text = (REPO / "corpus" / "synthetic" / "docs" / "nda-sparse-001.md").read_text()
    from harness.document import sha256_text

    return Document(doc_id="nda-sparse-001", text=text, sha256=sha256_text(text))


def pytest_configure(config):
    import os

    os.environ["LA_CORPUS_DIR"] = str(Path(__file__).resolve().parent / "fixtures" / "corpus")
