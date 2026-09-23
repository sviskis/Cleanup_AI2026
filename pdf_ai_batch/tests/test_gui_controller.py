"""GUI controller tests: the whole GUI logic, no display, no Illustrator.

The controller is the only layer the widgets talk to, so testing it here covers
every GUI action: project handling, page count, mapping rows, config edits, the
queue calls behind the RUN buttons, progress and validation. A fake Illustrator
adapter is injected, exactly like the queue tests do.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_ai_batch.core import config as cfg
from pdf_ai_batch.core import state
from pdf_ai_batch.core.project import JobProject
from pdf_ai_batch.gui import controller
from pdf_ai_batch.tests.fakes import FakeIllustrator

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def adapter() -> FakeIllustrator:
    return FakeIllustrator()


@pytest.fixture()
def job(tmp_path, make_pdf) -> JobProject:
    """A real JOB folder with a 4 page PDF and a MASTER template."""
    project = JobProject.open(tmp_path / "GUI_JOB")
    make_pdf(project.pdf_dir / "manual.pdf", pages=4)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nMASTER template\n")
    return project


@pytest.fixture()
def gui(job, adapter) -> controller.AppController:
    app = controller.AppController(adapter_factory=lambda: adapter)
    app.open_project(job.root)
    app.select_pdf("manual.pdf")
    return app


def states_of(app: controller.AppController) -> list[str]:
    return [row.state for row in app.mapping_rows()]


def test_new_project_creates_the_structure_and_populates_the_model(tmp_path):
    app = controller.AppController()
    project = app.new_project(tmp_path / "NEW_JOB")

    assert project.root.is_dir()
    labels = [label for label, _path, _exists in app.project_folders()]
    assert labels == ["PDF", "TEMPLATE", "CONFIG", "AI_OUT", "LOG", "ERROR"]
    assert all(exists for _label, _path, exists in app.project_folders())
    assert app.active_pdf is None  # no PDF yet, nothing is selected


def test_open_project_and_add_pdf_and_templates(gui, job, tmp_path, make_pdf):
    outside_pdf = make_pdf(tmp_path / "outside.pdf", pages=2)
    outside_template = tmp_path / "extra_template.ai"
    outside_template.write_bytes(b"%PDF-1.5\nextra\n")

    added_pdf, skipped_pdf = gui.add_pdf([outside_pdf])
    added_tpl, skipped_tpl = gui.add_templates([outside_template, "not_a_template.txt"])

    assert added_pdf == ["outside.pdf"] and skipped_pdf == []
    assert added_tpl == ["extra_template.ai"] and skipped_tpl == ["not_a_template.txt"]
    assert (job.pdf_dir / "outside.pdf").is_file()
    assert [path.name for path in gui.list_pdfs()] == ["manual.pdf", "outside.pdf"]
    # adding the same file twice is reported, not an error
    assert gui.add_pdf([outside_pdf]) == ([], ["outside.pdf"])


def test_pdf_selection_reports_page_count_and_config_status(gui, make_pdf, job):
    entry = gui.select_pdf("manual.pdf")

    assert entry.name == "manual.pdf"
    assert entry.page_count == 4
    assert entry.count_method == "PyMuPDF"  # pdf_info stays authoritative
    assert entry.size_bytes > 0
    assert "autom" in entry.config_status  # no config yet -> automatic plan

    assert gui.select_pdf(str(job.pdf_dir / "manual.pdf")).page_count == 4
    with pytest.raises(controller.ControllerError):
        gui.select_pdf("missing.pdf")


def test_mapping_rows_come_from_the_plan_and_the_queue_state(gui, adapter):
    rows = gui.mapping_rows()

    assert [row.page for row in rows] == [1, 2, 3, 4]
    assert [row.page_label for row in rows] == ["001", "002", "003", "004"]
    assert all(row.template == "MASTER_AI_TEMPLATE.ai" for row in rows)
    assert all(row.layer == "ARTWORK" for row in rows)
    assert [row.output for row in rows] == [
        "manual__001.ai",
        "manual__002.ai",
        "manual__003.ai",
        "manual__004.ai",
    ]
    assert all(row.state == state.WAITING for row in rows)
    assert all(row.use_label == "[x]" for row in rows)

    adapter.script[1] = "error"
    gui.run_selected(["manual_p001"])

    assert states_of(gui) == [state.ERROR, state.WAITING, state.WAITING, state.WAITING]
    assert "testa kļūda" in gui.mapping_rows()[0].detail


def test_enable_and_disable_selected_persists_in_config_and_state(gui):
    rows = gui.set_enabled([2, 3], False)

    assert [row.enabled for row in rows] == [True, False, False, True]
    assert [row.use_label for row in rows] == ["[x]", "[ ]", "[ ]", "[x]"]

    config = cfg.load_config(gui.project.config_path)
    enabled = {entry["page"]: entry["enabled"] for entry in cfg.page_entries(config)}
    assert enabled == {1: True, 2: False, 3: False, 4: True}

    items = {item.page: item for item in gui.queue.document.items}
    assert items[2].enabled is False
    assert items[2].runnable is False

    with pytest.raises(controller.ControllerError):
        gui.set_enabled([], True)


def test_assign_template_and_use_default_persist_through_config(gui, job):
    (job.template_dir / "001_cover.ai").write_bytes(b"%PDF-1.5\ncover\n")
    (job.template_dir / "003_special.ai").write_bytes(b"%PDF-1.5\nspecial\n")

    rows = gui.assign_template([3], "003_special.ai")

    assert rows[0].template == "001_cover.ai"        # automatic positional mapping
    assert rows[2].template == "003_special.ai"      # explicit assignment wins
    assert rows[3].template == "MASTER_AI_TEMPLATE.ai"  # beyond the pool -> default
    config = cfg.load_config(gui.project.config_path)
    assert cfg.page_entries(config)[2]["template"] == "003_special.ai"
    items = {item.page: item for item in gui.queue.document.items}
    assert items[3].template.endswith("003_special.ai")  # merged into state.json

    assert gui.use_default_template([3])[2].template == "MASTER_AI_TEMPLATE.ai"
    config = cfg.load_config(gui.project.config_path)
    assert cfg.page_entries(config)[2]["template"] is None

    with pytest.raises(controller.ControllerError):
        gui.assign_template([1], "003_special.pdf")  # only .ai/.ait are templates


def test_auto_assign_uses_natural_sort_and_never_numbered_mapping_for_master(gui, job):
    for name in ("10_page.ai", "2_page.ai", "MASTER_TEMPLATE.ai"):
        (job.template_dir / name).write_bytes(b"%PDF-1.5\nx\n")

    rows = gui.auto_assign_templates()

    assert [row.template for row in rows] == [
        "2_page.ai",            # natural sort: 2 before 10
        "10_page.ai",
        "MASTER_AI_TEMPLATE.ai",  # beyond the pool -> the default template
        "MASTER_AI_TEMPLATE.ai",
    ]
    assert "MASTER_TEMPLATE.ai" not in [row.template for row in rows]
    assert gui.default_template_name() == "MASTER_AI_TEMPLATE.ai"


def test_reset_selected_calls_the_queue_api(gui):
    gui.run_all_enabled()
    assert states_of(gui) == [state.DONE] * 4

    reset = gui.reset_pages(["manual_p002", 3])

    assert reset == ["manual_p002", "manual_p003"]
    assert states_of(gui) == [state.DONE, state.WAITING, state.WAITING, state.DONE]
    with pytest.raises(controller.ControllerError):
        gui.reset_pages(["nope_p999"])


def test_done_and_skipped_are_not_rerun_by_the_run_buttons(gui, adapter):
    gui.run_all_enabled()
    calls_after_first = len(adapter.calls)
    assert calls_after_first == 4

    gui.run_selected([1, 2, 3, 4])
    gui.run_all_enabled()
    gui.continue_queue()

    assert len(adapter.calls) == calls_after_first  # nothing was rerun
    assert states_of(gui) == [state.DONE] * 4


def test_run_selected_only_runs_the_selection(gui, adapter):
    summary = gui.run_selected(["manual_p002"])

    assert adapter.pages_run() == [2]
    assert [outcome.state_name for outcome in summary.outcomes] == [state.DONE]
    assert states_of(gui) == [state.WAITING, state.DONE, state.WAITING, state.WAITING]

    with pytest.raises(controller.ControllerError):
        gui.run_selected([])


def test_retry_errors_and_retry_interrupted_use_the_queue_api(gui, adapter):
    adapter.script[2] = "error"
    gui.run_all_enabled()
    assert states_of(gui)[1] == state.ERROR

    adapter.script[2] = None
    summary = gui.retry_errors()
    assert summary.counts["DONE"] == 4
    assert states_of(gui) == [state.DONE] * 4
    assert adapter.pages_run().count(2) == 2  # the failed page really ran again

    # an INTERRUPTED item (as after a crash) is resumed through the queue
    item = gui.queue.document.find("manual_p003")
    gui.queue.document.replace_item(state.mark_running(item, "run-crash"))
    gui.queue.save()
    assert states_of(gui)[2] == state.RUNNING

    gui.refresh()  # reload_from_disk never recovers on its own
    assert states_of(gui)[2] == state.RUNNING
    gui.queue.recover_running()
    assert states_of(gui)[2] == state.INTERRUPTED
    assert gui.has_running_items() is False
    assert gui.retry_interrupted().counts["DONE"] == 4
    assert states_of(gui) == [state.DONE] * 4


def test_has_running_items_follows_the_state(gui):
    gui.queue.build_queue(pdf="manual.pdf")
    assert gui.has_running_items() is False
    item = gui.queue.document.find("manual_p001")
    gui.queue.document.replace_item(state.mark_running(item, "run-x"))
    gui.queue.save()

    assert gui.has_running_items() is True
    assert gui.progress().running_page == 1


def test_progress_summary_derives_from_the_queue_state(gui, adapter):
    snapshot = gui.progress()
    assert snapshot.total == 4 and snapshot.processed == 0
    assert snapshot.current_label() == "Page --- / 004"
    assert snapshot.fraction == 0.0

    adapter.script[4] = "skip"
    gui.run_all_enabled()
    snapshot = gui.progress()

    assert snapshot.counts[state.DONE] == 3
    assert snapshot.counts[state.SKIPPED] == 1
    assert snapshot.processed == 4
    assert snapshot.fraction == 1.0
    assert snapshot.current_label() == "Page 004 / 004"
    assert "DONE: 3" in snapshot.summary_lines()


def test_validation_reports_human_readable_problems(gui, job):
    assert gui.can_run() is True
    assert "kļūdas=0" in gui.validation_report()

    # a lost per page template: the plan still builds, the check must flag the file
    (job.template_dir / "003_special.ai").write_bytes(b"%PDF-1.5\nspecial\n")
    gui.assign_template([3], "003_special.ai")
    (job.template_dir / "003_special.ai").unlink()

    checks = gui.validate()
    assert gui.can_run() is False
    failures = " ".join(gui.validation_failures())
    assert "003_special.ai" in failures
    assert "nav atrasts" in failures
    assert any(not check.ok for check in checks)

    # the default template gone as well: the plan itself cannot be built
    master = job.template_dir / "MASTER_AI_TEMPLATE.ai"
    hidden = master.with_suffix(".ai.hidden")
    master.rename(hidden)
    gui.validate()
    assert gui.can_run() is False
    assert any("template" in failure.lower() for failure in gui.validation_failures())

    hidden.rename(master)
    (job.template_dir / "003_special.ai").write_bytes(b"%PDF-1.5\nspecial\n")
    gui.validate()
    assert gui.can_run() is True


def test_mapping_rows_report_a_clear_error_without_a_pdf(tmp_path):
    app = controller.AppController()
    app.open_project(tmp_path / "EMPTY_JOB")

    with pytest.raises(controller.ControllerError):
        app.mapping_rows()
    assert app.can_run() is False
    failures = " ".join(app.validation_failures())
    assert "PDF" in failures


def test_project_folders_are_listed_with_their_state(gui):
    folders = gui.project_folders()
    assert [label for label, _path, _exists in folders] == ["PDF", "TEMPLATE", "CONFIG", "AI_OUT", "LOG", "ERROR"]
    assert all(exists for _label, _path, exists in folders)
    assert all(Path(path).is_absolute() for _label, path, _exists in folders)


def test_gui_python_sources_never_touch_com_tk_or_state_files_directly():
    """ARCHITECTURE RULE: GUI -> controller/core -> adapter, never win32com/JSX."""
    import re

    gui_dir = REPO_ROOT / "pdf_ai_batch" / "gui"
    sources = {path.name: path.read_text(encoding="utf-8") for path in gui_dir.glob("*.py")}
    assert "controller.py" in sources and "tasks.py" in sources

    import_pattern = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", re.MULTILINE)
    for name, source in sources.items():
        modules = set(import_pattern.findall(source))
        assert not any(module.startswith(("win32com", "pythoncom")) for module in modules), (name, modules)
        assert "DoJavaScriptFile" not in source, name          # only the adapter drives the worker
        assert "write_json_atomic" not in source, name         # no direct JSON writing
        assert "state.save_state(" not in source, name         # no direct state mutation

    # the controller and the task bridge are Tk free (and therefore testable)
    for name in ("controller.py", "tasks.py"):
        modules = set(import_pattern.findall(sources[name]))
        assert not any(module.startswith("tkinter") for module in modules), name