"""GUI controller with several PDFs in one JOB (milestone 4), no display, no COM.

The controller decides what each tab shows; these tests prove that it stays a thin
layer: the document list comes from `core.pagejob.plan_project`, the mapping table is
scoped to the active document, plan edits reach `config.json` (and the queue through
`build_queue`), and every run button ends up in a proven `BatchQueue` call.
"""

from __future__ import annotations

import pytest

from pdf_ai_batch.core import config as cfg
from pdf_ai_batch.core import pagejob, state
from pdf_ai_batch.core.project import JobProject
from pdf_ai_batch.gui import controller
from pdf_ai_batch.tests.fakes import FakeIllustrator

MANUALIS = "manualis.pdf"
APPENDIX = "appendix.pdf"


@pytest.fixture()
def adapter() -> FakeIllustrator:
    return FakeIllustrator()


@pytest.fixture()
def job(tmp_path, make_pdf) -> JobProject:
    """A JOB with two PDFs (3 + 3 pages) and a MASTER template."""
    project = JobProject.open(tmp_path / "GUI_MULTI_JOB")
    make_pdf(project.pdf_dir / MANUALIS, pages=3)
    make_pdf(project.pdf_dir / APPENDIX, pages=3)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nMASTER template\n")
    return project


@pytest.fixture()
def gui(job, adapter) -> controller.AppController:
    app = controller.AppController(adapter_factory=lambda: adapter)
    app.open_project(job.root)
    app.select_document(MANUALIS)
    app.ensure_queue_built()
    return app


def names(rows) -> list[str]:
    return [row.name for row in rows]


def states_of(app: controller.AppController, pdf: str) -> list[str]:
    return [item.state for item in app.queue.items_of(pdf)]


def test_documents_lists_every_pdf_of_the_job(gui, adapter):
    rows = gui.documents()

    # a fresh JOB has no config: the project order is the natural sort of JOB/PDF
    assert names(rows) == [APPENDIX, MANUALIS]
    assert [row.page_count for row in rows] == [3, 3]
    assert all(row.enabled for row in rows)
    assert [row.status for row in rows] == [pagejob.DOC_STATUS_NEW, pagejob.DOC_STATUS_NEW]
    assert "autom" in rows[0].config_status
    assert rows[1].active is True and rows[0].active is False  # manualis is selected
    # the queue was built for both documents, nothing ran
    assert [row.queue_status for row in rows] == ["WAITING 3", "WAITING 3"]
    assert adapter.pages_run() == []


def test_document_order_follows_the_config(gui, job):
    config = cfg.new_project_config(
        [
            {"pdf": MANUALIS, "page_count": 3},
            {"pdf": APPENDIX, "page_count": 3},
        ],
        {"template": "MASTER_AI_TEMPLATE.ai"},
    )
    cfg.save_config(job.config_path, config)

    assert names(gui.documents()) == [MANUALIS, APPENDIX]


def test_selecting_a_document_scopes_the_mapping_table(gui, job, make_pdf):
    assert [row.job_id for row in gui.mapping_rows()] == [
        "manualis_p001",
        "manualis_p002",
        "manualis_p003",
    ]

    row = gui.select_document(APPENDIX)

    assert row.name == APPENDIX
    assert gui.active_pdf_id == "appendix"
    assert [mapping.job_id for mapping in gui.mapping_rows()] == [
        "appendix_p001",
        "appendix_p002",
        "appendix_p003",
    ]
    assert all(mapping.pdf_id == "appendix" for mapping in gui.mapping_rows())
    assert gui.active_document().name == APPENDIX

    with pytest.raises(controller.ControllerError):
        gui.select_document("missing.pdf")


def test_plan_edits_only_touch_the_active_document(gui, job):
    gui.set_enabled([2], False)
    config = cfg.load_config(job.config_path)

    assert {entry["page"]: entry["enabled"] for entry in cfg.page_entries(config, MANUALIS)} == {
        1: True,
        2: False,
        3: True,
    }
    assert cfg.document_for(config, APPENDIX) is None

    gui.select_document(APPENDIX)
    gui.set_enabled([1, 2, 3], True)
    config = cfg.load_config(job.config_path)

    assert len(cfg.document_entries(config)) == 2
    assert {entry["page"]: entry["enabled"] for entry in cfg.page_entries(config, MANUALIS)} == {
        1: True,
        2: False,
        3: True,
    }
    assert {entry["page"]: entry["enabled"] for entry in cfg.page_entries(config, APPENDIX)} == {
        1: True,
        2: True,
        3: True,
    }


def test_run_current_pdf_leaves_the_other_document_waiting(gui, adapter):
    summary = gui.run_document()

    assert adapter.pages_run() == [1, 2, 3]  # only manualis
    assert states_of(gui, MANUALIS) == [state.DONE] * 3
    assert states_of(gui, APPENDIX) == [state.WAITING] * 3
    assert summary.pdfs == 2
    assert summary.counts["DONE"] == 3 and summary.counts["WAITING"] == 3
    assert "PDFs: 2" in summary.format()


def test_run_all_enabled_covers_the_project_and_survives_one_error(gui, adapter):
    adapter.script["manualis_p002"] = "error"

    summary = gui.run_all_enabled()

    assert adapter.pages_run() == [1, 2, 3, 1, 2, 3]
    assert states_of(gui, MANUALIS) == [state.DONE, state.ERROR, state.DONE]
    assert states_of(gui, APPENDIX) == [state.DONE] * 3
    assert summary.aborted is False

    adapter.script.clear()
    retried = gui.retry_errors()

    assert states_of(gui, MANUALIS) == [state.DONE] * 3
    assert retried.counts["DONE"] == 6


