"""Shared pytest fixtures: a temporary repository and a real multi page PDF."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture()
def fake_repo(tmp_path, monkeypatch) -> Path:
    """A temporary 'repository': jsx/, runtime/ and a JOB folder inside it."""
    root = tmp_path / "repo"
    (root / "jsx").mkdir(parents=True)
    (root / "runtime").mkdir()
    (root / "jsx" / "worker.jsx").write_text("// stub worker\n", encoding="utf-8")
    (root / "jsx" / "cleanup.jsx").write_text("// stub cleanup\n", encoding="utf-8")
    (root / "jsx" / "json2.js").write_text("// stub json\n", encoding="utf-8")
    monkeypatch.setenv("PDF_AI_BATCH_ROOT", str(root))
    return root


@pytest.fixture()
def make_pdf():
    """Factory that writes a real PDF with a given page count (PyMuPDF)."""
    mupdf = pytest.importorskip("pymupdf", reason="PyMuPDF not installed")

    def _make(path: Path, pages: int = 3) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        document = mupdf.open()
        for index in range(pages):
            page = document.new_page(width=595, height=842)  # A4 in points
            page.insert_text((72, 72), f"page {index + 1}")
        document.save(str(path))
        document.close()
        return path

    return _make


@pytest.fixture()
def job_folder(tmp_path) -> Path:
    """A plain folder that a JobProject can take over."""
    folder = tmp_path / "JOB_TEST"
    folder.mkdir()
    return folder
