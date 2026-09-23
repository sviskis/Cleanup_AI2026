"""MAPPING tab: per page template / layer / output / status plus validation.

The table is the operator's plan view. Everything it can change goes through
`AppController` into `config.json` (the plan source of truth) and is then merged
into `state.json` by the core queue - the GUI never writes state itself.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any, Callable

from ..core import state
from .controller import ControllerError, MappingRow
from .context import GuiContext

STATE_COLOURS = {
    state.DONE: "#1a7f37",
    state.ERROR: "#b00020",
    state.INTERRUPTED: "#a15c00",
    state.SKIPPED: "#555555",
    state.RUNNING: "#0b5cad",
    state.WAITING: "#111111",
}
DEFAULT_CHOICE = "<noklusētais template>"


class TemplateChooser(tk.Toplevel):
    """Modal template chooser: lists the files already inside JOB/TEMPLATE.

    `result` is the chosen file name, "" for "use the default template" or None when
    the dialog was cancelled.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        choices: list[str],
        current: str,
        default_name: str,
        on_browse: Callable[[list[str]], list[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Izvēlies template")
        self.transient(parent)
        self.resizable(True, True)
        self.result: str | None = None
        self._choices = list(choices)
        self._default_name = default_name
        self._on_browse = on_browse

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(
            self,
            text=f"Template faili mapē JOB/TEMPLATE (noklusētais: {default_name or '(nav)'})",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))

        self.listbox = tk.Listbox(self, height=10, width=46, exportselection=False)
        self.listbox.grid(row=1, column=0, sticky="nsew", padx=10)
        self.listbox.bind("<Double-1>", lambda _event: self._accept())
        self._fill(current)

        buttons = ttk.Frame(self, padding=10)
        buttons.grid(row=2, column=0, sticky="ew")
        for index in range(3):
            buttons.columnconfigure(index, weight=1)
        ttk.Button(buttons, text="LABI", command=self._accept).grid(row=0, column=0, sticky="ew", padx=2)
        ttk.Button(buttons, text="ATCAUKT", command=self._cancel).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(buttons, text="PĀRLŪKOT...", command=self._browse).grid(row=0, column=2, sticky="ew", padx=2)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._select(current)

    def _fill(self, current: str) -> None:
        self.listbox.delete(0, tk.END)
        self.listbox.insert(tk.END, DEFAULT_CHOICE)
        for name in self._choices:
            self.listbox.insert(tk.END, name)

    def _select(self, current: str) -> None:
        target = current if current in self._choices else ""
        index = self.listbox.get(0, tk.END).index(target) if target else 0
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.listbox.see(index)

    def _current_choice(self) -> str:
        selection = self.listbox.curselection()
        if not selection:
            return ""
        value = self.listbox.get(selection[0])
        return "" if value == DEFAULT_CHOICE else value

    def _browse(self) -> None:
        if self._on_browse is None:
            return
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Pievienot template mapē JOB/TEMPLATE",
            filetypes=[("Illustrator", "*.ai *.ait"), ("Visi faili", "*.*")],
        )
        if not paths:
            return
        added = self._on_browse(list(paths))
        if added:
            self._choices = sorted(set(self._choices) | set(added), key=str.lower)
            self._fill(self._current_choice())

    def _accept(self) -> None:
        self.result = self._current_choice()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class MappingTab(ttk.Frame):
    """The page plan table and its actions."""

    #: replaced by tests so the chooser can be answered without a user
    chooser_factory: type[TemplateChooser] = TemplateChooser

    def __init__(self, parent: ttk.Notebook, context: GuiContext) -> None:
        super().__init__(parent, padding=8)
        self.ctx = context
        self._rows: list[MappingRow] = []
        self._buttons: list[ttk.Button] = []
        self._build()

    # ------------------------------------------------------------------ widgets

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew")
        for index in range(6):
            bar.columnconfigure(index, weight=1)
        actions = (
            ("SELECT ALL", self.on_select_all, 0, 0),
            ("SELECT NONE", self.on_select_none, 0, 1),
            ("ENABLE SELECTED", self.on_enable, 0, 2),
            ("DISABLE SELECTED", self.on_disable, 0, 3),
            ("RESET SELECTED", self.on_reset, 0, 4),
            ("VALIDATE", self.on_validate, 0, 5),
            ("AUTO ASSIGN TEMPLATES", self.on_auto_assign, 1, 0),
            ("ASSIGN TEMPLATE", self.on_assign_template, 1, 1),
            ("USE DEFAULT TEMPLATE", self.on_use_default, 1, 2),
            ("REFRESH", self.on_refresh, 1, 3),
        )
        for label, handler, row, column in actions:
            button = ttk.Button(bar, text=label, command=handler)
            button.grid(row=row, column=column, sticky="ew", padx=2, pady=2)
            self._buttons.append(button)

        columns = ("use", "page", "template", "layer", "output", "status")
        frame = ttk.Frame(self)
        frame.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        headings = {
            "use": ("USE", 52, "center", False),
            "page": ("PAGE", 64, "center", False),
            "template": ("TEMPLATE", 220, "w", True),
            "layer": ("LAYER", 110, "w", False),
            "output": ("OUTPUT", 220, "w", True),
            "status": ("STATUS", 130, "center", False),
        }
        for key, (text, width, anchor, stretch) in headings.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor, stretch=stretch)
        for name, colour in STATE_COLOURS.items():
            self.tree.tag_configure(name, foreground=colour)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        hscroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_selection)
        self.tree.tag_configure("disabled", background="#f2f2f2")

        bottom = ttk.Frame(self)
        bottom.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        bottom.columnconfigure(0, weight=1)
        self.detail = ttk.Label(bottom, text="", foreground="#444", wraplength=900, justify="left")
        self.detail.grid(row=0, column=0, sticky="w")

        panel = ttk.LabelFrame(self, text="Pārbaudes (core/validation)")
        panel.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)
        self.report = tk.Text(panel, height=7, wrap="none", state="disabled")
        self.report.grid(row=0, column=0, sticky="ew")
        report_scroll = ttk.Scrollbar(panel, orient="vertical", command=self.report.yview)
        report_scroll.grid(row=0, column=1, sticky="ns")
        self.report.configure(yscrollcommand=report_scroll.set)

    # ------------------------------------------------------------------ helpers

    def selected_job_ids(self) -> list[str]:
        """Tree item ids ARE job ids, so a selection maps straight onto the queue."""
        return list(self.tree.selection())

    def selected_pages(self) -> list[int]:
        by_id = {row.job_id: row.page for row in self._rows}
        return [by_id[job_id] for job_id in self.selected_job_ids() if job_id in by_id]

    def _set_report(self, text: str) -> None:
        self.report.configure(state="normal")
        self.report.delete("1.0", tk.END)
        self.report.insert("1.0", text)
        self.report.configure(state="disabled")

    def _handle(self, action, success: str) -> None:
        try:
            action()
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        self.ctx.report(success)
        self.ctx.refresh()

    # ------------------------------------------------------------------ actions

    def on_select_all(self) -> None:
        self.tree.selection_set(self.tree.get_children())

    def on_select_none(self) -> None:
        self.tree.selection_remove(*self.tree.selection())

    def on_enable(self) -> None:
        pages = self.selected_pages()
        self._handle(
            lambda: self.ctx.controller.set_enabled(pages, True),
            f"Iespējotas lapas: {pages}",
        )

    def on_disable(self) -> None:
        pages = self.selected_pages()
        self._handle(
            lambda: self.ctx.controller.set_enabled(pages, False),
            f"Izslēgtas lapas: {pages}",
        )

    def on_auto_assign(self) -> None:
        self._handle(
            lambda: self.ctx.controller.auto_assign_templates(),
            "Automātiskā template piešķire veikta (dabiskā kārtā, MASTER nav numurētajā sarakstā)",
        )

    def on_assign_template(self) -> None:
        pages = self.selected_pages()
        if not pages:
            self.ctx.report("Nav atlasīta neviena lapa", error=True)
            return
        template = self._ask_template(current=self._rows[0].template if self._rows else "")
        if template is None:
            return
        self._handle(
            lambda: self.ctx.controller.assign_template(pages, template),
            f"Template {template or '(noklusētais)'} piešķirts lapām {pages}",
        )

    def on_use_default(self) -> None:
        pages = self.selected_pages()
        self._handle(
            lambda: self.ctx.controller.use_default_template(pages),
            f"Noklusētais template lapām {pages}",
        )

    def on_reset(self) -> None:
        job_ids = self.selected_job_ids()
        self._handle(
            lambda: self.ctx.controller.reset_pages(job_ids),
            f"RESET uz WAITING: {', '.join(job_ids) if job_ids else '(neviens)'}",
        )

    def on_refresh(self) -> None:
        self.ctx.controller.refresh()
        self.ctx.refresh()
        self.ctx.report("Statuss pārlasīts no state.json")

    def on_validate(self) -> None:
        self.ctx.controller.validate()
        self._set_report(self.ctx.controller.validation_report())
        failures = self.ctx.controller.validation_failures()
        self.ctx.report(
            "Pārbaudes: OK" if not failures else "Pārbaudes: " + " | ".join(failures[:3]),
            error=bool(failures),
        )

    def on_double_click(self, event: Any) -> None:
        """Double click edits the template of exactly that row."""
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        row = next((candidate for candidate in self._rows if candidate.job_id == item_id), None)
        if row is None:
            return
        template = self._ask_template(current=row.template)
        if template is None:
            return
        self._handle(
            lambda: self.ctx.controller.assign_template([row.page], template),
            f"Lapa {row.page_label}: template {template or '(noklusētais)'}",
        )

    def _ask_template(self, *, current: str) -> str | None:
        """Open the chooser; "" means the default template, None means cancelled.

        A plain object with a `result` attribute works as well as a real Toplevel,
        which is how the acceptance driver answers the dialog without a user.
        """
        dialog = self.chooser_factory(
            self.ctx.window,
            choices=self.ctx.controller.template_choices(),
            current=current,
            default_name=self.ctx.controller.default_template_name(),
            on_browse=lambda paths: self.ctx.controller.add_templates(paths)[0],
        )
        if isinstance(dialog, tk.Widget):
            self.wait_window(dialog)
        return getattr(dialog, "result", None)

    def _on_selection(self, _event: Any = None) -> None:
        rows = [row for row in self._rows if row.job_id in set(self.selected_job_ids())]
        if not rows:
            self.detail.configure(text="")
            return
        row = rows[0]
        text = (
            f"{row.job_id} | lapa {row.page_label} | {row.template or '(nav)'} | "
            f"{row.output} | {row.state}"
            + (f" | mēģinājumi {row.attempts}" if row.attempts else "")
        )
        if row.detail:
            text += f" | {row.detail}"
        self.detail.configure(text=text)

    # ------------------------------------------------------------------ refresh

    def refresh(self, *_args: Any) -> None:
        keep = set(self.tree.selection())  # an action must not lose the selection
        try:
            rows = self.ctx.controller.mapping_rows()
        except ControllerError as exc:
            self._rows = []
            self.tree.delete(*self.tree.get_children())
            self.detail.configure(text=str(exc))
            return
        self._rows = rows
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            tags = [row.state]
            if not row.enabled:
                tags.append("disabled")
            self.tree.insert(
                "",
                "end",
                iid=row.job_id,
                values=(row.use_label, row.page_label, row.template, row.layer, row.output, row.state),
                tags=tuple(tags),
            )
        restored = [job_id for job_id in self.tree.get_children() if job_id in keep]
        if restored:
            self.tree.selection_set(restored)
        self._on_selection()  # keep the detail line in sync (also clears a stale message)
        if self.report.get("1.0", tk.END).strip() == "":
            self._set_report(self.ctx.controller.validation_report())

    def set_busy(self, busy: bool) -> None:
        """While a batch runs, plan edits are disabled (the worker owns state.json)."""
        for button in self._buttons:
            button.configure(state="disabled" if busy else "normal")