def test_continue_queue_resumes_the_whole_project(gui, adapter):
    gui.run_document()
    item = gui.queue.document.find("appendix_p001")
    gui.queue.document.replace_item(state.mark_running(item, "run-crash"))
    gui.queue.save()

    summary = gui.continue_queue()

    assert summary.counts["INTERRUPTED"] == 0
    assert summary.counts["DONE"] == 6
    assert adapter.pages_run() == [1, 2, 3, 1, 2, 3]


def test_disabling_a_document_gates_its_pages(gui, adapter):
    rows = gui.set_document_enabled(APPENDIX, False)

    assert {row.name: row.enabled for row in rows} == {MANUALIS: True, APPENDIX: False}
    assert states_of(gui, APPENDIX) == [state.WAITING] * 3
    assert all(not item.enabled for item in gui.queue.items_of(APPENDIX))

    summary = gui.run_all_enabled()

    assert adapter.pages_run() == [1, 2, 3]
    assert summary.counts["DONE"] == 3
    assert summary.counts["WAITING"] == 3


def test_progress_is_project_and_document_aware(gui, adapter):
    adapter.script["appendix_p002"] = "error"
    gui.run_all_enabled()

    snapshot = gui.progress()

    assert snapshot.pdfs == 2
    assert snapshot.total == 6 and snapshot.processed == 6
    assert snapshot.document in (MANUALIS, APPENDIX)
    assert snapshot.document_total == 3
    assert "PDFs: 2" in snapshot.summary_lines()
    assert any("Lapas kopā: 6" in line for line in snapshot.summary_lines())
    lines = snapshot.document_lines()
    assert len(lines) == 2
    assert any(line.startswith(MANUALIS) for line in lines)
    assert any("ERROR 1" in line for line in lines)


def test_page_count_drift_is_visible_and_reconciled_explicitly(gui, job, make_pdf):
    gui.auto_assign_templates()  # writes the initial plan of the active document
    gui.run_document()  # manualis 3 pages DONE

    make_pdf(job.pdf_dir / MANUALIS, pages=4)
    manualis = next(row for row in gui.documents() if row.name == MANUALIS)

    assert manualis.status == pagejob.DOC_STATUS_STALE
    assert manualis.pages_label == "4 (stored 3)"
    assert manualis.status_text == "CONFIG STALE (stored: 3, current: 4)"
    assert "CONFIG STALE" in manualis.config_status
    # nothing was rewritten: the mapping still has three pages
    assert [mapping.job_id for mapping in gui.mapping_rows()] == [
        "manualis_p001",
        "manualis_p002",
        "manualis_p003",
    ]

    report = gui.reconcile_document(MANUALIS)

    assert report["added"] == [4] and report["removed"] == []
    assert [row.job_id for row in gui.mapping_rows()] == [
        "manualis_p001",
        "manualis_p002",
        "manualis_p003",
        "manualis_p004",
    ]
    assert states_of(gui, MANUALIS) == [state.DONE, state.DONE, state.DONE, state.WAITING]
    assert gui.document_row(MANUALIS).status == pagejob.DOC_STATUS_OK
    assert states_of(gui, APPENDIX) == [state.WAITING] * 3  # the other PDF is untouched


def test_a_missing_pdf_is_reported_and_recovers(gui, job, adapter, make_pdf):
    gui.run_document()  # manualis DONE
    gui.select_document(APPENDIX)
    gui.run_document()  # appendix DONE
    (job.pdf_dir / APPENDIX).unlink()

    rows = gui.documents()
    appendix = next(row for row in rows if row.name == APPENDIX)

    assert appendix.missing is True
    assert appendix.status == pagejob.DOC_STATUS_MISSING
    assert appendix.pages_label == "---"
    assert appendix.queue_status == "DONE 3"  # state kept, nothing deleted
    assert names(rows) == [MANUALIS, APPENDIX]

    calls_before = len(adapter.calls)
    summary = gui.run_all_enabled()

    assert len(adapter.calls) == calls_before  # nothing ran: all 6 pages are DONE
    assert summary.counts["DONE"] == 6
    assert summary.counts["ERROR"] == 0
    # the missing document stays part of the report (its history is intact)
    appendix_row = next(row for row in summary.documents if row["pdf"] == APPENDIX)
    assert appendix_row["counts"]["DONE"] == 3
    assert any("MISSING PDF" in " ".join(check.detail.split()) for check in gui.validate())

    make_pdf(job.pdf_dir / APPENDIX, pages=3)
    gui.select_document(APPENDIX)

    appendix = gui.document_row(APPENDIX)
    assert appendix.missing is False
    assert states_of(gui, APPENDIX) == [state.DONE] * 3  # plan and states survived
    assert adapter.pages_run() == [1, 2, 3, 1, 2, 3]  # nothing ran again after the recovery


def test_validation_reports_documents_and_output_collisions(gui, job):
    checks = gui.validate()
    documents = [check for check in checks if check.name == "Dokumenti"]

    assert documents and "2 PDF" in documents[0].detail
    assert all(check.ok for check in checks if check.name == "Output dublikāti")
    assert gui.can_run() is True

    # a hand edited plan that maps appendix page 1 onto manualis' automatic output
    # name: two documents would write one AI, which must never start a run
    gui.select_document(APPENDIX)
    gui.auto_assign_templates()
    config = cfg.load_config(job.config_path)
    cfg.document_for(config, APPENDIX)["pages"][0]["output"] = "manualis__001.ai"
    cfg.save_config(job.config_path, config)
    gui.queue.build_queue()

    checks = gui.validate()
    collisions = [check for check in checks if check.name == "Output dublikāti"]
    assert collisions and collisions[0].ok is False
    assert "manualis__001.ai" in collisions[0].detail
    assert gui.can_run() is False
