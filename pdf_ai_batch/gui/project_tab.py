"""PROJECT tab: create/open a JOB, add PDFs and templates, show the folders."""

from __future__ import annotations

import os
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from .controller import ControllerError
from .context import GuiContext


class ProjectTab(ttk.Frame):
    """Left: the six JOB folders. Right: the project actions."""

    def __init__(self, parent: ttk.Notebook, context: GuiContext) -> None:
        super().__init__(parent, padding=8)
        self.ctx = context
        self._buttons: list[ttk.Button] = []
        self._build()

    # ------------------------------------------------------------------ widgets

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="JOB:").grid(row=0, column=0, sticky="w")
        self.job_label = ttk.Label(header, text="(nav atvērts)", foreground="#444")
        self.job_label.grid(row=0, column=1, sticky="w", padx=(6, 0))

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.grid(row=1, column=0, sticky="nsew")

        table_frame = ttk.Frame(panes)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table_frame, columns=("folder", "state", "path"), show="headings", height=10
        )
        self.tree.heading("folder", text="MAPE")
        self.tree.heading("state", text="STĀVOKLIS")
        self.tree.heading("path", text="CEĻŠ")
        self.tree.column("folder", width=110, anchor="w", stretch=False)
        self.tree.column("state", width=90, anchor="center", stretch=False)
        self.tree.column("path", width=480, anchor="w")
        self.tree.tag_configure("missing", foreground="#b00020")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        panes.add(table_frame, weight=3)

        buttons = ttk.Frame(panes, padding=(10, 0, 0, 0))
        buttons.columnconfigure(0, weight=1)
        specs = (
            ("NEW PROJECT", self.on_new_project),
            ("OPEN PROJECT", self.on_open_project),
            ("ADD PDF", self.on_add_pdf),
            ("ADD TEMPLATES", self.on_add_templates),
            ("OPEN JOB FOLDER", self.on_open_folder),
        )
        for index, (label, handler) in enumerate(specs):
            button = ttk.Button(buttons, text=label, command=handler)
            button.grid(row=index, column=0, sticky="ew", pady=3)
            self._buttons.append(button)
        ttk.Separator(buttons, orient="horizontal").grid(
            row=len(specs), column=0, sticky="ew", pady=8
        )
        self.summary = ttk.Label(buttons, text="", justify="left", foreground="#444")
        self.summary.grid(row=len(specs) + 1, column=0, sticky="w")
        panes.add(buttons, weight=1)

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
            self.job_label.configure(text="(nav atvērts)", foreground="#444")
            self.summary.configure(text="")
            return

        self.job_label.configure(text=str(project.root), foreground="#111")
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
        """While a batch runs, mutating JOB actions are disabled."""
        for button in self._buttons:
            button.configure(state="disabled" if busy else "normal")