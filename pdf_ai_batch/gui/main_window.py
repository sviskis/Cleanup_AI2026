"""The main window: the dark shell, the four sections, the event pump, close safety.

The shell is the mockup's layout (see `gui/shell.py` for the widgets and `gui/theme.py`
for the palette):

    +--------------------------------------------------------------+ +-------------+
    | project name   |  status chips  |  operator / version          | | REVIEW      |
    +--------------------------------------------------------------+ | PLAN        |
    | PROJECT | PDF | MAPPING | RUN / LOG        (accent underline)    | | LOOP        |
    +---------+------------------------------------------+-----------+ | PROJECT     |
    | sidebar | review question + 3 advisor cards         | actions   | | REPORTS     |
    | 1..4    | ----------------------------------------- | grouped   | | MONITORING  |
    |         | the visible section (the proven tab)      | by section| |             |
    +---------+------------------------------------------+-----------+ +-------------+
    | status line                                            busy label |
    +------------------------------------------------------------------+

Threading model (see docs/GUI.md): the Tk main thread only builds widgets,
`_pump()` renders events from the worker thread, and every long action runs through
`TaskRunner` in a worker thread. Opening the window never launches Illustrator.
"""

from __future__ import annotations

import getpass
import logging
import time
import tkinter
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from .. import __version__
from ..core import report as report_module
from ..core import state
from ..logging_setup import configure_console, setup_logging
from . import (
    APP_TITLE,
    LIVE_STATE_REFRESH_SECONDS,
    LOG_POLL_MS,
    MIN_HEIGHT,
    MIN_WIDTH,
    shell,
    tasks,
    theme,
)
from .context import GuiContext
from .controller import AppController, ControllerError, ProgressSnapshot
from .mapping_tab import MappingTab
from .pdf_tab import PdfTab
from .preview_loader import PreviewLoader
from .project_tab import ProjectTab
from .run_tab import RunTab

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
GUI_HANDLER_NAME = "gui-view"

#: the four workflow sections - the sidebar items AND the tab row show the same ones,
#: so the numbers of the mockup and the proven tab labels stay in one place
SECTIONS = (
    ("project", "1", "PROJECT"),
    ("pdf", "2", "PDF"),
    ("mapping", "3", "MAPPING"),
    ("run", "4", "RUN / LOG"),
)

#: the status chips of the top bar (centre block)
CHIPS = (
    ("job", "JOB"),
    ("documents", "PDF"),
    ("plan", "PLĀNS"),
    ("queue", "RINDA"),
    ("illustrator", "ILLUSTRATOR"),
)

#: the three advisor cards (the mockup's three columns with a coloured dot)
ADVISORS = (
    ("plan", "PLĀNS"),
    ("queue", "RINDA"),
    ("illustrator", "ILLUSTRATOR"),
)

#: the right action panel: the mockup's groups, filled with the actions that exist
ACTIONS = (
    ("review", "Review"),
    ("plan", "Plan"),
    ("loop", "Loop"),
    ("project", "Project"),
    ("reports", "Reports"),
    ("monitoring", "Monitoring"),
)

#: the question the review bar asks (the answer comes from the core's validation)
REVIEW_QUESTION = "Vai plāns ir gatavs palaišanai?"



