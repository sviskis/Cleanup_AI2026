"""The request JSON carries ABSOLUTE paths only - Python owns path resolution.

Regression tests for the milestone bug: run_one wrote relative paths such as
``temp\\REAL_TEST\\PDF\\mans_fails.pdf`` into ``runtime/current_job.json``. The
worker runs inside Illustrator, which has its own current working directory, so
``File(request.pdf).exists`` was false and every job ended as INVALID_REQUEST.

Covered here:

    * a relative --job path ends up absolute in the request
    * spaces in the path, Latvian characters, a OneDrive style location
    * pdf, template and output are all absolute and use forward slashes
    * no contract path field depends on the current working directory
    * the validator rejects a request that still carries relative paths
"""

from __future__ import annotations

import json
from pathlib import Path

from pdf_ai_batch.core import contract, jsonio
from pdf_ai_batch.core.project import JobProject

LATVIAN_JOB = "Latvijas mape \u0100\u010d"
LATVIAN_PDF = "M\u0101ja \u0100\u010d\u0113\u0123\u012b.pdf"
LATVIAN_TEMPLATE = "\u0160ablons MASTER.ai"
SPACE_JOB = "JOB with spaces"
SPACE_PDF = "my manual file.pdf"

# the exact shape from the milestone report (Windows + OneDrive + one space)
ONEDRIVE_EXAMPLE = (
    "C:/Users/libri/OneDrive/Dokumenti/CLINE/Cleanup_AI2026/temp/REAL_TEST/PDF/mans_fails.pdf"
)


def prepare_job(
    root: str | Path,
    *,
    pdf_name: str = "manual.pdf",
    template_name: str = "MASTER_AI_TEMPLATE.ai",
    output_name: str = "manual__001.ai",
) -> JobProject:
    """A JOB folder with a real PDF, template and prepared output copy."""
    project = JobProject.open(root)
    (project.pdf_dir / pdf_name).write_bytes(b"%PDF-1.5\npage one\n")
    (project.template_dir / template_name).write_bytes(b"%PDF-1.5\nMASTER template\n")
    (project.output_dir / output_name).write_bytes(b"%PDF-1.5\ncopy of the template\n")
    return project


def request_for(
    project: JobProject,
    *,
    pdf_name: str = "manual.pdf",
    template_name: str = "MASTER_AI_TEMPLATE.ai",
    output_name: str = "manual__001.ai",
    page: int = 1,
) -> dict:
    """The request run_one builds for one page."""
    return contract.build_request(
        run_id="run-1",
        job_id=f"manual_p{page:03d}",
        pdf=project.pdf_dir / pdf_name,
        page=page,
        template=project.template_dir / template_name,
        output=project.output_dir / output_name,
    )


def assert_absolute_contract_paths(request: dict) -> None:
    """Every path field is absolute, forward slashed and points at a real file."""
    for key in contract.CONTRACT_PATH_KEYS:
        value = request[key]
        assert contract.is_absolute_path(value), f"{key} nav absolūts: {value!r}"
        assert "\\" not in value, f"{key} satur atpakaļslīpsvītras: {value!r}"
        assert Path(value).is_file(), f"{key} fails neeksistē: {value!r}"


def test_relative_job_path_becomes_an_absolute_request_path(tmp_path, monkeypatch):
    """--job temp\\REAL_TEST is relative: the request must not inherit that."""
    monkeypatch.chdir(tmp_path)
    project = prepare_job(Path("REL_JOB"))

    assert project.root.is_absolute()
    assert Path(project.root) == tmp_path / "REL_JOB"

    request = request_for(project)
    assert_absolute_contract_paths(request)
    assert request["pdf"].startswith(project.root.as_posix() + "/")


