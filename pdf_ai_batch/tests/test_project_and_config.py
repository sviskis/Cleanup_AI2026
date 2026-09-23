"""The JOB project, config.json handling and preflight validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_ai_batch.core import config as cfg
from pdf_ai_batch.core import jsonio, validation
from pdf_ai_batch.core.project import JobProject
from pdf_ai_batch.core.template_mapper import build_page_plan

FOLDERS = ("PDF", "TEMPLATE", "CONFIG", "AI_OUT", "LOG", "ERROR")


def write_template(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"%PDF-1.5\ntemplate\n")
    return path


def test_open_creates_every_missing_folder(job_folder):
    project = JobProject.open(job_folder)
    for name in FOLDERS:
        assert (job_folder / name).is_dir()
    assert project.config_path == job_folder / "CONFIG" / "config.json"
    assert project.state_path == job_folder / "CONFIG" / "state.json"


def test_open_existing_without_create_fails(job_folder):
    with pytest.raises(Exception):
        JobProject.open(job_folder / "does_not_exist", create=False)


def test_resolve_pdf_accepts_name_and_path(job_folder, make_pdf):
    project = JobProject.open(job_folder)
    pdf = make_pdf(project.pdf_dir / "manual.pdf", pages=2)
    assert project.resolve_pdf("manual.pdf") == pdf
    assert project.resolve_pdf(str(pdf)) == pdf
    with pytest.raises(Exception):
        project.resolve_pdf("nope.pdf")


def test_resolve_output_keeps_outputs_inside_ai_out(job_folder):
    project = JobProject.open(job_folder)
    assert project.resolve_output("manual__001.ai") == project.output_dir / "manual__001.ai"
    absolute = Path("C:/somewhere/else.ai")
    assert project.resolve_output(absolute) == absolute


def test_project_info_summarises_content(job_folder, make_pdf):
    project = JobProject.open(job_folder)
    make_pdf(project.pdf_dir / "b.pdf", pages=1)
    make_pdf(project.pdf_dir / "a.pdf", pages=1)
    write_template(project.template_dir, "MASTER_AI_TEMPLATE.ai")

    info = project.info()
    assert info["pdf_count"] == 2
    assert info["pdfs"] == ["a.pdf", "b.pdf"]
    assert info["default_template"] == "MASTER_AI_TEMPLATE.ai"


def test_config_round_trip_and_validation(job_folder):
    project = JobProject.open(job_folder)
    write_template(project.template_dir, "001_cover.ai")
    write_template(project.template_dir, "MASTER_AI_TEMPLATE.ai")

    pages, defaults, _fallback = build_page_plan("manual.pdf", 3, project.template_dir)
    document = cfg.new_config("manual.pdf", 3, pages, defaults)

    assert cfg.validate_config(document) == []
    cfg.save_config(project.config_path, document)

    loaded = cfg.load_config(project.config_path)
    assert loaded == document
    assert cfg.page_entries(loaded)[0]["output"] == "manual__001.ai"
    assert len(cfg.enabled_page_entries(loaded)) == 3


def test_validate_config_reports_real_problems(job_folder):
    document = {
        "version": 2,
        "defaults": {"template": None, "layer": "", "clear_layer": True},
        "documents": [
            {
                "pdf": "",
                "page_count": 0,
                "enabled": True,
                "pages": [
                    {"page": 1, "enabled": True, "template": "x.txt", "output": "a.ai"},
                    {"page": 1, "enabled": True, "template": None, "output": "a.ai"},
                    {"page": 5, "enabled": True, "template": None, "output": "b.pdf"},
                ],
            }
        ],
    }
    problems = cfg.validate_config(document)
    assert any("pdf ir tukšs" in problem for problem in problems)
    assert any("page_count" in problem for problem in problems)
    assert any("layer" in problem for problem in problems)
    assert any("parādās divreiz" in problem for problem in problems)
    assert any("pārsniedz" in problem for problem in problems)
    assert any("nav .ai/.ait" in problem for problem in problems)
    assert any("jābeidzas ar .ai" in problem for problem in problems)


def test_validate_config_migrates_v1_and_reports_unknown_versions(job_folder):
    legacy = {
        "version": 1,
        "pdf": "manual.pdf",
        "page_count": 2,
        "defaults": {"template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK"},
        "pages": [{"page": 1, "enabled": True, "output": "manual__001.ai"}],
    }
    assert cfg.validate_config(legacy) == []
    migrated, note = cfg.migrate_config(legacy)
    assert migrated["version"] == cfg.CONFIG_VERSION
    assert note
    assert migrated["documents"][0]["pdf"] == "manual.pdf"
    assert cfg.page_entries(migrated, "manual.pdf")[0]["output"] == "manual__001.ai"

    unknown = {"version": 99, "documentses": []}
    problems = cfg.validate_config(unknown)
    assert any("nezināma config versija" in problem for problem in problems)


def test_validate_config_detects_duplicate_outputs():
    document = cfg.new_config(
        "manual.pdf",
        2,
        [
            {"page": 1, "enabled": True, "template": None, "output": "same.ai"},
            {"page": 2, "enabled": True, "template": None, "output": "same.ai"},
        ],
        {"template": None, "layer": "ARTWORK", "clear_layer": True},
    )
    problems = cfg.validate_config(document)
    assert any("vairākām lapām" in problem for problem in problems)


def test_template_mode_for_ai_and_ait():
    assert cfg.template_mode_for("MASTER_AI_TEMPLATE.ai") == "copy"
    assert cfg.template_mode_for("MASTER_AI_TEMPLATE.AIT") == "saveas"


def test_load_config_of_missing_file_is_empty(job_folder):
    project = JobProject.open(job_folder)
    assert cfg.load_config(project.config_path) == {}
    assert jsonio.read_json(project.config_path, default={}) == {}


def test_preflight_passes_for_a_complete_job(job_folder, make_pdf, fake_repo):
    project = JobProject.open(job_folder)
    pdf = make_pdf(project.pdf_dir / "manual.pdf", pages=2)
    template = write_template(project.template_dir, "MASTER_AI_TEMPLATE.ai")

    checks = validation.preflight(
        project,
        pdf=pdf,
        page=1,
        page_count=2,
        template=template,
        output=project.output_dir / "manual__001.ai",
        worker_jsx=fake_repo / "jsx" / "worker.jsx",
        cleanup_jsx=fake_repo / "jsx" / "cleanup.jsx",
        runtime_dir=fake_repo / "runtime",
        illustrator_available=True,
    )
    assert not validation.has_failures(checks)
    assert "kļūdas=0" in validation.format_report(checks)


def test_preflight_fails_when_files_or_folders_are_missing(job_folder, fake_repo):
    project = JobProject.open(job_folder)
    checks = validation.preflight(
        project,
        pdf="missing.pdf",
        page=99,
        page_count=3,
        template="missing.ai",
        output=project.output_dir / "bad name.pdf",
        worker_jsx=fake_repo / "jsx" / "not_here.jsx",
        cleanup_jsx=fake_repo / "jsx" / "cleanup.jsx",
        runtime_dir=fake_repo / "runtime",
        illustrator_available=False,
    )
    assert validation.has_failures(checks)
    report = validation.format_report(checks)
    assert "PDF fails" in report
    assert "Lapas numurs" in report
    assert "worker.jsx" in report

    # illustrator missing is only a warning, it must not fail the preflight
    illustrator_check = [check for check in checks if check.name == "Illustrator"][0]
    assert illustrator_check.warning


def test_is_writable_rejects_missing_folder(tmp_path):
    assert validation.is_writable(tmp_path / "nope") is False
    assert validation.is_writable(tmp_path) is True
