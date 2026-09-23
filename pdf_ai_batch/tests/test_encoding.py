"""Encoding guards for the JSX worker chain and the JSON contract.

Why these tests exist
---------------------
Illustrator decodes a large BOM-less UTF-8 .jsx loaded with doJavaScriptFile as
ANSI (Windows codepage), so a raw Latvian literal in jsx/worker.jsx arrived as
mojibake in runtime/current_result.json (the worker message was unreadable).
The generated jsx/cleanup.jsx was damaged the same way: the extraction tool had
lost its UTF-8 BOM, so PowerShell read its Latvian here-strings as ANSI and wrote
the mojibake into the generated file. Both defects are frozen here:

  * jsx/ sources are pure ASCII (\\uXXXX escapes), no BOM, LF line endings
  * no text source in the repository carries cp1252 mojibake
  * request JSON, result JSON and the worker log are always read/written UTF-8
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_ai_batch.core import contract, jsonio

REPO_ROOT = Path(__file__).resolve().parents[2]
JSX_DIR = REPO_ROOT / "jsx"

# byte pairs that only appear when UTF-8 text was decoded as cp1252/latin-1
MOJIBAKE_MARKERS = (
    "\u00c4\u201c", "\u00c4\u0081", "\u00c4\u00ab", "\u00c4\u00a3", "\u00c4\u00a7",
    "\u00c4\u008d", "\u00c4\u00bc", "\u00c4\u00b7", "\u00c4\u0086", "\u00c4\u0093",
    "\u00c5\u00a1", "\u00c5\u00ab", "\u00c5\u0081", "\u00c5\u00bd", "\u00c5\u201c",
    "\u00c5\u2020", "\u00c5\u00a0", "\u00c5\u00be", "\u00e2\u20ac", "\u00c3\u00a4",
)

TEXT_SUFFIXES = (".py", ".jsx", ".js", ".json", ".md", ".ps1", ".txt")
SCAN_DIRS = (
    "jsx",
    "src",
    "pdf_ai_batch",
    "tools",
    "tests",
    "docs",
    "config",
    "examples",
    "legacy",
    "archive",
)
SKIP_PARTS = ("__pycache__", ".pytest_cache", "node_modules")

# the Latvian text used everywhere in this module
WORKER_MESSAGE = "Neder\u012bgs piepras\u012bjums"
LATVIAN_PDF = "M\u0101ja \u0100\u010d\u0113\u0123\u012b.pdf"


def text_sources() -> list[Path]:
    """Every text file of the project that must be valid UTF-8 without mojibake."""
    found: list[Path] = []
    for name in SCAN_DIRS:
        base = REPO_ROOT / name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if any(part in path.parts for part in SKIP_PARTS):
                continue
            found.append(path)
    found.extend(sorted(REPO_ROOT.glob("*.md")))
    return found


def test_jsx_sources_are_pure_ascii_without_bom_and_with_lf():
    """ExtendScript must never have to guess the encoding of a jsx/ source."""
    files = sorted(path for path in JSX_DIR.iterdir() if path.suffix in (".jsx", ".js"))
    assert files, "jsx/ sources not found"

    for path in files:
        data = path.read_bytes()
        assert not data.startswith(b"\xef\xbb\xbf"), f"{path.name} has a UTF-8 BOM"
        assert b"\r" not in data, f"{path.name} contains CR, jsx/ uses LF only"
        non_ascii = sum(1 for byte in data if byte > 127)
        assert non_ascii == 0, (
            f"{path.name}: {non_ascii} non-ASCII byte(s); use \\uXXXX escapes "
            "(Illustrator decodes a large BOM-less .jsx as ANSI)"
        )


def test_no_text_source_contains_mojibake():
    offenders: list[str] = []
    for path in text_sources():
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            offenders.append(f"{path.relative_to(REPO_ROOT)} (not UTF-8: {exc})")
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if any(marker in line for marker in MOJIBAKE_MARKERS):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")
    assert not offenders, "mojibake found in: " + ", ".join(offenders)


def test_request_json_is_written_as_utf8(tmp_path):
    request = contract.build_request(
        run_id="r1",
        job_id="manual_p001",
        pdf=tmp_path / LATVIAN_PDF,
        page=1,
        template=tmp_path / "MASTER_AI_TEMPLATE.ai",
        output=tmp_path / "manual__001.ai",
    )
    path = jsonio.write_json_atomic(tmp_path / "current_job.json", request)

    raw = path.read_bytes()
    text = raw.decode("utf-8")                     # valid UTF-8, never cp1252
    assert "\u0101".encode("utf-8") in raw          # real characters, not escapes
    assert "\\u0101" not in text
    assert json.loads(text)["pdf"] == request["pdf"]
    assert "\u00c4" not in text                     # no mojibake marker


def test_result_json_is_read_as_utf8(tmp_path):
    result_path = tmp_path / "current_result.json"
    result = {
        "schema": contract.RESULT_SCHEMA,
        "run_id": "r1",
        "job_id": "manual_p001",
        "status": "ERROR",
        "page": 1,
        "output": "C:/JOB/AI_OUT/manual__001.ai",
        "message": WORKER_MESSAGE + ": pdf nav atrasts: C:/JOB/PDF/" + LATVIAN_PDF,
        "error_type": "INVALID_REQUEST",
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    data = jsonio.read_json(result_path)
    assert data["message"] == result["message"]
    assert WORKER_MESSAGE in data["message"]
    assert "\u00c4" not in data["message"]

    accepted, reason = jsonio.wait_for_json(result_path, lambda candidate: True, timeout=1.0)
    assert accepted == result
    assert reason == ""


def test_worker_log_is_read_as_utf8(tmp_path):
    log_path = tmp_path / "worker.log"
    log_path.write_bytes(
        ("2026-09-23 17:26:23 | ERROR INVALID_REQUEST pdf nav atrasts: " + LATVIAN_PDF + "\r\n").encode(
            "utf-8"
        )
    )

    text = jsonio.read_text(log_path)
    assert LATVIAN_PDF in text
    assert "\u00c4" not in text


def test_worker_keeps_strict_absolute_path_validation():
    """Source level guard: the JSX side stays strict (no Illustrator in pytest).

    The real behaviour is exercised by the end to end run
    (.venv\\Scripts\\python.exe -m pdf_ai_batch.run_one --job temp\\REAL_TEST ...).
    """
    source = (JSX_DIR / "worker.jsx").read_text(encoding="utf-8")

    assert "function isAbsolutePath(" in source
    assert 'checkContractPath(problems, "pdf", req.pdf, true, "nav atrasts")' in source
    assert 'checkContractPath(problems, "template", req.template, true, "nav atrasts")' in source
    assert "new File(value)).exists" in source
    assert 'mode === "copy"' in source
    assert "nav sagatavots (template_mode=copy)" in source
    # the handoff is UTF-8 in both directions
    assert source.count('encoding = "UTF-8"') >= 2

