"""PROJECT section: create/open a JOB, add PDFs and templates, show the folders.

The dark shell version (see `gui/theme.py`): the six JOB folders in a card, the project
actions in a labelled card (and again in the right action panel).
"""

from __future__ import annotations

import os
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from . import shell, theme
from .controller import ControllerError
from .context import GuiContext


class ProjectTab(theme.Frame):
    """Left: the six JOB folders. Right: the project actions."""

    def __init__(self, parent: Any, context: GuiContext) -> None:
        super().__init__(parent)
        self.ctx = context
        self._buttons: list[Any] = []
        self._busy = False  # the last value pushed to the buttons (a no-op is skipped)
        self._build()

    # ------------------------------------------------------------------ widgets

    def _build(self) -> None:
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        header = theme.Card(self)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        header.columnconfigure(1, weight=1)
        theme.Label(header, text="JOB:", text_color=theme.COLORS["muted"]).grid(
            row=0, column=0, sticky="w", padx=(12, 6), pady=10
        )
        self.job_label = theme.Body(header, text="(nav atvērts)")
        self.job_label.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=10)

        table_card = shell.TitledCard(self, title="JOB mapes")
        table_card.grid(row=1, column=0, sticky="nsew")
        table_body = table_card.body
        table_body.columnconfigure(0, weight=1)
        table_body.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table_body, columns=("folder", "state", "path"), show="headings", height=10
        )
        self.tree.heading("folder", text="MAPE")
        self.tree.heading("state", text="STĀVOKLIS")
        self.tree.heading("path", text="CEĻŠ")
        self.tree.column("folder", width=110, anchor="w", stretch=False)
        self.tree.column("state", width=90, anchor="center", stretch=False)
        self.tree.column("path", width=480, anchor="w")
        self.tree.tag_configure("missing", foreground=theme.COLORS["red"])
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = theme.Scrollbar(table_body, orientation="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        actions_card = shell.TitledCard(self, title="Darbības")
        actions_card.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        buttons = actions_card.body
        buttons.columnconfigure(0, weight=1)
        specs = (
            ("NEW PROJECT", self.on_new_project, "primary"),
            ("OPEN PROJECT", self.on_open_project, "primary"),
            ("ADD PDF", self.on_add_pdf, "ghost"),
            ("ADD TEMPLATES", self.on_add_templates, "ghost"),
            ("OPEN JOB FOLDER", self.on_open_folder, "ghost"),
        )
        for label, handler, kind in specs:
            button = theme.Button(buttons, text=label, kind=kind, command=handler)
            button.grid(row=len(self._buttons), column=0, sticky="ew", pady=2)
            self._buttons.append(button)
        theme.Divider(buttons).grid(row=len(self._buttons), column=0, sticky="ew", pady=10)
        self.summary = theme.Label(buttons, text="", justify="left")
        self.summary.grid(row=len(self._buttons) + 1, column=0, sticky="w")

    # ------------------------------------------------------------------ actions

    def on_new_project(self) -> None:
        parent = filedialog.askdirectory(title="Mapē, kurā izveidot JOB")
        if not parent:
            return
        name = simpledialog.askstring("Jauns JOB", "JOB mapes nosaukums:", parent=self)
        if not name:
            return
        try:
            project = self.ctx.controller.new_project(os.path.join(parent, name))
        except ControllerError as exc:
            messagebox.showerror("Jauns JOB", str(exc), parent=self)
            return
        self.ctx.report(f"Jauns JOB izveidots: {project.root}")
        self.ctx.refresh()

    def on_open_project(self) -> None:
        folder = filedialog.askdirectory(title="Atver JOB mapi")
        if not folder:
            return
        try:
            project = self.ctx.controller.open_project(folder)
        except ControllerError as exc:
            messagebox.showerror("Atvērt JOB", str(exc), parent=self)
            return
        self.ctx.report(f"JOB atvērts: {project.root}")
        self.ctx.refresh()

    def on_add_pdf(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Pievienot PDF", filetypes=[("PDF", "*.pdf"), ("Visi faili", "*.*")]
        )
        if not paths:
            return
        self._add(paths, self.ctx.controller.add_pdf, "PDF")

    def on_add_templates(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Pievienot template",
            filetypes=[("Illustrator", "*.ai *.ait"), ("Visi faili", "*.*")],
        )
        if not paths:
            return
        self._add(paths, self.ctx.controller.add_templates, "template")

    def _add(self, paths: tuple[str, ...], action, label: str) -> None:
        try:
            added, skipped = action(paths)
        except ControllerError as exc:
            messagebox.showerror(f"Pievienot {label}", str(exc), parent=self)
            return
        self.ctx.report(
            f"Pievienoti {label}: {', '.join(added) if added else '(neviens)'}"
            + (f" | izlaisti: {', '.join(skipped)}" if skipped else "")
        )
        self.ctx.refresh()

    def on_open_folder(self) -> None:
        project = self.ctx.controller.project
        if project is None:
            messagebox.showinfo("JOB", "Vispirms atver vai izveido JOB.", parent=self)
            return
        try:
            os.startfile(str(project.root))  # noqa: S606 - Windows shell open
        except OSError as exc:
            messagebox.showerror("Atvērt mapi", str(exc), parent=self)

    # ------------------------------------------------------------------ refresh

    def refresh(self, *_args: Any) -> None:
        project = self.ctx.controller.project
        self.tree.delete(*self.tree.get_children())
        if project is None:
            self.job_label.configure(text="(nav atvērts)", text_color=theme.COLORS["muted"])
            self.summary.configure(text="")
            return

        self.job_label.configure(text=str(project.root), text_color=theme.COLORS["text"])
        for label, path, exists in self.ctx.controller.project_folders():
            self.tree.insert(
                "",
                "end",
                values=(label, "ir" if exists else "NAV", path),
                tags=() if exists else ("missing",),
            )
        self.summary.configure(
            text=f"PDF: {len(self.ctx.controller.list_pdfs())}\n"
            f"Template: {len(self.ctx.controller.template_choices())}"
        )

    def set_busy(self, busy: bool) -> None:
        """While a batch runs, mutating JOB actions are disabled.

        An unchanged value returns immediately: every `configure()` on a CTkButton is
        a full redraw and the window's pump calls this every 120 ms.
        """
        busy = bool(busy)
        if self._busy == busy:
            return
        self._busy = busy
        for button in self._buttons:
            button.configure(state="disabled" if busy else "normal")

