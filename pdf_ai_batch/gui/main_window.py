"""The Tk main window: four tabs, the event pump and close safety.

Threading model (see docs/GUI.md): the Tk main thread only builds widgets,
`_pump()` renders events from the worker thread, and every long action runs through
`TaskRunner` in a worker thread. Opening the window never launches Illustrator.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from .. import __version__
from ..logging_setup import configure_console, setup_logging
from . import APP_TITLE, LOG_POLL_MS, MIN_HEIGHT, MIN_WIDTH, tasks
from .context import GuiContext
from .controller import AppController
from .mapping_tab import MappingTab
from .pdf_tab import PdfTab
from .project_tab import ProjectTab
from .run_tab import RunTab

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
GUI_HANDLER_NAME = "gui-view"


class MainWindow(tk.Tk):
    """Cleanup AI 2026 main window."""

    def __init__(
        self,
        *,
        controller: AppController | None = None,
        adapter_factory: Callable[[], object] | None = None,
    ) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.geometry(f"{MIN_WIDTH}x{MIN_HEIGHT}")

        self.bus = tasks.EventBus()
        self.runner = tasks.TaskRunner(self.bus)
        self.controller = controller or AppController(adapter_factory=adapter_factory)
        self._job_log_dir = None

        setup_logging(None, console=False)  # per JOB file logging starts on open
        self._attach_log_handler()

        self.ctx = GuiContext(
            controller=self.controller,
            set_status=self.set_status,
            append_log=self.append_log,
            refresh=self.refresh_all,
            run_task=self.run_task,
            busy=lambda: self.runner.busy,
            window=self,
        )
        self._build()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._pump_id = self.after(LOG_POLL_MS, self._pump)
        self.set_status(f"{APP_TITLE} {__version__} gatavs - atver vai izveido JOB (PROJECT tab)")

    # ------------------------------------------------------------------ widgets

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.project_tab = ProjectTab(self.notebook, self.ctx)
        self.pdf_tab = PdfTab(self.notebook, self.ctx)
        self.mapping_tab = MappingTab(self.notebook, self.ctx)
        self.run_tab = RunTab(self.notebook, self.ctx)
        self.run_tab.selection_provider = self.mapping_tab.selected_job_ids

        for tab, label in (
            (self.project_tab, "PROJECT"),
            (self.pdf_tab, "PDF"),
            (self.mapping_tab, "MAPPING"),
            (self.run_tab, "RUN / LOG"),
        ):
            self.notebook.add(tab, text=label)

        status_bar = ttk.Frame(self, padding=(8, 4))
        status_bar.grid(row=1, column=0, sticky="ew")
        status_bar.columnconfigure(0, weight=1)
        self.status = ttk.Label(status_bar, text="", anchor="w")
        self.status.grid(row=0, column=0, sticky="ew")
        self.busy_status = ttk.Label(status_bar, text="", anchor="e", foreground="#0b5cad")
        self.busy_status.grid(row=0, column=1, sticky="e")

        self.refresh_all()

    # --------------------------------------------------------------------- log

    def _attach_log_handler(self) -> None:
        """Attach the GUI log view to the package logger (files stay canonical)."""
        logger = logging.getLogger("pdf_ai_batch")
        for handler in list(logger.handlers):
            if getattr(handler, "name", "") == GUI_HANDLER_NAME:
                logger.removeHandler(handler)
        handler = tasks.QueueLogHandler(self.bus, level=logging.INFO)
        handler.name = GUI_HANDLER_NAME
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        logger.addHandler(handler)

    def append_log(self, text: str) -> None:
        self.run_tab.append_log(text)

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def _ensure_job_logging(self) -> None:
        """Once a JOB is open, write the canonical logs into JOB/LOG."""
        project = self.controller.project
        if project is None or project.log_dir == self._job_log_dir:
            return
        setup_logging(project.log_dir, console=False, batch_log=True)
        self._attach_log_handler()  # setup_logging replaces the handler list
        self._job_log_dir = project.log_dir

    # ------------------------------------------------------------ event pump

    def _pump(self) -> None:
        """Render worker events on the Tk thread (the only place widgets change)."""
        for event in self.bus.drain():
            if event.kind == tasks.EVENT_LOG:
                self.append_log(str(event.payload))
            elif event.kind == tasks.EVENT_PROGRESS:
                outcome = event.payload
                line = outcome.line() if hasattr(outcome, "line") else str(outcome)
                self.append_log(line)
                self.run_tab.update_progress()
                self.mapping_tab.refresh()
            elif event.kind == tasks.EVENT_DONE:
                self._on_task_done(event.payload)
            elif event.kind == tasks.EVENT_ERROR:
                self.run_tab.show_error(event.payload)
        self._render_busy()
        self._pump_id = self.after(LOG_POLL_MS, self._pump)

    def _on_task_done(self, payload: Any) -> None:
        from ..core.queue import BatchSummary

        if isinstance(payload, BatchSummary):
            self.run_tab.show_summary(payload)
            self.append_log("Darbs pabeigts")
            self.set_status(f"Pabeigts: {payload.format().splitlines()[0]}")
            self.refresh_all()
        elif isinstance(payload, tuple) and len(payload) == 2 and isinstance(payload[0], bool):
            self.run_tab.show_health(payload)
            self.refresh_all()
        elif payload is not None:
            self.append_log(str(payload))

    def _render_busy(self) -> None:
        busy = self.runner.busy
        for tab in (self.project_tab, self.pdf_tab, self.mapping_tab):
            tab.set_busy(busy)
        self.run_tab.set_busy(busy, f"Notiek: {self.runner.label}" if busy else "")
        self.busy_status.configure(text=f"Notiek: {self.runner.label}" if busy else "")

    # ------------------------------------------------------------------- tasks

    def run_task(self, label: str, task: Callable[[Any], Any]) -> bool:
        """Start `task(progress)` in a worker thread (False when one is running)."""
        if not self.runner.start(label, task):
            return False
        self.append_log(f"--- {label} sākts ---")
        self.set_status(f"Notiek: {label}")
        self._render_busy()
        return True

    def refresh_all(self) -> None:
        """Rebuild every tab from the controller (never from GUI-owned state)."""
        self._ensure_job_logging()
        if self.controller.project is not None:
            # opening a JOB must show the project queue (both PDFs, states included)
            self.controller.ensure_queue_built()
        for tab in (self.project_tab, self.pdf_tab, self.mapping_tab, self.run_tab):
            refresh = getattr(tab, "refresh", None)
            if callable(refresh):
                refresh()
        self.run_tab.update_progress()

    # ------------------------------------------------------------------- close

    def on_close(self) -> None:
        """Warn when a page is still RUNNING; recovery stays authoritative."""
        if self.runner.busy or self.controller.has_running_items():
            proceed = messagebox.askyesno(
                "Aizvērt logu?",
                "Notiek darbs vai lapa ir stāvoklī RUNNING.\n\n"
                "Ja aizver tagad, lapa paliks RUNNING un nākamajā palaišanā kļūs INTERRUPTED "
                "(to var pabeigt ar CONTINUE). Illustratoris netiks aizvērts ar varu.\n\n"
                "Aizvērt logu?",
                parent=self,
            )
            if not proceed:
                return
            self.append_log("Logs tiek aizvērts darba laikā - lapa kļūs INTERRUPTED")
        if self._pump_id is not None:
            try:
                self.after_cancel(self._pump_id)  # no stray "invalid command name ..._pump"
            except Exception:  # noqa: BLE001 - the window may already be gone
                pass
            self._pump_id = None
        self.bus.close()
        self.destroy()


def launch(argv: list[str] | None = None) -> int:
    """Create the window and run the Tk main loop."""
    configure_console()
    window = MainWindow()
    window.mainloop()
    return 0