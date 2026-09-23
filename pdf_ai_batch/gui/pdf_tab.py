"""PDF tab: pick the PDF of the JOB and show page count, size and config status."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from .controller import ControllerError
from .context import GuiContext


class PdfTab(ttk.Frame):
    """Left: the PDFs found in JOB/PDF. Right: what the core reports about one."""

    def __init__(self, parent: ttk.Notebook, context: GuiContext) -> None:
        super().__init__(parent, padding=8)
        self.ctx = context
        self._buttons: list[ttk.Button] = []
        self._build()

    # ------------------------------------------------------------------ widgets

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.grid(row=0, column=0, sticky="nsew")

        list_frame = ttk.Frame(panes)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(1, weight=1)
        ttk.Label(list_frame, text="JOB/PDF").grid(row=0, column=0, sticky="w")
        self.listbox = tk.Listbox(list_frame, height=12, exportselection=False)
        self.listbox.grid(row=1, column=0, sticky="nsew", pady=(4, 4))
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        scroll.grid(row=1, column=1, sticky="ns", pady=(4, 4))
        self.listbox.configure(yscrollcommand=scroll.set)
        self.refresh_button = ttk.Button(list_frame, text="ATJAUNOT SARAKSTU", command=self.refresh)
        self.refresh_button.grid(row=2, column=0, sticky="ew")
        panes.add(list_frame, weight=1)

        details = ttk.Frame(panes, padding=(12, 0, 0, 0))
        details.columnconfigure(1, weight=1)
        self.fields: dict[str, ttk.Label] = {}
        rows = (
            ("Fails", "name"),
            ("Ceļš", "path"),
            ("Lapas", "pages"),
            ("Skaits", "method"),
            ("Izmērs", "size"),
            ("Config", "config"),
        )
        for index, (label, key) in enumerate(rows):
            ttk.Label(details, text=f"{label}:").grid(row=index, column=0, sticky="nw", pady=2)
            value = ttk.Label(details, text="-", wraplength=520, justify="left")
            value.grid(row=index, column=1, sticky="nw", padx=(8, 0), pady=2)
            self.fields[key] = value
        self.use_button = ttk.Button(details, text="IZMANTOT ŠO PDF", command=self.on_use_pdf)
        self.use_button.grid(row=len(rows), column=0, columnspan=2, sticky="ew", pady=(12, 4))
        self.note = ttk.Label(details, text="", foreground="#444", wraplength=520, justify="left")
        self.note.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w")
        panes.add(details, weight=2)

    # ------------------------------------------------------------------ actions

    def _selected_name(self) -> str | None:
        selection = self.listbox.curselection()
        if not selection:
            return None
        return self.listbox.get(selection[0])

    def _on_select(self, _event: Any = None) -> None:
        name = self._selected_name()
        if name is None:
            return
        try:
            entry = self.ctx.controller.select_pdf(name)
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        self._show(entry)
        self.ctx.report(f"PDF: {entry.name} | {entry.page_count} lapas ({entry.count_method})")
        self.ctx.refresh()

    def on_use_pdf(self) -> None:
        name = self._selected_name()
        if name is None:
            messagebox.showinfo("PDF", "Izvēlies PDF sarakstā.", parent=self)
            return
        self._on_select()

    def _show(self, entry) -> None:
        self.fields["name"].configure(text=entry.name)
        self.fields["path"].configure(text=str(entry.path))
        self.fields["pages"].configure(text=str(entry.page_count))
        self.fields["method"].configure(text=entry.count_method)
        self.fields["size"].configure(text=f"{entry.size_mb} MB ({entry.size_bytes} B)")
        self.fields["config"].configure(text=entry.config_status)
        self.note.configure(
            text="Lapas skaita Python (PyMuPDF, pypdf rezerve) - Illustratoris to nekad neskaita."
        )

    # ------------------------------------------------------------------ refresh

    def refresh(self, *_args: Any) -> None:
        pdfs = []
        if self.ctx.controller.project is not None:
            pdfs = [path.name for path in self.ctx.controller.list_pdfs()]

        current = self._selected_name()
        self.listbox.delete(0, tk.END)
        for name in pdfs:
            self.listbox.insert(tk.END, name)

        target = current if current in pdfs else (pdfs[0] if pdfs else None)
        if target is None:
            for label in self.fields.values():
                label.configure(text="-")
            self.note.configure(text="JOB/PDF mapē nav neviena PDF faila.")
            return
        self.listbox.selection_set(pdfs.index(target))
        if self.ctx.controller.active_pdf is None or self.ctx.controller.active_pdf.name != target:
            try:
                self.ctx.controller.select_pdf(target)
            except ControllerError as exc:
                self.ctx.report(str(exc), error=True)
                return
        try:
            self._show(self.ctx.controller.pdf_entry())
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)

    def set_busy(self, busy: bool) -> None:
        for button in (self.refresh_button, self.use_button):
            button.configure(state="disabled" if busy else "normal")