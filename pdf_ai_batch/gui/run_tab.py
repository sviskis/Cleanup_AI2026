"""RUN / LOG section: batch execution, progress and the live log view.

The batch itself runs in a worker thread (see `gui/tasks.py`); this section only starts
tasks and renders events. Progress comes from `AppController.progress()`, i.e. from the
queue state - the GUI keeps no counter of its own.

The widgets are built from `gui/theme.py` (dark) and `gui/shell.py` (cards); the same
handlers are also reachable from the right action panel (`loop` / `monitoring`).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Any

from ..core.queue import BatchSummary
from . import shell, theme
from .controller import ControllerError
from .context import GuiContext


class RunTab(theme.Frame):
    """Left: the run actions. Right: progress. Bottom: the live log."""

    def __init__(self, parent: Any, context: GuiContext) -> None:
        super().__init__(parent)
        self.ctx = context
        self._buttons: list[Any] = []
        self._busy = False  # the last value pushed to the buttons (a no-op is skipped)
        self._busy_text = ""  # the last label text pushed to the busy label
        #: wired by MainWindow: the MAPPING tab's selection (job ids)
        self.selection_provider = None
        self._build()

    # ------------------------------------------------------------------ widgets

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = theme.Frame(self)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=2)
        top.rowconfigure(0, weight=1)

        actions = shell.TitledCard(top, title="Darbības")
        actions.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        specs = (
            ("RUN SELECTED", self.on_run_selected, "accent"),
            ("RUN CURRENT PDF", self.on_run_current, "primary"),
            ("RUN ALL ENABLED PDFs", self.on_run_all, "primary"),
            ("CONTINUE PROJECT", self.on_continue, "ghost"),
            ("RETRY PROJECT ERRORS", self.on_retry_errors, "ghost"),
            ("RETRY INTERRUPTED", self.on_retry_interrupted, "ghost"),
            ("REFRESH STATUS", self.on_refresh, "ghost"),
            ("HEALTH CHECK", self.on_health, "ghost"),
            ("PREFLIGHT PROJECT", self.on_preflight, "primary"),
        )
        for label, handler, kind in specs:
            button = theme.Button(actions.body, text=label, kind=kind, command=handler)
            button.grid(row=len(self._buttons), column=0, sticky="ew", pady=2)
            self._buttons.append(button)

        self.overwrite_var = tk.BooleanVar(master=self, value=self.ctx.controller.overwrite_outputs)
        overwrite = theme.CheckBox(
            actions.body,
            text="Pārrakstīt esošos AI (overwrite)",
            variable=self.overwrite_var,
            command=self.on_overwrite_toggle,
        )
        overwrite.grid(row=len(self._buttons), column=0, sticky="w", pady=(10, 2))
        self._buttons.append(overwrite)

        progress = shell.TitledCard(top, title="Progress")
        progress.grid(row=0, column=1, sticky="nsew")
        body = progress.body
        body.columnconfigure(0, weight=1)
        self.current = theme.Title(body, text="Lapas --- / ---")
        self.current.grid(row=0, column=0, sticky="w", padx=8, pady=(4, 6))
        self.progressbar = theme.ProgressBar(body)
        self.progressbar.grid(row=1, column=0, sticky="ew", padx=8)
        self.counts = theme.Label(body, text="", justify="left")
        self.counts.grid(row=2, column=0, sticky="w", padx=8, pady=(8, 4))
        theme.Muted(body, text="Dokumenti:").grid(row=3, column=0, sticky="w", padx=8)
        self.documents = theme.Label(body, text="", justify="left")
        self.documents.grid(row=4, column=0, sticky="w", padx=8, pady=(0, 8))
        self.busy_label = theme.Label(body, text="", text_color=theme.COLORS["accent"])
        self.busy_label.grid(row=5, column=0, sticky="w", padx=8, pady=(0, 8))

        self.preflight = theme.Label(
            body,
            text="PREFLIGHT PROJECT: nav pārbaudīts",
            justify="left",
            text_color=theme.COLORS["muted"],
        )
        self.preflight.grid(row=6, column=0, sticky="w", padx=8, pady=(0, 8))

        log_card = shell.TitledCard(self, title="Log (skats; kanoniskie logi ir JOB/LOG)")
        log_card.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        log_body = log_card.body
        log_body.columnconfigure(0, weight=1)
        log_body.rowconfigure(0, weight=1)
        self.log = theme.Text(log_body, height=14, wrap="none")
        self.log.grid(row=0, column=0, sticky="nsew")

    # ------------------------------------------------------------------ helpers

    def append_log(self, text: str) -> None:
        """Append one line to the view (never the source of truth)."""
        self.log.configure(state="normal")
        self.log.insert(tk.END, text.rstrip() + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def set_busy(self, busy: bool, label: str = "") -> None:
        """Lock the run actions; an unchanged call only redraws nothing.

        The label text is cached next to the value, so a new task's text is never
        skipped (the window calls this from its pump every 120 ms).
        """
        busy = bool(busy)
        text = label if busy else ""
        if self._busy == busy and self._busy_text == text:
            return
        self._busy = busy
        self._busy_text = text
        for button in self._buttons:
            if not busy:
                button.configure(state="normal")
                continue
            # only REFRESH STATUS stays usable while a batch runs (it is a plain read)
            button.configure(state="normal" if str(button["text"]) == "REFRESH STATUS" else "disabled")
        self.busy_label.configure(text=text)

    def _start(self, label: str, task) -> None:
        try:
            self.ctx.controller.validate()
        except Exception as exc:  # noqa: BLE001 - validation must never crash the GUI
            self.ctx.report(f"Pārbaudes kļūda: {exc}", error=True)
            return
        failures = self.ctx.controller.validation_failures()
        if failures:
            messagebox.showerror(
                "Pārbaudes",
                "Darbs netiek sākts, jo pārbaudes neizturēja:\n\n" + "\n".join(failures[:6]),
                parent=self,
            )
            self.ctx.report(" | ".join(failures[:3]), error=True)
            return
        # a finished PREFLIGHT PROJECT blocks a run only on a real ERROR (never a warning)
        blockers = self.ctx.controller.preflight_blocks_run()
        if blockers:
            messagebox.showerror(
                "PREFLIGHT PROJECT",
                "Darbs netiek sākts, jo PREFLIGHT PROJECT atrada kļūdas:\n\n"
                + "\n".join(blockers[:6]),
                parent=self,
            )
            self.ctx.report("PREFLIGHT: " + " | ".join(blockers[:3]), error=True)
            return
        if not self.ctx.run_task(label, task):
            self.ctx.report("Notiek cits darbs, nogaidi.", error=True)

    # ------------------------------------------------------------------ actions

    def on_run_selected(self) -> None:
        job_ids = list(self.selection_provider()) if self.selection_provider else []
        if not job_ids:
            self.ctx.report("MAPPING tabulā nav atlasīta neviena lapa", error=True)
            return
        self._start(
            "RUN SELECTED",
            lambda progress: self.ctx.controller.run_selected(job_ids, progress=progress),
        )

    def on_run_current(self) -> None:
        """RUN CURRENT PDF: the document selected in the PDF tab (others wait)."""
        self._start(
            "RUN CURRENT PDF",
            lambda progress: self.ctx.controller.run_document(progress=progress),
        )

    def on_run_all(self) -> None:
        """RUN ALL ENABLED PDFs: every enabled document of the JOB."""
        self._start(
            "RUN ALL ENABLED PDFs",
            lambda progress: self.ctx.controller.run_all_enabled(progress=progress),
        )

    def on_continue(self) -> None:
        """CONTINUE PROJECT: WAITING + INTERRUPTED across every document."""
        self._start(
            "CONTINUE PROJECT",
            lambda progress: self.ctx.controller.continue_queue(progress=progress),
        )

    def on_retry_errors(self) -> None:
        """RETRY PROJECT ERRORS: ERROR -> WAITING in every document, then run."""
        self._start(
            "RETRY PROJECT ERRORS",
            lambda progress: self.ctx.controller.retry_errors(progress=progress),
        )

    def on_retry_interrupted(self) -> None:
        self._start(
            "RETRY INTERRUPTED",
            lambda progress: self.ctx.controller.retry_interrupted(progress=progress),
        )

    def on_refresh(self) -> None:
        recovered = self.ctx.controller.refresh()
        self.ctx.refresh()
        self.ctx.report(
            "Statuss pārlasīts no state.json"
            + (f" | atjaunoti pēc pārtraukuma: {', '.join(recovered)}" if recovered else "")
        )

    def on_overwrite_toggle(self) -> None:
        """Overwrite is a run time decision; keep the controller in sync."""
        self.ctx.controller.overwrite_outputs = bool(self.overwrite_var.get())
        self.ctx.report(
            "Pārrakstīt esošos AI: "
            + (
                "JĀ - RESET lapas tiks apstrādātas no jauna"
                if self.ctx.controller.overwrite_outputs
                else "NĒ"
            )
        )

    def on_health(self) -> None:
        """Explicit health check - one of the two places that may touch COM."""
        self._start_health()

    def on_preflight(self) -> None:
        """PREFLIGHT PROJECT: the whole project in one READY / NOT READY report.

        Runs in a worker thread (it may talk to Illustrator for a few seconds), so the
        window stays responsive and the widgets are only touched in the event pump.
        """
        if not self.ctx.run_task(
            "PREFLIGHT PROJECT",
            lambda progress: self.ctx.controller.preflight_project(check_illustrator=True),
        ):
            self.ctx.report("Notiek cits darbs, nogaidi.", error=True)


    def show_preflight(self, result) -> None:
        """Render the preflight report (called by the window after the task)."""
        if result is None:
            return
        self.append_log("".join(line + "\n" for line in result.to_text().splitlines()))
        rows = [f"{label + ':':<20} {value}" for label, value in result.summary_rows() if label]
        self.preflight.configure(text="\n".join(rows))
        self.ctx.report(
            f"PREFLIGHT: {result.status}"
            + (f" | kļūdas: {len(result.problems)}" if result.problems else "")
            + (f" | brīdinājumi: {len(result.warnings)}" if result.warnings else ""),
            error=not result.can_run,
        )
        if result.problems:
            for problem in result.problems[:4]:
                self.append_log("KĻŪDA: " + problem)

    def _start_health(self) -> None:
        if not self.ctx.run_task("HEALTH CHECK", lambda progress: self.ctx.controller.check_illustrator()):
            self.ctx.report("Notiek cits darbs, nogaidi.", error=True)

    # ----------------------------------------------------------------- progress

    def update_progress(self, *_args: Any) -> None:
        """Render the queue state (called after every event and on refresh)."""
        try:
            snapshot = self.ctx.controller.progress()
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        self.current.configure(text=snapshot.current_label())
        self.progressbar["value"] = round(snapshot.fraction * 1000)
        self.counts.configure(text="\n".join(snapshot.summary_lines()))
        self.documents.configure(text="\n".join(snapshot.document_lines()) or "(nav dokumentu rindā)")

    def show_summary(self, summary: BatchSummary) -> None:
        """End of pass report: counts from the state, statistics from the pass."""
        self.append_log(summary.format())
        for outcome in summary.outcomes:
            self.append_log(f"  {outcome.line()}")
        self.update_progress()

    def show_error(self, exc: BaseException) -> None:
        self.append_log(f"KĻŪDA: {exc}")
        self.ctx.report(str(exc), error=True)
        self.update_progress()

    def show_health(self, result: tuple[bool, str]) -> None:
        ok, message = result
        self.append_log(("OK: " if ok else "KĻŪDA: ") + message)
        self.ctx.report(message, error=not ok)
        self.update_progress()

