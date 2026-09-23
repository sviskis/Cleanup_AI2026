"""MAPPING tab: per page template / layer / output / status plus validation.

The table is the operator's plan view. Everything it can change goes through
`AppController` into `config.json` (the plan source of truth) and is then merged
into `state.json` by the core queue - the GUI never writes state itself.

Milestone 6 added the bulk actions: ASSIGN TO SELECTED / ASSIGN TO RANGE /
USE DEFAULT / CLEAR OVERRIDE / AUTO MAP BY NUMBER / COPY MAPPING / PASTE MAPPING /
SAVE PRESET / LOAD-APPLY PRESET. The tab itself only collects input (`bulk_dialogs`)
and calls the controller; the range parser, the numbered mapping and the preset
schema all live in `core/mapping_rules.py`.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from ..core import state
from .bulk_dialogs import (
    DEFAULT_CHOICE,
    PresetDialog,
    RangeAssignDialog,
    SavePresetDialog,
    SnapshotDialog,
)
from .controller import ControllerError, MappingRow
from .context import GuiContext
from .preview_panel import PreviewPanel

STATE_COLOURS = {
    state.DONE: "#1a7f37",
    state.ERROR: "#b00020",
    state.INTERRUPTED: "#a15c00",
    state.SKIPPED: "#555555",
    state.RUNNING: "#0b5cad",
    state.WAITING: "#111111",
}


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
    #: the dialogs of the bulk actions (milestone 6) and history (milestone 8)
    range_dialog_factory: type[RangeAssignDialog] = RangeAssignDialog
    save_preset_dialog_factory: type[SavePresetDialog] = SavePresetDialog
    preset_dialog_factory: type[PresetDialog] = PresetDialog
    snapshot_dialog_factory: type[SnapshotDialog] = SnapshotDialog

    def __init__(self, parent: ttk.Notebook, context: GuiContext) -> None:
        super().__init__(parent, padding=8)
        self.ctx = context
        self._rows: list[MappingRow] = []
        self._buttons: list[ttk.Button] = []
        #: the visual page browser (thumbnails + preview); None without a loader
        self.preview_panel: PreviewPanel | None = None
        self._build()

    # ------------------------------------------------------------------ widgets

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        #: which document this table edits - plan edits never leak into another PDF
        self.document_label = ttk.Label(self, text="PDF: -", font=("Segoe UI", 10, "bold"))
        self.document_label.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.document_detail = ttk.Label(self, text="", foreground="#444")
        self.document_detail.grid(row=1, column=0, sticky="w", pady=(0, 4))

        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew")
        for index in range(6):
            bar.columnconfigure(index, weight=1)
        actions = (
            ("SELECT ALL", self.on_select_all, 0, 0),
            ("SELECT NONE", self.on_select_none, 0, 1),
            ("ENABLE SELECTED", self.on_enable, 0, 2),
            ("DISABLE SELECTED", self.on_disable, 0, 3),
            ("RESET SELECTED", self.on_reset, 0, 4),
            ("VALIDATE", self.on_validate, 0, 5),
            ("ASSIGN TO SELECTED", self.on_assign_template, 1, 0),
            ("ASSIGN TO RANGE", self.on_assign_range, 1, 1),
            ("USE DEFAULT", self.on_use_default, 1, 2),
            ("CLEAR OVERRIDE", self.on_clear_override, 1, 3),
            ("AUTO MAP BY NUMBER", self.on_auto_map_number, 1, 4),
            ("REFRESH", self.on_refresh, 1, 5),
            ("COPY MAPPING", self.on_copy_mapping, 2, 0),
            ("PASTE MAPPING", self.on_paste_mapping, 2, 1),
            ("SAVE PRESET", self.on_save_preset, 2, 2),
            ("LOAD / APPLY PRESET", self.on_apply_preset, 2, 3),
            ("AUTO ASSIGN TEMPLATES", self.on_auto_assign, 2, 4),
            ("RECONCILE PDF", self.on_reconcile, 3, 0),
            ("UNDO PLAN CHANGE", self.on_undo, 3, 1),
            ("RESTORE SNAPSHOT", self.on_restore, 3, 2),
        )
        for label, handler, row, column in actions:
            button = ttk.Button(bar, text=label, command=handler)
            button.grid(row=row, column=column, sticky="ew", padx=2, pady=2)
            self._buttons.append(button)

        loader = getattr(self.ctx, "preview_loader", None)
        if loader is not None:
            self.preview_panel = PreviewPanel(self, self.ctx, loader)
            self.preview_panel.on_select_pages = self.on_preview_select
            self.preview_panel.on_action = self.on_preview_action
            self.preview_panel.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        columns = ("use", "page", "template", "layer", "output", "status")
        frame = ttk.Frame(self)
        frame.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
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
        bottom.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        bottom.columnconfigure(0, weight=1)
        self.detail = ttk.Label(bottom, text="", foreground="#444", wraplength=900, justify="left")
        self.detail.grid(row=0, column=0, sticky="w")

        panel = ttk.LabelFrame(self, text="Pārbaudes (core/validation)")
        panel.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)
        self.report = tk.Text(panel, height=5, wrap="none", state="disabled")
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

    def _handle(self, action, success: str):
        """Run a controller action; report the result or the ControllerError.

        Returns whatever the action returned, so a caller can use the report of a bulk
        operation (for example the problems of the numbered auto mapping).
        """
        try:
            result = action()
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return None
        self.ctx.report(success)
        self.ctx.refresh()
        return result

    @staticmethod
    def _wait(dialog) -> None:
        """Wait for a modal dialog (a fake dialog object is never waited for)."""
        if isinstance(dialog, tk.Widget):
            dialog.wait_window()

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

    # ----------------------------------------------------------- bulk mapping (M6)

    def on_assign_range(self) -> None:
        """ASSIGN TO RANGE: pages text + template (+ layer / enable) in one dialog."""
        try:
            page_count = self.ctx.controller.active_document().page_count
        except (ControllerError, AttributeError):
            page_count = 0
        dialog = self.range_dialog_factory(
            self.ctx.window,
            page_count=page_count,
            choices=self.ctx.controller.template_choices(),
            parse=self.ctx.controller.parse_pages,
            current_template=self._rows[0].template if self._rows else "",
            current_layer=self._rows[0].layer if self._rows else "ARTWORK",
            on_browse=self.ctx.controller.add_templates,
        )
        self._wait(dialog)
        answer = getattr(dialog, "result", None)
        if not answer:
            return
        pages = answer["pages"]
        self._handle(
            lambda: self.ctx.controller.assign_template_to_range(
                pages, answer["template"], layer=answer["layer"]
            ),
            f"Template {answer['template'] or '(noklusētais)'} lapām {self.ctx.controller.format_pages(pages)}",
        )
        if answer.get("enabled") is not None:
            self._handle(
                lambda: self.ctx.controller.set_enabled(pages, answer["enabled"]),
                f"Lapas {self.ctx.controller.format_pages(pages)}: "
                f"{'iespējotas' if answer['enabled'] else 'izslēgtas'}",
            )

    def on_clear_override(self) -> None:
        pages = self.selected_pages()
        if not pages:
            self.ctx.report("Nav atlasīta neviena lapa", error=True)
            return
        self._handle(
            lambda: self.ctx.controller.clear_pages(pages),
            f"Notīrīti pārraksti lapām {self.ctx.controller.format_pages(pages)}",
        )

    def on_auto_map_number(self) -> None:
        """AUTO MAP BY TEMPLATE NUMBER: page N <- the template numbered N."""
        report = self._handle(
            self.ctx.controller.auto_map_by_template_number,
            "Numerētā piešķire veikta (MASTER neietilpst, neskaidri numuri netiek minēti)",
        )
        if report and report.get("problems"):
            self.ctx.report("Neskaidri numuri: " + " | ".join(report["problems"]), error=True)

    def on_copy_mapping(self) -> None:
        pages = self.selected_pages()
        if not pages:
            self.ctx.report("Nav atlasīta neviena lapa", error=True)
            return
        try:
            clipboard = self.ctx.controller.copy_mapping(pages)
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        self.ctx.report(f"Nokopēts: {clipboard.summary()}")

    def on_restore(self) -> None:
        """RESTORE SNAPSHOT: pick an older plan from JOB/CONFIG/history and put it back."""
        try:
            snapshots = self.ctx.controller.snapshots()
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        if not snapshots:
            self.ctx.report("Nav nevienas plāna kopijas (JOB/CONFIG/history)", error=True)
            return
        dialog = self.snapshot_dialog_factory(self.ctx.window, snapshots=snapshots)
        self._wait(dialog)
        name = getattr(dialog, "result", None)
        if not name:
            return
        try:
            result = self.ctx.controller.restore_snapshot(name)
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        self.ctx.report("RESTORE: " + result.summary())
        self.ctx.refresh()

    def on_undo(self) -> None:
        """UNDO PLAN CHANGE: put the previous plan back (the restore is reversible)."""
        try:
            result = self.ctx.controller.undo_plan_change()
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        if result is None:
            self.ctx.report("UNDO: nav ko atgriezt (nav nevienas plāna kopijas)")
            return
        self.ctx.report("UNDO: " + result.summary())
        self.ctx.refresh()

    def on_paste_mapping(self) -> None:
        pages = self.selected_pages()
        try:
            report = self.ctx.controller.paste_mapping(pages or None)
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        self.ctx.report(
            f"Ielīmēts {report['pdf']} lapās {self.ctx.controller.format_pages(report['pasted_pages'])}"
            + (f" | izlaistas {report['skipped_pages']}" if report["skipped_pages"] else "")
            + (f" | neizmantotas {report['unused_pages']}" if report["unused_pages"] else "")
            + (f" | bez vietas {report['truncated']}" if report["truncated"] else "")
        )
        self.ctx.refresh()

    def on_save_preset(self) -> None:
        pdf = self.ctx.controller.active_pdf
        default_name = f"{pdf.stem if pdf else 'job'}_mapping"
        dialog = self.save_preset_dialog_factory(self.ctx.window, default_name=default_name)
        self._wait(dialog)
        name = getattr(dialog, "result", None)
        if not name:
            return
        self._handle(
            lambda: self.ctx.controller.save_preset(name),
            f"Preset saglabāts: {name}.json (JOB/CONFIG/presets)",
        )

    def on_apply_preset(self) -> None:
        """LOAD / APPLY PRESET: pick, read the conflict preview, then apply."""
        try:
            presets = self.ctx.controller.presets()
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        if not presets:
            self.ctx.report("Nav neviena preseta (JOB/CONFIG/presets)", error=True)
            return
        dialog = self.preset_dialog_factory(
            self.ctx.window,
            presets=presets,
            preview=self.ctx.controller.preset_preview,
        )
        self._wait(dialog)
        answer = getattr(dialog, "result", None)
        if not answer:
            return
        try:
            report = self.ctx.controller.apply_preset(
                answer["name"], replace_all=bool(answer.get("replace_all"))
            )
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        self.ctx.report(
            f"Preset {report['name']}: mainītas {len(report['changed'])} lapas"
            + (f", atiestatītas {len(report['reset'])}" if report["reset"] else "")
            + (f", ārpus dokumenta {report['skipped_pages']}" if report["skipped_pages"] else "")
        )
        self.ctx.refresh()

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
        self._wait(dialog)
        return getattr(dialog, "result", None)

    def _show_document(self) -> None:
        """The header: exactly which PDF this table edits (and its status)."""
        try:
            row = self.ctx.controller.active_document()
        except ControllerError as exc:
            self.document_label.configure(text="PDF: -")
            self.document_detail.configure(text=str(exc))
            return
        if row is None:
            self.document_label.configure(text="PDF: -")
            self.document_detail.configure(text="PROJECT tabā atver JOB, tad PDF tabā izvēlies dokumentu")
            return
        self.document_label.configure(text=f"PDF: {row.name} | Lapas: {row.page_count}")
        self.document_detail.configure(
            text=f"{row.status_text} | {row.config_status} | rinda: {row.queue_status}"
        )

    def on_reconcile(self) -> None:
        """RECONCILE the active document after its PDF page count changed.

        Explicit by design: nothing in the pipeline rewrites a mapping on its own, so
        the operator confirms and then sees exactly what happened.
        """
        controller = self.ctx.controller
        try:
            row = controller.active_document()
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        if row is None:
            self.ctx.report("Nav izvēlēts PDF", error=True)
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
            report = controller.reconcile_document(row.name)
        except ControllerError as exc:
            self.ctx.report(str(exc), error=True)
            return
        added = ", ".join(str(page) for page in report.get("added") or []) or "-"
        removed = ", ".join(str(page) for page in report.get("removed") or []) or "-"
        restored = ", ".join(str(page) for page in report.get("restored") or []) or "-"
        self.ctx.report(
            f"RECONCILE {report.get('pdf')}: {report.get('stored')} -> {report.get('current')} lapas | "
            f"pievienotas {added} | noņemtas {removed} | atjaunotas {restored}"
        )
        self.ctx.refresh()

    def _on_selection(self, _event: Any = None, *, focus: int | None = None) -> None:
        rows = [row for row in self._rows if row.job_id in set(self.selected_job_ids())]
        if self.preview_panel is not None:
            pages = sorted(row.page for row in rows)
            target = focus if focus is not None else (rows[0].page if rows else None)
            self.preview_panel.select_pages(pages, focus=target)
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

    # ------------------------------------------------------------------ preview

    def on_preview_select(self, pages: list[int], focus: int | None = None) -> None:
        """A thumbnail click: mirror it into the Treeview (the selection authority)."""
        by_page = {row.page: row.job_id for row in self._rows}
        job_ids = [by_page[page] for page in pages if page in by_page]
        self.tree.selection_remove(*self.tree.selection())
        for job_id in job_ids:
            self.tree.selection_add(job_id)
        if focus is not None and focus in by_page:
            self.tree.see(by_page[focus])
        self._on_selection(focus=focus)  # panel + detail follow immediately

    def on_preview_action(self, name: str, pages: list[int] | None = None) -> None:
        """Preview buttons reuse the existing mapping actions (no new semantics).

        `pages` is what the operator sees selected in the thumbnail browser; it is
        mirrored into the Treeview FIRST, because the Treeview stays the single
        source of truth for the selection the actions work on.
        """
        self._apply_preview_selection(pages)
        handlers = {
            "assign": self.on_assign_template,
            "default": self.on_use_default,
            "enable": self.on_enable,
            "disable": self.on_disable,
            "reset": self.on_reset,
            "open_output": self.on_open_output,
        }
        handler = handlers.get(name)
        if handler is None:
            return
        handler()

    def _apply_preview_selection(self, pages: list[int] | None) -> None:
        """Make the Treeview selection match the preview's (when they differ)."""
        if not pages:
            return
        by_page = {row.page: row.job_id for row in self._rows}
        job_ids = sorted(by_page[page] for page in pages if page in by_page)
        if not job_ids or sorted(self.selected_job_ids()) == job_ids:
            return
        self.tree.selection_remove(*self.tree.selection())
        for job_id in job_ids:
            self.tree.selection_add(job_id)
        self.tree.see(job_ids[0])
        self._on_selection()

    def on_open_output(self) -> None:
        """OPEN OUTPUT: hand a DONE page's AI to the OS default (never edited here)."""
        pages = self.selected_pages()
        row = next((candidate for candidate in self._rows if pages and candidate.page == pages[0]), None)
        if row is None:
            self.ctx.report("Nav atlasīta neviena lapa", error=True)
            return
        path = Path(str(row.output_path))
        if row.state != state.DONE:
            self.ctx.report(
                f"Lapa {row.page_label}: stāvoklis {row.state}, nevis DONE - output netiek atvērts",
                error=True,
            )
            return
        if not path.is_file():
            self.ctx.report(
                f"Output nav atrasts: {path.name} (state DONE) - pārbaudi ar VALIDATE", error=True
            )
            return
        try:
            self.ctx.open_file(path)
        except Exception as exc:  # noqa: BLE001 - opening a file is best effort
            self.ctx.report(f"Output nevar atvērt: {exc}", error=True)
            return
        self.ctx.report(f"Atveru output: {path.name}")

    def on_preview_result(self, result: Any) -> None:
        """Forward one finished render (called by the window's event pump)."""
        if self.preview_panel is not None:
            self.preview_panel.on_preview_result(result)

    def _sync_preview(self) -> None:
        """Show the active document in the preview pane (thumbnails + preview)."""
        if self.preview_panel is None:
            return
        try:
            document = self.ctx.controller.active_document()
        except ControllerError:
            document = None
        pdf = self.ctx.controller.active_pdf if document is not None else None
        self.preview_panel.show_document(pdf, self._rows, document)

    # ------------------------------------------------------------------ refresh

    def refresh(self, *_args: Any) -> None:
        keep = set(self.tree.selection())  # an action must not lose the selection
        self._show_document()
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
        self._sync_preview()
        if self.report.get("1.0", tk.END).strip() == "":
            self._set_report(self.ctx.controller.validation_report())

    def set_busy(self, busy: bool) -> None:
        """While a batch runs, plan edits are disabled (the worker owns state.json)."""
        for button in self._buttons:
            button.configure(state="disabled" if busy else "normal")
        if self.preview_panel is not None:
            self.preview_panel.set_busy(busy)
