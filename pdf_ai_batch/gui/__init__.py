"""Cleanup AI 2026 - Tkinter GUI (milestone 3).

A thin presentation layer over the proven core:

    gui/main_window.py   the window, the tabs, the event pump, close safety
    gui/controller.py    all GUI logic, NO Tk and NO COM (fully testable)
    gui/tasks.py         worker thread + event queue bridge (no Tk imports)
    gui/project_tab.py   JOB folders, new/open project, add PDF/templates
    gui/pdf_tab.py       PDF list, page count, config status
    gui/mapping_tab.py   per page template/layer/output/status, validation
    gui/preview_panel.py thumbnails + large preview + page info (display only)
    gui/preview_loader.py background PDF renders (worker thread, generations)
    gui/run_tab.py       run/continue/retry, progress, live log

Rules (see .clinerules and docs/GUI.md):

* the GUI never touches win32com, JSX or state.json directly - everything goes
  through `gui/controller.py` and then the core modules (`core/*`, adapter)
* PDF rendering happens in `pdf_ai_batch/preview` (PyMuPDF); the GUI only draws the
  PNG bytes it receives through the event bus - never a COM call, never Illustrator
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
#: while a batch runs the mapping rows/thumbnails are refreshed this often, so the
#: page being processed is visibly RUNNING (progress events only arrive afterwards)
LIVE_STATE_REFRESH_SECONDS = 0.5


def run_gui(argv: list[str] | None = None) -> int:
    """Launch the GUI (imported lazily so CLI-only use needs no Tk).

    A packaged build first makes sure there is a writable application log folder
    (`<install>/logs` or `%LOCALAPPDATA%/Cleanup AI 2026/logs`) and writes one startup
    record with the version, the executable and the result of the asset checks - so a
    production start is diagnosable even before a JOB is open. Once a JOB is open the
    canonical logs are its `JOB/LOG` files (see `MainWindow._ensure_job_logging`).
    """
    from .. import paths

    if paths.is_frozen():
        from .. import __version__, diagnostics
        from ..logging_setup import setup_logging

        logger = setup_logging(paths.log_dir(), console=False)
        report = diagnostics.run_diagnostics(check_illustrator=False)
        logger.info(
            "Cleanup AI 2026 %s start | exe=%s | instalācija=%s | pārbaudes=%s | "
            "kļūdas=%s | brīdinājumi=%s",
            __version__,
            paths.executable_path(),
            paths.app_root(),
            len(report.items),
            report.errors or "-",
            report.warnings or "-",
        )

    from .main_window import launch

    return launch(argv)


__all__ = [
    "APP_TITLE",
    "LIVE_STATE_REFRESH_SECONDS",
    "MIN_WIDTH",
    "MIN_HEIGHT",
    "LOG_POLL_MS",
    "run_gui",
]
