"""Production preflight tests (milestone 7): the whole project in one report.

`core/preflight.py` must aggregate the checks that already exist (`validation`,
`config.validate_config`, the queue/state model, the project plan) and add the
project wide ones: every document, every template, duplicate outputs, disk space and
the Illustrator side. Every case here runs without Illustrator and without a display;
the COM part uses a fake adapter that can only be asked explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_ai_batch.core import config as cfg
from pdf_ai_batch.core import pagejob
from pdf_ai_batch.core import preflight
from pdf_ai_batch.core.naming import output_name_for
from pdf_ai_batch.core.pdf_info import count_pages
from pdf_ai_batch.core.project import JobProject
from pdf_ai_batch.core.queue import BatchQueue


class FakeAdapter:
    """Minimal Illustrator stand-in with the two members preflight uses."""

    def __init__(self, *, ok: bool = True, version: str = "29.8.3", error: str = "") -> None:
        self.ok = ok
        self.version = version
        self.error = error
        self.health_calls = 0

    def health_check(self) -> dict:
        self.health_calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return {"ok": self.ok, "illustrator": {"version": self.version} if self.ok else {}}

    def app_info(self):
        class Info:
            version = "29.8.3"

        return Info()


def make_job(
    tmp_path,
    make_pdf,
    *,
    documents=("manualis.pdf",),
    pages=4,
    templates=("MASTER_AI_TEMPLATE.ai",),
) -> JobProject:
    project = JobProject.open(tmp_path / "PREFLIGHT_JOB")
    for name in documents:
        make_pdf(project.pdf_dir / name, pages=pages)
    for name in templates:
        (project.template_dir / name).write_bytes(b"%PDF-1.5\ntemplate\n")
    return project


def write_config(
    project: JobProject,
    *,
    pages_templates: dict | None = None,
    default_template: str | None = "MASTER_AI_TEMPLATE.ai",
    page_count: int | None = None,
    pdf_name: str = "manualis.pdf",
) -> dict:
    """Write a real config.json (as the GUI/run_one plan editor does) and return it.

    Built straight from the PDF page count instead of `plan_project`, so a test can
    create a stored plan even for a JOB whose plan cannot be built at all (no default
    template, stale page count) - those are exactly the situations preflight checks.
    `page_count` overrides the stored count, which is how the stale case is written.
    """
    documents = []
    names = [pdf_name] + [path.name for path in project.find_pdfs() if path.name != pdf_name]
    for name in names:
        count = int(count_pages(project.pdf_dir / name)[0])
        stored = int(page_count) if (page_count is not None and name == pdf_name) else count
        pages = [
            {
                "page": page,
                "enabled": True,
                "template": (pages_templates or {}).get(page)
                if name == pdf_name
                else None,
                "layer": "ARTWORK",
                "output": output_name_for(name, page, count),
            }
            for page in range(1, stored + 1)
        ]
        documents.append(
            {"pdf": name, "page_count": stored, "enabled": True, "pages": pages}
        )
    defaults = {"template": default_template, "layer": "ARTWORK", "clear_layer": True}
    cfg.save_config(project.config_path, cfg.new_project_config(documents, defaults))
    BatchQueue.open(project).build_queue()
    return cfg.load_config(project.config_path)


def section(result: preflight.PreflightReport, key: str) -> preflight.PreflightSection:
    found = result.section(key)
    assert found is not None, (key, [item.key for item in result.sections])
    return found


# --------------------------------------------------------------------- clean project


def test_clean_project_is_ready(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=3)
    write_config(project)

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_READY
    assert result.can_run is True
    assert result.problems == ()
    for key in preflight.SECTION_ORDER:
        assert section(result, key).severity == preflight.SEVERITY_OK, key
    assert result.facts["pages"] == 3
    assert result.facts["missing_templates"] == []
    assert result.facts["illustrator"] == "READY 29.8.3"
    assert result.facts["output_writable"] is True
    rows = dict(result.summary_rows())
    assert rows["Overall"] == preflight.STATUS_READY
    assert rows["PDF"] == "OK"
    assert rows["Pages"] == "3"
    assert rows["Output writable"] == "YES"
    assert result.job == "PREFLIGHT_JOB"


def test_preflight_never_writes_the_plan(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_config(project)
    before_config = project.config_path.read_bytes()
    before_state = project.state_path.read_bytes()
    outputs = sorted(path.name for path in project.output_dir.glob("*"))

    preflight.run_preflight(project, adapter=FakeAdapter())

    assert project.config_path.read_bytes() == before_config
    assert project.state_path.read_bytes() == before_state
    assert sorted(path.name for path in project.output_dir.glob("*")) == outputs


def test_preflight_does_not_touch_illustrator_unless_asked(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_config(project)
    adapter = FakeAdapter()

    quiet = preflight.run_preflight(project, adapter=adapter, check_illustrator=False)

    assert adapter.health_calls == 0
    assert quiet.facts["illustrator"] == "nav pārbaudīts"
    assert section(quiet, "ILLUSTRATOR").severity == preflight.SEVERITY_WARNING
    assert quiet.can_run is True  # "not checked" is a warning, never a blocker

    loud = preflight.run_preflight(project, adapter=adapter, check_illustrator=True)
    assert adapter.health_calls == 1
    assert loud.facts["illustrator"] == "READY 29.8.3"


def test_unavailable_illustrator_is_an_error(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_config(project)

    result = preflight.run_preflight(project, adapter=FakeAdapter(ok=False))

    assert result.status == preflight.STATUS_NOT_READY
    assert result.facts["illustrator"] == "NAV PIEJAMS"
    assert section(result, "ILLUSTRATOR").severity == preflight.SEVERITY_ERROR
    assert any("Illustrator" in problem for problem in result.problems)


def test_broken_com_environment_is_a_finding_not_a_crash(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_config(project)

    result = preflight.run_preflight(project, adapter=FakeAdapter(error="RPC server unavailable"))

    assert result.status == preflight.STATUS_NOT_READY
    assert any("RPC server unavailable" in problem for problem in result.problems)


# ------------------------------------------------------------------------- documents


def test_missing_document_warns_when_another_document_can_still_run(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    make_pdf(project.pdf_dir / "appendix.pdf", pages=2)
    write_config(project)  # the stored plan lists both documents
    (project.pdf_dir / "appendix.pdf").unlink()

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.facts["missing_pdfs"] == ["appendix.pdf"]
    assert result.status == preflight.STATUS_READY  # manualis.pdf can still run
    assert section(result, "PDF").severity == preflight.SEVERITY_WARNING
    assert any("appendix.pdf" in warning for warning in result.warnings)
    assert dict(result.summary_rows())["PDF"] == "1 trūkst"


def test_missing_document_is_an_error_when_it_is_the_only_document(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    write_config(project)
    (project.pdf_dir / "manualis.pdf").unlink()

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_NOT_READY
    assert any("neviens dokuments nav izpildāms" in problem for problem in result.problems)


def test_stale_page_count_warns_and_mentions_reconcile(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    make_pdf(project.pdf_dir / "appendix.pdf", pages=3)
    write_config(project)
    make_pdf(project.pdf_dir / "appendix.pdf", pages=5)  # page count drift

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.facts["stale"] == ["appendix.pdf"]
    assert result.status == preflight.STATUS_READY  # the other document is healthy
    assert section(result, "PDF").severity == preflight.SEVERITY_WARNING
    assert any("CONFIG STALE" in warning for warning in result.warnings)
    assert any("RECONCILE" in warning for warning in result.warnings)


def test_stale_page_count_is_an_error_for_a_single_document_job(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    write_config(project, page_count=5)  # a plan that does not match the PDF

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.facts["stale"] == ["manualis.pdf"]
    assert result.status == preflight.STATUS_NOT_READY
    # the stale document is excluded from a run, so the blocker is "nothing runnable";
    # the RECONCILE hint itself is a warning, not a blocker
    assert any("neviens dokuments nav izpildāms" in problem for problem in result.problems)
    assert any("RECONCILE" in warning for warning in result.warnings)


def test_pdf_without_a_stored_plan_gets_an_automatic_one(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    write_config(project)
    make_pdf(project.pdf_dir / "noplan.pdf", pages=2)

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_READY
    documents = {row["pdf"]: row for row in result.facts["documents"]}
    assert documents["noplan.pdf"]["status"] == pagejob.DOC_STATUS_NEW
    assert result.facts["pdfs"] == 2
    assert result.facts["pages"] == 4  # both documents are counted



# ------------------------------------------------------------------------- templates


def test_missing_template_is_an_error(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=3, templates=("MASTER_AI_TEMPLATE.ai", "001_cover.ai"))
    write_config(project, pages_templates={1: "001_cover.ai"})
    (project.template_dir / "001_cover.ai").unlink()

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_NOT_READY
    assert result.facts["missing_templates"] == ["001_cover.ai"]
    assert section(result, "TEMPLATES").severity == preflight.SEVERITY_ERROR
    assert any("001_cover.ai" in problem for problem in result.problems)
    assert dict(result.summary_rows())["Missing templates"] == "1"
    assert dict(result.summary_rows())["Templates"] == "TRŪKST"


def test_missing_default_template_is_an_error(tmp_path, make_pdf):
    """No MASTER at all while a page inherits the default template."""
    project = make_job(tmp_path, make_pdf, pages=2, templates=("001_cover.ai",))
    write_config(
        project, pages_templates={1: "001_cover.ai"}, default_template=None
    )

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_NOT_READY
    assert any("prasa MASTER" in problem for problem in result.problems)


def test_template_folder_without_templates_is_an_error(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2, templates=())
    write_config(project)

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_NOT_READY
    assert any("neviena .ai/.ait" in problem for problem in result.problems)


# ---------------------------------------------------------------------------- output


def test_unwritable_output_folder_is_an_error(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_config(project)
    # AI_OUT is not a folder any more: the copy step could never write an output
    for child in list(project.output_dir.iterdir()):
        child.unlink()
    project.output_dir.rmdir()
    project.output_dir.write_text("not a folder", encoding="utf-8")

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_NOT_READY
    assert result.facts["output_writable"] is False
    assert section(result, "OUTPUT").severity == preflight.SEVERITY_ERROR
    assert any("AI_OUT" in problem for problem in result.problems)


def test_duplicate_output_names_are_an_error(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=3)
    write_config(project)
    config = cfg.load_config(project.config_path)
    block = cfg.document_for(config, "manualis.pdf")
    block["pages"][1]["output"] = block["pages"][0]["output"]  # the same file twice
    cfg.save_config(project.config_path, config)

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_NOT_READY
    assert section(result, "OUTPUT").severity == preflight.SEVERITY_ERROR
    assert any("Dublikāti" in problem for problem in result.problems)
    assert dict(result.summary_rows())["Duplicate outputs"] == "1"


def test_output_names_across_documents_must_be_unique(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    make_pdf(project.pdf_dir / "appendix.pdf", pages=2)
    write_config(project)
    config = cfg.load_config(project.config_path)
    first = cfg.document_for(config, "manualis.pdf")["pages"][0]
    second = cfg.document_for(config, "appendix.pdf")["pages"][0]
    second["output"] = first["output"]
    cfg.save_config(project.config_path, config)

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_NOT_READY
    assert result.facts["duplicate_outputs"] == [first["output"]]
    assert any("Dublikāti" in problem for problem in result.problems)


def test_existing_outputs_are_a_warning(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    write_config(project)
    (project.output_dir / "manualis__001.ai").write_bytes(b"%PDF-1.5\ndone\n")

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_READY  # it would only be SKIPped
    assert result.facts["existing_outputs"] == ["manualis.pdf l.1"]
    assert section(result, "OUTPUT").severity == preflight.SEVERITY_WARNING
    assert any("SKIP" in warning for warning in result.warnings)


# ----------------------------------------------------------------------------- queue


def test_queue_with_a_stale_running_item_warns(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    write_config(project)
    import json

    payload = json.loads(project.state_path.read_text(encoding="utf-8"))
    payload["items"][0]["state"] = "RUNNING"
    project.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_READY
    assert section(result, "QUEUE").severity == preflight.SEVERITY_WARNING
    assert any("RUNNING" in warning for warning in result.warnings)


def test_queue_item_outside_the_plan_is_reported(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    write_config(project)
    import json

    payload = json.loads(project.state_path.read_text(encoding="utf-8"))
    orphan = dict(payload["items"][0])
    orphan["job_id"] = "manualis_p099"
    orphan["page"] = 99
    orphan["output"] = str(project.output_dir / "manualis__099.ai")
    payload["items"].append(orphan)
    project.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert any("ārpus plāna" in warning for warning in result.warnings)
    assert section(result, "QUEUE").severity == preflight.SEVERITY_WARNING


def test_corrupt_state_is_a_warning_and_still_allows_a_run(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    write_config(project)
    project.state_path.write_text("{ not json", encoding="utf-8")

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_READY  # the queue rebuilds from the plan
    assert section(result, "PROJECT").severity == preflight.SEVERITY_WARNING
    assert any("state.json" in warning for warning in result.warnings)


# ------------------------------------------------------------- disk space thresholds


class _Usage:
    def __init__(self, free_mb: int) -> None:
        self.total = 500 * 1024 * 1024 * 1024
        self.used = self.total - free_mb * 1024 * 1024
        self.free = free_mb * 1024 * 1024


def _patch_disk(monkeypatch, free_mb: int) -> None:
    monkeypatch.setattr(
        preflight.shutil, "disk_usage", lambda path: _Usage(free_mb), raising=True
    )


def test_low_disk_space_warns(tmp_path, make_pdf, monkeypatch):
    project = make_job(tmp_path, make_pdf)
    write_config(project)
    _patch_disk(monkeypatch, preflight.FREE_SPACE_WARNING_MB - 100)

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_READY  # a warning never blocks
    assert section(result, "SYSTEM").severity == preflight.SEVERITY_WARNING
    assert "maz" in result.facts["disk"]
    assert any("Brīvā vieta" in warning for warning in result.warnings)


def test_critical_disk_space_is_an_error(tmp_path, make_pdf, monkeypatch):
    project = make_job(tmp_path, make_pdf)
    write_config(project)
    _patch_disk(monkeypatch, preflight.FREE_SPACE_ERROR_MB - 50)

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_NOT_READY
    assert section(result, "SYSTEM").severity == preflight.SEVERITY_ERROR
    assert any("Brīvā vieta" in problem for problem in result.problems)


def test_disk_usage_failure_is_a_finding(tmp_path, make_pdf, monkeypatch):
    project = make_job(tmp_path, make_pdf)
    write_config(project)

    def broken(path):
        raise OSError("drive not ready")

    monkeypatch.setattr(preflight.shutil, "disk_usage", broken, raising=True)

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    assert result.status == preflight.STATUS_NOT_READY
    assert any("nevar nolasīt" in problem for problem in result.problems)


# ------------------------------------------------------------------------- reporting


def test_preflight_text_and_dict_agree(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=3)
    write_config(project)
    result = preflight.run_preflight(project, adapter=FakeAdapter())

    text = result.to_text()
    payload = result.to_dict()

    assert "PRODUCTION PREFLIGHT" in text
    assert "Overall" in text and "READY" in text
    assert payload["status"] == preflight.STATUS_READY
    assert payload["can_run"] is True
    assert [row["key"] for row in payload["sections"]] == list(preflight.SECTION_ORDER)
    assert payload["facts"]["pages"] == 3
    assert payload["facts"]["templates"] == 1
    assert all("severity" in row for row in payload["sections"])
    assert all(
        check["severity"] in (preflight.SEVERITY_OK, preflight.SEVERITY_WARNING, preflight.SEVERITY_ERROR)
        for row in payload["sections"]
        for check in row["checks"]
    )


def test_preflight_reports_the_report_folder(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_config(project)

    result = preflight.run_preflight(project, adapter=FakeAdapter())

    reports = project.log_dir / "reports"
    assert reports.is_dir()  # created so the first pass can write into it
    assert result.facts["reports"] == 0
    assert any(check.name == "Report mape" and check.ok for check in section(result, "SYSTEM").checks)




