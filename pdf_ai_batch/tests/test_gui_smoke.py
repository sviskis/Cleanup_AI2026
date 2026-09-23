"""Window smoke test: the tabs build and the wiring works (no Illustrator).

Skipped automatically when no display is available (CI / headless shell).
"""

from __future__ import annotations

import logging

import pytest

tkinter = pytest.importorskip("tkinter")

from pdf_ai_batch.core.project import JobProject  # noqa: E402
from pdf_ai_batch.gui import main_window  # noqa: E402


@pytest.fixture()
def window():
    try:
        app = main_window.MainWindow()
    except tkinter.TclError as exc:  # pragma: no cover - headless
        pytest.skip(f"nav displeja: {exc}")
    app.withdraw()  # keep the test window off the screen
    yield app
    app.bus.close()
    try:
        app.destroy()
    except tkinter.TclError:
        pass  # the test closed the window itself (on_close)


def test_window_builds_the_four_tabs_without_touching_illustrator(window):
    labels = [window.notebook.tab(tab, "text") for tab in window.notebook.tabs()]
    assert labels == ["PROJECT", "PDF", "MAPPING", "RUN / LOG"]
    assert window.title() == "Cleanup AI 2026"
    assert window.controller.project is None
    assert window.controller._adapter is None  # opening the GUI needs no COM
    assert "Cleanup AI 2026" in window.status["text"]


def test_window_close_stops_the_event_pump(window):
    assert window._pump_id is not None

    window.on_close()  # nothing is running, so it closes without asking

    assert window._pump_id is None
    assert window.bus.closed is True


def test_opening_a_job_fills_the_tabs(window, tmp_path, make_pdf):
    project = JobProject.open(tmp_path / "JOB")
    make_pdf(project.pdf_dir / "manual.pdf", pages=3)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nx\n")

    window.controller.open_project(project.root)
    window.refresh_all()

    folders = window.project_tab.tree.get_children()
    assert len(folders) == 6
    assert window.project_tab.tree.item(folders[0], "values")[0] == "PDF"

    rows = window.mapping_tab.tree.get_children()
    assert [window.mapping_tab.tree.item(row, "values")[1] for row in rows] == ["001", "002", "003"]
    first = window.mapping_tab.tree.item(rows[0], "values")
    assert first[0] == "[x]" and first[5] == "WAITING"
    assert window.run_tab.current["text"].endswith("/ 003")
    assert "manual.pdf" in window.run_tab.current["text"]


def test_pdf_tab_follows_the_controller_active_document(window, tmp_path, make_pdf):
    """Switching the document must not be reverted by the PDF tab's own selection."""
    project = JobProject.open(tmp_path / "JOB")
    make_pdf(project.pdf_dir / "alpha.pdf", pages=2)
    make_pdf(project.pdf_dir / "beta.pdf", pages=3)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nx\n")

    window.controller.open_project(project.root)
    window.refresh_all()
    assert window.controller.active_pdf.name == "alpha.pdf"  # natural order picks it

    window.controller.select_document("beta.pdf")
    window.refresh_all()

    assert window.controller.active_pdf.name == "beta.pdf"
    assert window.pdf_tab.tree.selection() == ("beta.pdf",)
    assert "beta.pdf" in window.mapping_tab.document_label["text"]
    assert len(window.mapping_tab.tree.get_children()) == 3

    # ... and clicking a row still switches the controller the other way round
    window.pdf_tab.tree.selection_set("alpha.pdf")
    window.pdf_tab.on_use()
    window.refresh_all()

    assert window.controller.active_pdf.name == "alpha.pdf"
    assert len(window.mapping_tab.tree.get_children()) == 2


def test_mapping_actions_keep_the_row_selection(window, tmp_path, make_pdf):
    """A refresh must not drop the selection (RESET then RUN SELECTED has to work)."""
    project = JobProject.open(tmp_path / "JOB")
    make_pdf(project.pdf_dir / "manual.pdf", pages=3)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nx\n")
    window.controller.open_project(project.root)
    window.refresh_all()

    tree = window.mapping_tab.tree
    tree.selection_set(tree.get_children()[1])
    assert window.mapping_tab.selected_job_ids() == ["manual_p002"]

    window.mapping_tab.on_reset()          # refreshes the table
    window.refresh_all()

    assert window.mapping_tab.selected_job_ids() == ["manual_p002"]
    assert window.mapping_tab.selected_pages() == [2]


def test_log_records_and_task_results_reach_the_log_view(window):
    import time

    logging.getLogger("pdf_ai_batch.gui").info("testa ziņa 123")
    window._pump()  # deterministic instead of waiting for the timer
    assert "testa ziņa 123" in window.run_tab.log.get("1.0", tkinter.END)

    def slow_task(progress):
        time.sleep(0.2)  # so "busy" is observable, like a real batch
        progress("solis")
        return "rezultāts 42"

    assert window.run_task("TESTA DARBS", slow_task) is True
    assert window.runner.busy is True
    assert str(window.run_tab._buttons[0]["state"]) == "disabled"  # actions locked while running
    window.runner.join(timeout=5)
    window._pump()

    text = window.run_tab.log.get("1.0", tkinter.END)
    assert "TESTA DARBS sākts" in text
    assert "solis" in text
    assert "rezultāts 42" in text
    assert window.runner.busy is False
    assert str(window.run_tab._buttons[0]["state"]) == "normal"


def test_run_without_a_job_reports_a_clear_error(window, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(main_window.messagebox, "showerror", lambda *a, **k: shown.append(a))

    window.run_tab.on_run_all()

    assert shown  # validation problems are shown, nothing is started
    assert window.runner.busy is False
    assert "JOB" in " ".join(str(part) for part in shown[0])