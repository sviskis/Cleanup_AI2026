"""RUN / LOG tab: batch execution, progress and the live log view.

The batch itself runs in a worker thread (see `gui/tasks.py`); this tab only starts
tasks and renders events. Progress comes from `AppController.progress()`, i.e. from
the queue state - the GUI keeps no counter of its own.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from ..core.queue import BatchSummary
from .controller import ControllerError
from .context import GuiContext


class RunTab(ttk.Frame):
    """Left: the run actions. Right: progress. Bottom: the live log."""

    def __init__(self, parent: ttk.Notebook, context: GuiContext) -> None:
        super().__init__(parent, padding=8)
        self.ctx = context
        self._buttons: list[ttk.Button] = []
        #: wired by MainWindow: the MAPPING tab's selection (job ids)
        self.selection_provider = None
        self._build()

    # ------------------------------------------------------------------ widgets

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=2)

        actions = ttk.LabelFrame(top, text="Darbības")
        actions.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        actions.columnconfigure(0, weight=1)
        specs = (
            ("RUN SELECTED", self.on_run_selected),
            ("RUN CURRENT PDF", self.on_run_current),
            ("RUN ALL ENABLED PDFs", self.on_run_all),
            ("CONTINUE PROJECT", self.on_continue),
            ("RETRY PROJECT ERRORS", self.on_retry_errors),
            ("RETRY INTERRUPTED", self.on_retry_interrupted),
            ("REFRESH STATUS", self.on_refresh),
            ("HEALTH CHECK", self.on_health),
        )
        for index, (label, handler) in enumerate(specs):
            button = ttk.Button(actions, text=label, command=handler)
            button.grid(row=index, column=0, sticky="ew", pady=2, padx=2)
            self._buttons.append(button)

        self.overwrite_var = tk.BooleanVar(value=self.ctx.controller.overwrite_outputs)
        overwrite = ttk.Checkbutton(
            actions,
            text="Pārrakstīt esošos AI (overwrite)",
            variable=self.overwrite_var,
            command=self.on_overwrite_toggle,
        )
        overwrite.grid(row=len(specs), column=0, sticky="w", padx=2, pady=(8, 2))
        self._buttons.append(overwrite)

        progress = ttk.LabelFrame(top, text="Progress")
        progress.grid(row=0, column=1, sticky="nsew")
        progress.columnconfigure(0, weight=1)
        self.current = ttk.Label(progress, text="Lapas --- / ---", font=("Segoe UI", 14, "bold"))
        self.current.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        self.progressbar = ttk.Progressbar(progress, maximum=1000, mode="determinate")
        self.progressbar.grid(row=1, column=0, sticky="ew", padx=10)
        self.counts = ttk.Label(progress, text="", justify="left")
        self.counts.grid(row=2, column=0, sticky="w", padx=10, pady=(8, 4))
        ttk.Label(progress, text="Dokumenti:", foreground="#444").grid(
            row=3, column=0, sticky="w", padx=10
        )
        self.documents = ttk.Label(progress, text="", justify="left", foreground="#444")
        self.documents.grid(row=4, column=0, sticky="w", padx=10, pady=(0, 8))
        self.busy_label = ttk.Label(progress, text="", foreground="#0b5cad")
        self.busy_label.grid(row=5, column=0, sticky="w", padx=10, pady=(0, 8))

        log_frame = ttk.LabelFrame(self, text="Log (skats; kanoniskie logi ir JOB/LOG)")
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=14, wrap="none", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

    # ------------------------------------------------------------------ helpers

    def append_log(self, text: str) -> None:
        """Append one line to the view (never the source of truth)."""
        self.log.configure(state="normal")
        self.log.insert(tk.END, text.rstrip() + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def set_busy(self, busy: bool, label: str = "") -> None:
        for button in self._buttons:
            if not busy:
                button.configure(state="normal")
                continue
            # only REFRESH STATUS stays usable while a batch runs (it is a plain read)
            button.configure(state="normal" if str(button["text"]) == "REFRESH STATUS" else "disabled")
        self.busy_label.configure(text=label if busy else "")

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
            + ("JĀ - RESET lapas tiks apstrādātas no jauna" if self.ctx.controller.overwrite_outputs else "NĒ")
        )

    def on_health(self) -> None:
        """Explicit health check - the only other place that may touch COM."""
        self._start_health()

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