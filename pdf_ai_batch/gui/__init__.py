"""Cleanup AI 2026 - Tkinter GUI (milestone 3).

A thin presentation layer over the proven core:

    gui/main_window.py   the window, the tabs, the event pump, close safety
    gui/controller.py    all GUI logic, NO Tk and NO COM (fully testable)
    gui/tasks.py         worker thread + event queue bridge (no Tk imports)
    gui/project_tab.py   JOB folders, new/open project, add PDF/templates
    gui/pdf_tab.py       PDF list, page count, config status
    gui/mapping_tab.py   per page template/layer/output/status, validation
    gui/run_tab.py       run/continue/retry, progress, live log

Rules (see .clinerules and docs/GUI.md):

* the GUI never touches win32com, JSX or state.json directly - everything goes
  through `gui/controller.py` and then the core modules (`core/*`, adapter)
* long work (a batch) runs in a worker thread; the Tk main thread only updates
  widgets, fed by a `queue.Queue` + `root.after(...)` poll
* the GUI log view is a VIEW: the canonical logs stay in JOB/LOG/*.log
* opening the GUI never launches Illustrator; that happens only for an explicit
  health check or a run
"""

from __future__ import annotations

APP_TITLE = "Cleanup AI 2026"
MIN_WIDTH = 1020
MIN_HEIGHT = 660
LOG_POLL_MS = 120


def run_gui(argv: list[str] | None = None) -> int:
    """Launch the GUI (imported lazily so CLI-only use needs no Tk)."""
    from .main_window import launch

    return launch(argv)


__all__ = ["APP_TITLE", "MIN_WIDTH", "MIN_HEIGHT", "LOG_POLL_MS", "run_gui"]
