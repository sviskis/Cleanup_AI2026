"""Dialogs for the bulk mapping actions (MAPPING tab, milestone 6).

Three modal dialogs, all of them *presentation only*: they collect the operator's
input, validate the range text with the CORE parser (`AppController.parse_pages`,
which is `core/mapping_rules.parse_pages`) and hand the values back. No mapping rule,
no config access and no file IO happens here.

    RangeAssignDialog   ASSIGN TO RANGE   (pages + template + layer + enable)
    SavePresetDialog    SAVE PRESET       (preset name)
    PresetDialog        LOAD / APPLY PRESET (list + preview + replace option)

Each dialog exposes `result` (``None`` when cancelled), which is also how the
acceptance drivers answer them without a user.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable

DEFAULT_CHOICE = "<noklusētais template>"
ENABLE_CHOICES = ("nemainīt", "iespējot", "izslēgt")
RANGE_HINT = "1 | 1-5 | 1,3,5 | 1-5,8,10-14 | * = visas"


class SavePresetDialog(tk.Toplevel):
    """SAVE PRESET: name of the preset file (JOB/CONFIG/presets/<name>.json)."""

    def __init__(self, parent: tk.Misc, *, default_name: str = "") -> None:
        super().__init__(parent)
        self.title("Saglabāt preset")
        self.transient(parent)
        self.resizable(False, False)
        self.result: str | None = None

        self.columnconfigure(1, weight=1)
        ttk.Label(self, text="Nosaukums:").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        self.name_var = tk.StringVar(value=default_name)
        entry = ttk.Entry(self, textvariable=self.name_var, width=36)
        entry.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(10, 2))
        entry.focus_set()
        entry.select_range(0, tk.END)
        ttk.Label(self, text="Fails: JOB/CONFIG/presets/<nosaukums>.json", foreground="#666").grid(
            row=1, column=1, sticky="w", padx=(0, 10)
        )
        self.error = ttk.Label(self, text="", foreground="#b00020", wraplength=380, justify="left")
        self.error.grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(4, 0))

        buttons = ttk.Frame(self, padding=10)
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew")
        for index in range(2):
            buttons.columnconfigure(index, weight=1)
        ttk.Button(buttons, text="SAGLABĀT", command=self._accept).grid(row=0, column=0, sticky="ew", padx=2)
        ttk.Button(buttons, text="ATCAUKT", command=self._cancel).grid(row=0, column=1, sticky="ew", padx=2)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _event: self._accept())

    def _accept(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            self.error.configure(text="Nosaukums ir tukšs")
            return
        self.result = name
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class RangeAssignDialog(tk.Toplevel):
    """ASSIGN TO RANGE: one template (and layer) for a whole page selection."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        page_count: int,
        choices: list[str],
        parse: Callable[[str], list[int]],
        current_template: str = "",
        current_layer: str = "ARTWORK",
        on_browse: Callable[[list[str]], list[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Piešķirt template lapu diapazonam")
        self.transient(parent)
        self.resizable(False, False)
        self.result: dict | None = None
        self._parse = parse
        self._page_count = int(page_count or 0)
        self._choices = list(choices)
        self._on_browse = on_browse

        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=f"Lapas (1-{self._page_count or '?'}):").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 2)
        )
        self.pages_var = tk.StringVar(value="")
        pages_entry = ttk.Entry(self, textvariable=self.pages_var, width=32)
        pages_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(10, 2))
        pages_entry.focus_set()
        ttk.Label(self, text=RANGE_HINT, foreground="#666").grid(
            row=1, column=1, sticky="w", padx=(0, 10)
        )

        ttk.Label(self, text="Template:").grid(row=2, column=0, sticky="w", padx=10, pady=2)
        self.template_var = tk.StringVar(value=current_template or DEFAULT_CHOICE)
        self.template_box = ttk.Combobox(
            self,
            textvariable=self.template_var,
            values=[DEFAULT_CHOICE, *self._choices],
            state="readonly",
            width=30,
        )
        self.template_box.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=2)
        ttk.Button(self, text="PĀRLŪKOT...", command=self._browse).grid(row=2, column=2, padx=(0, 10))

        ttk.Label(self, text="Layer:").grid(row=3, column=0, sticky="w", padx=10, pady=2)
        self.layer_var = tk.StringVar(value=current_layer or "ARTWORK")
        ttk.Entry(self, textvariable=self.layer_var, width=32).grid(
            row=3, column=1, sticky="ew", padx=(0, 10), pady=2
        )

        ttk.Label(self, text="Iespējot:").grid(row=4, column=0, sticky="w", padx=10, pady=2)
        self.enable_var = tk.StringVar(value=ENABLE_CHOICES[0])
        ttk.Combobox(
            self, textvariable=self.enable_var, values=list(ENABLE_CHOICES), state="readonly", width=28
        ).grid(row=4, column=1, sticky="ew", padx=(0, 10), pady=2)

        self.error = ttk.Label(self, text="", foreground="#b00020", wraplength=380, justify="left")
        self.error.grid(row=5, column=0, columnspan=3, sticky="w", padx=10, pady=(4, 0))

        buttons = ttk.Frame(self, padding=10)
        buttons.grid(row=6, column=0, columnspan=3, sticky="ew")
        for index in range(2):
            buttons.columnconfigure(index, weight=1)
        ttk.Button(buttons, text="PIEŠĶIRT", command=self._accept).grid(row=0, column=0, sticky="ew", padx=2)
        ttk.Button(buttons, text="ATCAUKT", command=self._cancel).grid(row=0, column=1, sticky="ew", padx=2)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _event: self._accept())

    def _browse(self) -> None:
        if self._on_browse is None or self.template_box.cget("state") != "readonly":
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
            self.template_box.configure(values=[DEFAULT_CHOICE, *self._choices])

    def _accept(self) -> None:
        text = self.pages_var.get()
        try:
            pages = self._parse(text)
        except Exception as exc:  # noqa: BLE001 - a ControllerError message is shown as is
            self.error.configure(text=str(exc))
            return
        if not pages:
            self.error.configure(text="Nav norādīta neviena lapa")
            return
        template = self.template_var.get().strip()
        layer = self.layer_var.get().strip()
        enabled = {"nemainīt": None, "iespējot": True, "izslēgt": False}[self.enable_var.get()]
        self.result = {
            "pages": pages,
            "template": None if template in ("", DEFAULT_CHOICE) else template,
            "layer": layer or None,
            "enabled": enabled,
        }
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class SnapshotDialog(tk.Toplevel):
    """RESTORE SNAPSHOT: pick an older plan from `JOB/CONFIG/history`.

    The list shows what every snapshot holds (timestamp, reason, how many documents and
    pages) and the current plan is snapshotted first, so a restore can be undone.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        snapshots: list,
        current: str = "",
    ) -> None:
        super().__init__(parent)
        self.title("Atjaunot plāna kopiju")
        self.transient(parent)
        self.resizable(True, True)
        self.result: str | None = None
        self._snapshots = list(snapshots)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = "Plāna kopijas mapē JOB/CONFIG/history (jaunākās vispirms)"
        if current:
            header += f" | pašreizējais plāns: {current}"
        ttk.Label(self, text=header).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))

        self.listbox = tk.Listbox(self, height=12, width=76, exportselection=False)
        self.listbox.grid(row=1, column=0, sticky="nsew", padx=10)
        for info in self._snapshots:
            self.listbox.insert(tk.END, info.summary())
        self.listbox.bind("<Double-1>", lambda _event: self._accept())

        ttk.Label(
            self,
            text="Pirms atjaunošanas pašreizējais plāns tiek nokopēts, tāpēc atjaunošanu var arī atcelt.",
            foreground="#666",
        ).grid(row=2, column=0, sticky="w", padx=10, pady=(6, 0))

        buttons = ttk.Frame(self, padding=10)
        buttons.grid(row=3, column=0, sticky="ew")
        for index in range(2):
            buttons.columnconfigure(index, weight=1)
        ttk.Button(buttons, text="ATJAUNOT", command=self._accept).grid(
            row=0, column=0, sticky="ew", padx=2
        )
        ttk.Button(buttons, text="ATCAUKT", command=self._cancel).grid(
            row=0, column=1, sticky="ew", padx=2
        )
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        if self._snapshots:
            self.listbox.selection_set(0)

    def _selected(self):
        selection = self.listbox.curselection()
        if not selection:
            return None
        return self._snapshots[selection[0]]

    def _accept(self) -> None:
        info = self._selected()
        self.result = None if info is None else info.name
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class PresetDialog(tk.Toplevel):
    """LOAD / APPLY PRESET: pick a preset, read its preview, then apply it.

    The preview comes from the core (`AppController.preset_preview`) and is shown
    BEFORE anything is replaced, conflicts included: pages the document does not have
    and template files the preset references but that are missing.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        presets: list,
        preview: Callable[[str], dict],
        replace_all_default: bool = False,
    ) -> None:
        super().__init__(parent)
        self.title("Uzlikt preset")
        self.transient(parent)
        self.resizable(True, True)
        self.result: dict | None = None
        self._presets = list(presets)
        self._preview = preview

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text="Preseti mapē JOB/CONFIG/presets (tiks uzlikti aktīvajam PDF):").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4)
        )

        self.listbox = tk.Listbox(self, height=8, width=64, exportselection=False)
        self.listbox.grid(row=1, column=0, sticky="nsew", padx=10)
        for info in self._presets:
            label = info.summary() if getattr(info, "entries", 0) else f"{info.name} (nav derīgs)"
            self.listbox.insert(tk.END, label)
        self.listbox.bind("<<ListboxSelect>>", lambda _event: self._show_preview())

        self.detail = tk.Text(self, height=7, wrap="none", state="disabled")
        self.detail.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 0))
        detail_scroll = ttk.Scrollbar(self, orient="vertical", command=self.detail.yview)
        detail_scroll.grid(row=2, column=1, sticky="ns", pady=(6, 0))
        self.detail.configure(yscrollcommand=detail_scroll.set)

        self.replace_all_var = tk.BooleanVar(value=bool(replace_all_default))
        ttk.Checkbutton(
            self,
            text="Aizstāt arī pārējās lapas (tās atgriežas pie noklusētā template)",
            variable=self.replace_all_var,
        ).grid(row=3, column=0, sticky="w", padx=10, pady=(6, 0))

        buttons = ttk.Frame(self, padding=10)
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew")
        for index in range(2):
            buttons.columnconfigure(index, weight=1)
        ttk.Button(buttons, text="UZLIKT", command=self._accept).grid(row=0, column=0, sticky="ew", padx=2)
        ttk.Button(buttons, text="ATCAUKT", command=self._cancel).grid(row=0, column=1, sticky="ew", padx=2)
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        if self._presets:
            self.listbox.selection_set(0)
            self._show_preview()

    # ------------------------------------------------------------------ helpers

    def _selected(self):
        selection = self.listbox.curselection()
        if not selection:
            return None
        return self._presets[selection[0]]

    def _write_detail(self, lines: list[str]) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", tk.END)
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.configure(state="disabled")

    def _show_preview(self) -> None:
        """Show the core's preview of the selected preset (conflicts included)."""
        info = self._selected()
        if info is None:
            return
        try:
            preview = self._preview(info.name)
        except Exception as exc:  # noqa: BLE001 - a broken preset is shown, not fatal
            self._write_detail([f"Preset {info.name} nav lietojams:", str(exc)])
            return
        conflicts = preview.get("conflicts") or {}
        beyond = conflicts.get("beyond_page_count") or []
        missing = conflicts.get("missing_templates") or []
        changes = preview.get("would_change") or []
        lines = [
            f"Preset: {preview.get('name')} | noteikumi: {preview.get('entries')} | "
            f"lapas: {preview.get('targets')}",
            f"Mainīsies {len(changes)} lapas"
            + (f" (pirmās: {', '.join(str(item['page']) for item in changes[:10])})" if changes else ""),
        ]
        if beyond:
            lines.append("Ārpus dokumenta (netiks rakstītas): " + ", ".join(str(page) for page in beyond[:20]))
        if missing:
            lines.append("Trūkst template failu: " + ", ".join(missing))
        if not beyond and not missing:
            lines.append("Konfliktu nav.")
        self._write_detail(lines)

    def _accept(self) -> None:
        info = self._selected()
        if info is None:
            self.result = None
            self.destroy()
            return
        self.result = {"name": info.name, "replace_all": bool(self.replace_all_var.get())}
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()