class MainWindow(ctk.CTk):
    """Cleanup AI 2026 main window (dark shell, four sections)."""

    def __init__(
        self,
        *,
        controller: AppController | None = None,
        adapter_factory: Callable[[], object] | None = None,
    ) -> None:
        theme.apply_theme()
        super().__init__(fg_color=theme.COLORS["bg"])
        # Build the finished window first: no white flash on startup. Must NOT go
        # through CTk.withdraw(): it sets `_withdraw_called_before_window_exists`,
        # and CTk.mainloop() then skips its own deiconify(), so the window stayed
        # invisible (WS_VISIBLE off) for the whole session. The base implementation
        # hides the window the same way without that flag; deiconify() below shows it.
        tkinter.Tk.withdraw(self)
        theme.apply_theme(self)

        self.title(APP_TITLE)
        self.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.geometry(f"{MIN_WIDTH}x{MIN_HEIGHT}")

        self.bus = tasks.EventBus()
        self.runner = tasks.TaskRunner(self.bus)
        self.controller = controller or AppController(adapter_factory=adapter_factory)
        #: background PDF renders (thumbnails + previews); never touches widgets
        self.preview_loader = PreviewLoader(self.controller.preview_cache(), bus=self.bus)
        self._job_log_dir = None
        self._live_refresh_at = 0.0
        #: the four section widgets by key; both navigations switch between them
        self._sections: dict[str, Any] = {}
        self._active_section = ""

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
            preview_loader=self.preview_loader,
        )
        self._build()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._pump_id = self.after(LOG_POLL_MS, self._pump)
        self.set_status(f"{APP_TITLE} {__version__} gatavs - atver vai izveido JOB (PROJECT)")
        self.show_section("project")
        self._refresh_shell()
        self.update_idletasks()
        self.deiconify()

    # ------------------------------------------------------------------ widgets

    def _build(self) -> None:
        """The whole shell: top bar, tab row, sidebar, cards, sections, actions."""
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self.topbar = shell.TopBar(self, chips=CHIPS)
        self.topbar.grid(row=0, column=0, sticky="ew")
        theme.Divider(self).grid(row=1, column=0, sticky="ew")

        self.tabrow = shell.TabRow(self, on_select=self.show_section)
        self.tabrow.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 0))

        body = theme.Frame(self)
        body.grid(row=3, column=0, sticky="nsew")
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=0)
        body.rowconfigure(0, weight=1)

        self.sidebar = shell.Sidebar(body, title="NAVIGĀCIJA", on_select=self.show_section)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.configure(width=theme.SIDEBAR_WIDTH)
        self.sidebar.grid_propagate(False)

        center = theme.Frame(body)
        center.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        center.columnconfigure(0, weight=1)
        center.rowconfigure(2, weight=1)

        self.review = shell.ReviewBar(center, question=REVIEW_QUESTION)
        self.review.grid(row=0, column=0, sticky="ew")
        self.advisor = shell.AdvisorRow(center, cards=ADVISORS)
        self.advisor.grid(row=1, column=0, sticky="ew", pady=10)
        self.notebook = shell.SectionStack(center, on_change=self._on_section_changed)
        self.notebook.grid(row=2, column=0, sticky="nsew")

        self.actions = shell.ActionPanel(body, title="Darbības", sections=ACTIONS)
        self.actions.grid(row=0, column=2, sticky="nse")
        self.actions.configure(width=theme.ACTION_PANEL_WIDTH)
        self.actions.grid_propagate(False)

        theme.Divider(self).grid(row=4, column=0, sticky="ew")
        self.status_bar = shell.StatusBar(self)
        self.status_bar.grid(row=5, column=0, sticky="ew")
        self.status = self.status_bar.status  # the widgets the rest of the GUI uses
        self.busy_status = self.status_bar.busy_status

        self._build_sections()
        self._fill_actions()
        self.refresh_all()

    def _build_sections(self) -> None:
        """Create the four proven tabs and stack them in the content area."""
        self.project_tab = ProjectTab(self.notebook, self.ctx)
        self.pdf_tab = PdfTab(self.notebook, self.ctx)
        self.mapping_tab = MappingTab(self.notebook, self.ctx)
        self.run_tab = RunTab(self.notebook, self.ctx)
        self.run_tab.selection_provider = self.mapping_tab.selected_job_ids

        for widget, (key, index, label) in zip(
            (self.project_tab, self.pdf_tab, self.mapping_tab, self.run_tab), SECTIONS
        ):
            self._sections[key] = widget
            self.notebook.add(widget, text=label)
            self.sidebar.add(key, label, index=int(index))
            self.tabrow.add(key, label)

    def _fill_actions(self) -> None:
        """The right panel: the proven tab actions, grouped by the mockup's sections.

        Every button calls the handler of the section that owns it - the panel adds no
        logic and no second way to change the plan.
        """
        add = self.actions.add
        # REVIEW - everything that only looks at the JOB
        add("review", "PREFLIGHT PROJECT", self.run_tab.on_preflight, kind="primary")
        add("review", "VALIDATE", self.mapping_tab.on_validate)
        add("review", "HEALTH CHECK", self.run_tab.on_health)
        add("review", "RECONCILE PDF", self.mapping_tab.on_reconcile)
        # PLAN - the mapping of the active document
        add("plan", "ASSIGN TO SELECTED", self.mapping_tab.on_assign_template, kind="primary")
        add("plan", "ASSIGN TO RANGE", self.mapping_tab.on_assign_range)
        add("plan", "USE DEFAULT", self.mapping_tab.on_use_default)
        add("plan", "CLEAR OVERRIDE", self.mapping_tab.on_clear_override)
        add("plan", "AUTO MAP BY NUMBER", self.mapping_tab.on_auto_map_number)
        add("plan", "AUTO ASSIGN TEMPLATES", self.mapping_tab.on_auto_assign)
        add("plan", "COPY MAPPING", self.mapping_tab.on_copy_mapping)
        add("plan", "PASTE MAPPING", self.mapping_tab.on_paste_mapping)
        add("plan", "ENABLE SELECTED", self.mapping_tab.on_enable)
        add("plan", "DISABLE SELECTED", self.mapping_tab.on_disable)
        add("plan", "RESET SELECTED", self.mapping_tab.on_reset)
        # LOOP - the batch loop of the project (overwrite is a run time decision)
        add("loop", "RUN SELECTED", self.run_tab.on_run_selected, kind="accent")
        add("loop", "RUN CURRENT PDF", self.run_tab.on_run_current, kind="primary")
        add("loop", "RUN ALL ENABLED PDFs", self.run_tab.on_run_all, kind="primary")
        add("loop", "CONTINUE PROJECT", self.run_tab.on_continue)
        add("loop", "RETRY PROJECT ERRORS", self.run_tab.on_retry_errors)
        add("loop", "RETRY INTERRUPTED", self.run_tab.on_retry_interrupted)
        loop_section = self.actions.sections["loop"]
        loop_section.add_widget(
            theme.CheckBox(
                loop_section,
                text="Pārrakstīt esošos AI",
                variable=self.run_tab.overwrite_var,
                command=self.run_tab.on_overwrite_toggle,
            )
        )
        # PROJECT - the JOB folder itself
        add("project", "NEW PROJECT", self.project_tab.on_new_project)
        add("project", "OPEN PROJECT", self.project_tab.on_open_project, kind="primary")
        add("project", "ADD PDF", self.project_tab.on_add_pdf)
        add("project", "ADD TEMPLATES", self.project_tab.on_add_templates)
        add("project", "OPEN JOB FOLDER", self.project_tab.on_open_folder)
        # REPORTS - what the passes wrote, plus the plan history
        add("reports", "OPEN REPORT FOLDER", self.on_open_report_folder)
        add("reports", "OPEN LAST REPORT (TXT)", self.on_open_last_report)
        add("reports", "SAVE PRESET", self.mapping_tab.on_save_preset)
        add("reports", "LOAD / APPLY PRESET", self.mapping_tab.on_apply_preset)
        add("reports", "UNDO PLAN CHANGE", self.mapping_tab.on_undo)
        add("reports", "RESTORE SNAPSHOT", self.mapping_tab.on_restore)
        # MONITORING - read only, so these stay live while a batch runs
        add("monitoring", "REFRESH STATUS", self.run_tab.on_refresh, keep_enabled=True)
        add("monitoring", "OPEN JOB LOG", self.on_open_log_folder, keep_enabled=True)
        add("monitoring", "OPEN OUTPUT (DONE)", self.mapping_tab.on_open_output, keep_enabled=True)

    # ------------------------------------------------------------------ navigation

    def show_section(self, key: str) -> None:
        """Show one of the four sections (the sidebar and the tab row both land here)."""
        widget = self._sections.get(key)
        if widget is None:
            return
        self.notebook.select(widget)  # fires _on_section_changed, which highlights both
        self._active_section = key
        self.sidebar.select(key)
        self.tabrow.select(key)

    def _on_section_changed(self, widget: Any) -> None:
        """Keep both navigations in sync when the section is switched another way."""
        key = self._key_for(widget)
        if key is None or key == self._active_section:
            return
        self._active_section = key
        self.sidebar.select(key)
        self.tabrow.select(key)

    def _key_for(self, widget: Any) -> str | None:
        for key, candidate in self._sections.items():
            if candidate is widget:
                return key
        return None


    # ---------------------------------------------------------------- reports/logs

    def on_open_report_folder(self) -> None:
        """REPORTS: open JOB/LOG/reports (written only by `core/report.py`)."""
        project = self.controller.project
        if project is None:
            self.ctx.report("Vispirms atver vai izveido JOB", error=True)
            return
        folder = report_module.reports_dir(project)
        if not folder.is_dir():
            self.ctx.report(f"Reportu mape vēl nav izveidota: {folder}", error=True)
            return
        self._open_folder(folder)

    def on_open_last_report(self) -> None:
        """REPORTS: hand the TXT of the last finished pass to the OS."""
        paths = self.controller.last_report_paths()
        if paths is None:
            self.ctx.report("Nav neviena reporta (JOB/LOG/reports)", error=True)
            return
        try:
            self.ctx.open_file(paths.txt)
        except Exception as exc:  # noqa: BLE001 - opening a file is best effort
            self.ctx.report(f"Reportu nevar atvērt: {exc}", error=True)
            return
        self.ctx.report(f"Atveru reportu: {paths.txt.name}")

    def on_open_log_folder(self) -> None:
        """MONITORING: open JOB/LOG, where the canonical logs live."""
        project = self.controller.project
        if project is None:
            self.ctx.report("Vispirms atver vai izveido JOB", error=True)
            return
        if not project.log_dir.is_dir():
            self.ctx.report(f"Logu mape nav atrasta: {project.log_dir}", error=True)
            return
        self._open_folder(project.log_dir)

    def _open_folder(self, folder: Any) -> None:
        try:
            self.ctx.open_file(folder)
        except Exception as exc:  # noqa: BLE001 - opening a folder is best effort
            self.ctx.report(f"Mapi nevar atvērt: {exc}", error=True)
            return
        self.ctx.report(f"Atveru mapi: {folder}")


    # ------------------------------------------------------------------ shell state

    def _refresh_shell(self) -> None:
        """Keep the top bar, the review bar and the advisor cards true (read only).

        Every number comes from the controller - the shell never counts anything itself,
        and a section that cannot be read yet (no JOB open) simply shows fewer facts.
        """
        project = self.controller.project
        if project is None:
            self.topbar.set_project("(nav atvērts)", "atver vai izveido JOB (1 PROJECT)")
        else:
            self.topbar.set_project(project.root.name, str(project.root))
        self.topbar.set_operator(self._operator(), f"{APP_TITLE} {__version__}")

        documents = self._documents()
        rows = self._rows()
        snapshot = self._progress()
        failures = self._validation_failures()

        counts = dict(snapshot.counts) if snapshot is not None else {}
        total = int(snapshot.total) if snapshot is not None else 0  # the core's own total
        done = int(counts.get("DONE", 0))
        running = int(counts.get("RUNNING", 0))
        errors = int(counts.get("ERROR", 0))
        queue_tone = self._queue_tone(total, done, running, errors)

        # ---- status chips of the top bar
        self.topbar.set_chip(
            "job", project.root.name if project is not None else "-", "ok" if project else "idle"
        )
        self.topbar.set_chip("documents", str(len(documents)), "idle" if documents else "warn")
        self.topbar.set_chip(
            "plan", f"{len(rows)} lapas" if rows else "nav plāna", "ok" if rows else "warn"
        )
        self.topbar.set_chip(
            "queue", f"DONE {done}/{total}" if total else "nav rindā", queue_tone
        )
        self.topbar.set_chip("illustrator", self._illustrator_metric(), self._illustrator_tone())

        # ---- the review question of the centre column
        if project is None:
            self.review.set_answer("Nav atvērts JOB - sāc ar 1 PROJECT (OPEN PROJECT).", tone="unknown")
        elif failures:
            self.review.set_answer(
                f"NĒ - {len(failures)} problēma(s), pirmā: {self._short(failures[0])}", tone="warn"
            )
        else:
            self.review.set_answer(
                f"JĀ - {len(rows)} lapas, {len(documents)} dokumenti; RUN ir atļauts.", tone="ok"
            )

        # ---- advisor cards (the mockup's three columns with a coloured dot)
        self.advisor.set_card(
            "plan",
            tone="ok" if (rows and not failures) else ("warn" if rows else "unknown"),
            metric=f"{len(rows)} lapas" if rows else "-",
            detail=self._plan_detail(rows, failures),
        )
        self.advisor.set_card(
            "queue",
            tone=queue_tone,
            metric=f"{done} / {total}" if total else "-",
            detail=self._queue_detail(snapshot, counts),
        )
        self.advisor.set_card(
            "illustrator",
            tone=self._illustrator_tone(),
            metric=self._illustrator_metric(),
            detail=self._illustrator_detail(),
        )

    @staticmethod
    def _short(text: str, limit: int = 90) -> str:
        line = " ".join(str(text).split())
        return line if len(line) <= limit else line[: limit - 1] + "\\u2026"

    @staticmethod
    def _queue_tone(total: int, done: int, running: int, errors: int) -> str:
        if not total:
            return "unknown"
        if errors:
            return "error"
        if running:
            return "busy"
        return "ok" if done == total else "idle"

    def _plan_detail(self, rows: list[Any], failures: list[str]) -> str:
        if not rows:
            return "nav plāna - atver JOB un izvēlies PDF (2 PDF)"
        if failures:
            return f"{len(failures)} problēma(s): {self._short(failures[0])}"
        return "pārbaudes: OK"

    @staticmethod
    def _queue_detail(snapshot: ProgressSnapshot | None, counts: dict[str, int]) -> str:
        """The queue states with a non-zero count (never the total/enabled extras)."""
        if not counts:
            return "rinda vēl nav uzcelta"
        if snapshot is not None and int(counts.get(state.RUNNING, 0)):
            return snapshot.current_label()
        parts = [
            f"{name} {int(counts.get(name, 0))}"
            for name in state.VALID_STATES
            if int(counts.get(name, 0))
        ]
        return " | ".join(parts) or "rinda ir tukša"


    def _illustrator_tone(self) -> str:
        state = self.controller.illustrator_state
        if state is True:
            return "ok"
        if state is False:
            return "error"
        return "unknown"

    def _illustrator_metric(self) -> str:
        state = self.controller.illustrator_state
        if state is True:
            return "savienots"
        if state is False:
            return "nav sasniedzams"
        return "nav pārbaudīts"

    def _illustrator_detail(self) -> str:
        state = self.controller.illustrator_state
        if state is True:
            return "COM savienojums pārbaudīts (HEALTH CHECK)"
        if state is False:
            return "palaid HEALTH CHECK; detaļas ir LOG skatā"
        return "HEALTH CHECK to pārbaudīs (Illustratoris netiek palaists pats)"

    def _documents(self) -> list[Any]:
        try:
            return self.controller.documents()
        except ControllerError:
            return []

    def _rows(self) -> list[Any]:
        try:
            return self.controller.mapping_rows()
        except ControllerError:
            return []

    def _progress(self) -> ProgressSnapshot | None:
        try:
            return self.controller.progress()
        except ControllerError:
            return None

    def _validation_failures(self) -> list[str]:
        try:
            return self.controller.validation_failures()
        except ControllerError:
            return []

    @staticmethod
    def _operator() -> str:
        try:
            return getpass.getuser()
        except Exception:  # noqa: BLE001 - a missing user name must not stop the window
            return "operators"


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
            elif event.kind == tasks.EVENT_PREVIEW:
                self.mapping_tab.on_preview_result(event.payload)
        self._render_busy()
        self._maybe_refresh_live_states(time.monotonic())
        self._pump_id = self.after(LOG_POLL_MS, self._pump)

    def _maybe_refresh_live_states(self, now: float) -> None:
        """While a batch runs, keep the rows/tiles (and the shell) showing RUNNING.

        A progress event only arrives AFTER a page finished, so without this the
        thumbnails would jump WAITING -> DONE and never show the page that is being
        processed right now (milestone 5: the state must be visible on the tile).
        """
        if not self.runner.busy:
            return
        if now - self._live_refresh_at < LIVE_STATE_REFRESH_SECONDS:
            return
        self._live_refresh_at = now
        self.mapping_tab.refresh()
        self._refresh_shell()

    def _on_task_done(self, payload: Any) -> None:
        from ..core.preflight import PreflightReport
        from ..core.queue import BatchSummary

        if isinstance(payload, BatchSummary):
            self.run_tab.show_summary(payload)
            self._log_report_paths()
            self.append_log("Darbs pabeigts")
            self.set_status(f"Pabeigts: {payload.format().splitlines()[0]}")
            self.refresh_all()
        elif isinstance(payload, PreflightReport):
            self.run_tab.show_preflight(payload)
            self.refresh_all()
        elif isinstance(payload, tuple) and len(payload) == 2 and isinstance(payload[0], bool):
            self.run_tab.show_health(payload)
            self.refresh_all()
        elif payload is not None:
            self.append_log(str(payload))

    def _log_report_paths(self) -> None:
        """Show where the immutable report of the finished pass was written."""
        paths = self.controller.last_report_paths()
        if paths is None:
            return
        self.append_log(f"Report: {paths.txt}")
        self.append_log(f"        {paths.json}")

    def _render_busy(self) -> None:
        busy = self.runner.busy
        for tab in (self.project_tab, self.pdf_tab, self.mapping_tab):
            tab.set_busy(busy)
        self.run_tab.set_busy(busy, f"Notiek: {self.runner.label}" if busy else "")
        self.actions.set_busy(busy)  # the action panel follows the same rule
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
        """Rebuild every section from the controller (never from GUI-owned state)."""
        self._ensure_job_logging()
        # the preview cache follows the JOB (JOB/.cache/preview); before that: temp
        self.preview_loader.cache = self.controller.preview_cache()
        if self.controller.project is not None:
            # opening a JOB must show the project queue (both PDFs, states included)
            self.controller.ensure_queue_built()
        for tab in (self.project_tab, self.pdf_tab, self.mapping_tab, self.run_tab):
            refresh = getattr(tab, "refresh", None)
            if callable(refresh):
                refresh()
        self.run_tab.update_progress()
        self._refresh_shell()

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
        try:
            self.preview_loader.stop()  # the render worker must not outlive the window
        except Exception:  # noqa: BLE001 - closing must always succeed
            pass
        self.bus.close()
        self.destroy()


def launch(argv: list[str] | None = None) -> int:
    """Create the window and run the Tk main loop."""
    configure_console()
    window = MainWindow()
    window.mainloop()
    return 0