def test_request_paths_with_spaces(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = prepare_job(Path(SPACE_JOB), pdf_name=SPACE_PDF)

    request = request_for(project, pdf_name=SPACE_PDF)
    assert_absolute_contract_paths(request)
    assert SPACE_JOB in request["pdf"]
    assert SPACE_PDF in request["pdf"]
    # a raw path, never URL encoded
    assert "%20" not in request["pdf"]


def test_request_paths_with_latvian_characters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = prepare_job(
        Path(LATVIAN_JOB),
        pdf_name=LATVIAN_PDF,
        template_name=LATVIAN_TEMPLATE,
    )

    request = request_for(project, pdf_name=LATVIAN_PDF, template_name=LATVIAN_TEMPLATE)
    assert_absolute_contract_paths(request)
    assert LATVIAN_JOB in request["pdf"]
    assert LATVIAN_PDF in request["pdf"]
    assert LATVIAN_TEMPLATE in request["template"]


def test_onedrive_style_path_stays_absolute_with_forward_slashes():
    """The milestone example: a Windows drive path under OneDrive."""
    resolved = contract.contract_path(ONEDRIVE_EXAMPLE)

    assert "\\" not in resolved
    assert resolved.startswith("C:/") or resolved.startswith("c:/")
    assert resolved.casefold().endswith("/temp/real_test/pdf/mans_fails.pdf")
    assert resolved.casefold().startswith("c:/users/libri/onedrive/dokumenti/cline/cleanup_ai2026/")
    assert Path(resolved) == Path(ONEDRIVE_EXAMPLE)


def test_onedrive_like_job_folder_is_resolved(tmp_path, monkeypatch):
    """A job inside a "OneDrive - <company>" folder (spaces and a dash)."""
    monkeypatch.chdir(tmp_path)
    project = prepare_job(Path("OneDrive - Contoso") / "Dokumenti" / "JOB")

    request = request_for(project)
    assert_absolute_contract_paths(request)
    assert "OneDrive - Contoso/Dokumenti/JOB/PDF/manual.pdf" in request["pdf"]


def test_pdf_template_and_output_are_all_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = prepare_job(Path("ABS_JOB"))

    request = request_for(project)
    assert_absolute_contract_paths(request)

    # same file, one canonical spelling: forward slashes, no backslashes
    assert request["pdf"] == (project.pdf_dir / "manual.pdf").as_posix()
    assert request["template"] == (project.template_dir / "MASTER_AI_TEMPLATE.ai").as_posix()
    assert request["output"] == (project.output_dir / "manual__001.ai").as_posix()


def test_no_contract_path_field_depends_on_the_current_working_directory(tmp_path, monkeypatch):
    """A written request stays valid when it is read from somewhere else."""
    cwd_a = tmp_path / "cwd_a"
    cwd_b = tmp_path / "cwd_b"
    cwd_a.mkdir()
    cwd_b.mkdir()

    monkeypatch.chdir(cwd_a)
    project = prepare_job(tmp_path / "JOB_CWD")
    request = request_for(project)
    written = jsonio.write_json_atomic(tmp_path / "runtime" / "current_job.json", request)

    monkeypatch.chdir(cwd_b)
    assert Path.cwd() != cwd_a

    data = json.loads(written.read_text(encoding="utf-8"))
    for key in contract.CONTRACT_PATH_KEYS:
        assert data[key] == request[key]
        assert Path(data[key]).is_file(), f"{key} atkarīgs no cwd: {data[key]!r}"
    assert_absolute_contract_paths(data)


def test_request_built_in_one_directory_is_usable_in_another(tmp_path, monkeypatch):
    """The original defect: relative job path plus Illustrator's own cwd."""
    cwd_a = tmp_path / "builder"
    cwd_b = tmp_path / "illustrator_cwd"
    cwd_a.mkdir()
    cwd_b.mkdir()

    monkeypatch.chdir(cwd_a)
    project = prepare_job(Path("REL_JOB"))
    request = request_for(project)

    monkeypatch.chdir(cwd_b)
    for key in contract.CONTRACT_PATH_KEYS:
        assert Path(request[key]).is_file(), f"{key} pazūd, mainot cwd: {request[key]!r}"


def test_contract_path_normalises_backslashes_and_dot_segments(tmp_path):
    raw = str(tmp_path / "JOB") + "\\PDF\\..\\PDF\\manual.pdf"
    assert contract.contract_path(raw) == (tmp_path / "JOB" / "PDF" / "manual.pdf").as_posix()


def test_validate_request_rejects_a_relative_path(tmp_path, monkeypatch):
    """The wire format is enforced, so an old style request cannot slip through."""
    monkeypatch.chdir(tmp_path)
    project = prepare_job(Path("REL_JOB"))
    request = request_for(project)
    assert contract.validate_request(request) == []

    request["pdf"] = "temp\\REAL_TEST\\PDF\\mans_fails.pdf"
    request["output"] = "mans_fails__003.ai"
    problems = contract.validate_request(request)

    assert any(problem.startswith("pdf") and "absolūts" in problem for problem in problems)
    assert any(problem.startswith("output") and "absolūts" in problem for problem in problems)


def test_is_absolute_path_accepts_every_contract_form():
    assert contract.is_absolute_path("C:/JOB/PDF/a.pdf")
    assert contract.is_absolute_path("C:\\JOB\\PDF\\a.pdf")
    assert contract.is_absolute_path("//server/share/a.pdf")
    assert contract.is_absolute_path("/opt/job/a.pdf")
    assert not contract.is_absolute_path("temp/JOB/PDF/a.pdf")
    assert not contract.is_absolute_path("a.pdf")
    assert not contract.is_absolute_path("")
    assert not contract.is_absolute_path(None)
