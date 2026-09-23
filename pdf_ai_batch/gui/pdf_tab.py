"""PDF tab: the JOB's documents (USE / PDF / PAGES / CONFIG STATUS / QUEUE STATUS).

One JOB can hold several PDFs; each has its own plan, its own queue states and its
own outputs. Selecting a row makes that document active: the MAPPING tab then shows
(and edits) exactly that PDF, and RUN CURRENT PDF runs only its pages.

Nothing is rewritten here: a document whose PDF changed size shows `CONFIG STALE`
and waits for an explicit RECONCILE; a document whose file is gone shows
`MISSING PDF` and keeps its plan and its queue state.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .controller import ControllerError
from .context import GuiContext

STATUS_COLOURS = {
    "CONFIG STALE": "#a15c00",
    "MISSING PDF": "#b00020",
    "PLAN ERROR": "#b00020",
    "OK": "#1a7f37",
    "NEW": "#0b5cad",
}


class PdfTab(ttk.Frame):
    """Top: the document table. Bottom: what the core reports about the selection."""

    def __init__(self, parent: ttk.Notebook, context: GuiContext) -> None:
        super().__init__(parent, padding=8)
        self.ctx = context
        self._buttons: list[ttk.Button] = []
        self._rows: list[Any] = []
        self._loading = False  # suppress selection events while filling the table
        self._build()

    # ------------------------------------------------------------------ widgets

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew")
        for index in range(5):
            bar.columnconfigure(index, weight=1)
        specs = (
            ("IZMANTOT (MAPPING)", self.on_use, 0, 0),
            ("IESLĒGT/IZSLĒGT", self.on_toggle_use, 0, 1),
            ("RECONCILE", self.on_reconcile, 0, 2),
            ("PIEVIENOT PDF...", self.on_add_pdf, 0, 3),
            ("ATJAUNOT", self.on_refresh, 0, 4),
        )
        for label, handler, row, column in specs:
            button = ttk.Button(bar, text=label, command=handler)
            button.grid(row=row, column=column, sticky="ew", padx=2, pady=2)
            self._buttons.append(button)

        columns = ("use", "pdf", "pages", "config_status", "queue_status")
        frame = ttk.Frame(self)
        frame.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "use": ("USE", 50, "center", False),
            "pdf": ("PDF", 260, "w", True),
            "pages": ("PAGES", 130, "center", False),
            "config_status": ("CONFIG STATUS", 300, "w", True),
            "queue_status": ("QUEUE STATUS", 330, "w", True),
        }
        for key, (text, width, anchor, stretch) in headings.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor, stretch=stretch)
        for label, colour in STATUS_COLOURS.items():
            self.tree.tag_configure(label, foreground=colour)
        self.tree.tag_configure("disabled", background="#f2f2f2")
        self.tree.tag_configure("active", background="#eef4fb")
        self.tree.grid(row=0, column=0, sticky="nsew")
        vscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        hscroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _event: self.on_use())

        details = ttk.LabelFrame(self, text="Izvēlētais dokuments")
        details.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        details.columnconfigure(1, weight=1)
        self.fields: dict[str, ttk.Label] = {}
        rows = (
            ("Fails", "name"),
            ("Ceļš", "path"),
            ("Lapas", "pages"),
            ("Skaits", "method"),
            ("Izmērs", "size"),
            ("Config", "config"),
            ("Rinda", "queue"),
            ("Statuss", "status"),
        )
        for index, (label, key) in enumerate(rows):
            ttk.Label(details, text=f"{label}:").grid(row=index, column=0, sticky="nw", pady=2)
            value = ttk.Label(details, text="-", wraplength=760, justify="left")
            value.grid(row=index, column=1, sticky="nw", padx=(8, 0), pady=2)
            self.fields[key] = value
        self.note = ttk.Label(details, text="", foreground="#444", wraplength=900, justify="left")
        self.note.grid(row=len(rows), column=0, columnspan=2, sticky="w")

    # ------------------------------------------------------------------ actions

    def _selected_name(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _row(self, name: str | None):
        return next((row for row in self._rows if row.name == name), None)

    def _on_select(self, _event: Any = None) -> None:
        if self._loading:
            return
        name = self._selected_name()
        if name is None:
            return
        try:
            row = self.ctx.controller.select_document(name)
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        self._show(row)
        self.ctx.report(
            f"Dokuments: {row.name} | {row.page_count} lapas | {row.status_text} | {row.queue_status}"
        )

    def on_use(self) -> None:
        """Make the selected document the active one (what MAPPING edits)."""
        if self._selected_name() is None:
            messagebox.showinfo("PDF", "Izvēlies PDF sarakstā.", parent=self)
            return
        self._on_select()
        self.ctx.refresh()

    def on_toggle_use(self) -> None:
        """USE column: enable/disable the whole document for runs."""
        row = self._row(self._selected_name())
        if row is None:
            self.ctx.report("Izvēlies PDF sarakstā.", error=True)
            return
        try:
            self.ctx.controller.set_document_enabled(row.name, not row.enabled)
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        self.ctx.report(f"{row.name}: {'izslēgts (USE nav atzīmēts)' if row.enabled else 'ieslēgts'}")
        self.ctx.refresh()

    def on_reconcile(self) -> None:
        """Explicit reconciliation of the selected document (page count drift)."""
        row = self._row(self._selected_name())
        if row is None:
            self.ctx.report("Izvēlies PDF sarakstā.", error=True)
            return
        if row.missing:
            self.ctx.report(f"{row.name}: PDF fails nav atrasts - RECONCILE nav iespējams", error=True)
            return
        if not messagebox.askyesno(
            "RECONCILE",
            f"Pārplānot {row.name}?\n\n"
            f"config.json: {row.stored_page_count or 'nav'} lapas\n"
            f"PDF tagad: {row.page_count} lapas\n\n"
            "Esošās lapas saglabā template/output/stāvokli, jaunas kļūst WAITING, "
            "noņemtās tiek arhivētas (netiek dzēstas).",
            parent=self,
        ):
            return
        try:
            report = self.ctx.controller.reconcile_document(row.name)
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        self.ctx.report(
            f"RECONCILE {report.get('pdf')}: {report.get('stored')} -> {report.get('current')} lapas | "
            f"pievienotas {', '.join(str(page) for page in report.get('added') or []) or '-'} | "
            f"noņemtas {', '.join(str(page) for page in report.get('removed') or []) or '-'}"
        )
        self.ctx.refresh()

    def on_add_pdf(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Pievienot PDF mapē JOB/PDF",
            filetypes=[("PDF", "*.pdf"), ("Visi faili", "*.*")],
        )
        if not paths:
            return
        try:
            added, skipped = self.ctx.controller.add_pdf(list(paths))
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        self.ctx.report(
            f"Pievienoti PDF: {', '.join(added) or '-'} (izlaisti: {', '.join(skipped) or '-'})"
        )
        self.ctx.refresh()

    def on_refresh(self) -> None:
        self.ctx.refresh()

    # ------------------------------------------------------------------ refresh

    def refresh(self, *_args: Any) -> None:
        """Render the document list from the controller (never the other way round).

        The controller owns the active document; this tab only shows it. The tree
        selection follows the controller, so a programmatic switch (reconcile report,
        acceptance driver, a deleted document) is not silently reverted by the tab.
        """
        rows = []
        if self.ctx.controller.project is not None:
            try:
                rows = self.ctx.controller.documents()
            except ControllerError as exc:
                rows = []
                self.ctx.report(str(exc), error=True)
        self._rows = rows

        names = [row.name for row in rows]
        active = self.ctx.controller.active_pdf.name if self.ctx.controller.active_pdf else None
        target = active if active in names else self._selected_name()
        if target not in names:
            target = names[0] if names else None

        self._loading = True
        try:
            self.tree.delete(*self.tree.get_children())
            for row in rows:
                tags = [row.status]
                if not row.enabled:
                    tags.append("disabled")
                if row.active:
                    tags.append("active")
                self.tree.insert(
                    "",
                    "end",
                    iid=row.name,
                    values=(
                        row.use_label,
                        row.name,
                        row.pages_label,
                        row.status_text,
                        row.queue_status,
                    ),
                    tags=tuple(tags),
                )
            if target is not None:
                self.tree.selection_set(target)
        finally:
            self._loading = False

        if target is None:
            for label in self.fields.values():
                label.configure(text="-")
            self.note.configure(text="JOB/PDF mapē nav neviena PDF faila.")
            return

        if active is None or active != target:
            try:
                self.ctx.controller.select_document(target)
            except ControllerError as exc:
                self.ctx.report(str(exc), error=True)
                return
        row = self._row(target)
        if row is not None:
            self._show(row)

    def _show(self, row) -> None:
        self.fields["name"].configure(text=row.name)
        self.fields["path"].configure(text=str(row.path))
        self.fields["pages"].configure(text=row.pages_label)
        self.fields["method"].configure(text=row.count_method or "-")
        self.fields["size"].configure(
            text=f"{round(row.path.stat().st_size / (1024 * 1024), 1)} MB"
            if row.path.is_file()
            else "-"
        )
        self.fields["config"].configure(text=row.config_status)
        self.fields["queue"].configure(text=row.queue_status)
        self.fields["status"].configure(text=row.status_text)
        self.note.configure(
            text=(
                "USE = vai dokumentu palaiž RUN ALL ENABLED PDFs. Lapu skaitu nosaka Python "
                "(PyMuPDF); Illustratoris to nekad neskaita. CONFIG STALE / MISSING PDF "
                "nemaina plānu bez RECONCILE."
            )
        )

    def set_busy(self, busy: bool) -> None:
        for button in self._buttons:
            button.configure(state="disabled" if busy else "normal")
