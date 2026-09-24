"""MAPPING preview pane: thumbnails, large preview, page info, page actions.

All PDF work happens in `gui/preview_loader.py` (worker thread + `pdf_ai_batch/preview`),
this module only turns the resulting PNG bytes into `tk.PhotoImage` objects:

    loader result (PNG bytes) -> tk.PhotoImage -> canvas item

Selection stays exactly where it always was: the MAPPING Treeview (the controller's
plan is the single source of truth). A click here only ASKS the tab to select pages
(`on_select_pages`); the tab then calls `select_pages()` back - one direction, no
duplicated selection state. Template/layer/output/state are never edited here either:
the buttons call the mapping tab, which calls the existing controller/core APIs.

The dark palette comes from `gui/theme.py` (the canvases keep their raw `tk.Canvas`,
because customtkinter has no canvas and the tiles are drawn with canvas items).
"""

from __future__ import annotations

import base64
import tkinter as tk
from pathlib import Path
from typing import Any, Callable

from ..preview.cache import KIND_PREVIEW, KIND_THUMBNAIL
from ..preview.renderer import DEFAULT_THUMBNAIL_WIDTH
from . import shell, theme
from .context import GuiContext

STATE_COLOURS = theme.state_colours()
TILE_BACKGROUND = theme.COLORS["card"]
TILE_SELECTED = theme.COLORS["selected"]
TILE_FOCUS = theme.COLORS["accent"]
TILE_BORDER = theme.COLORS["border_soft"]
TILE_DISABLED = theme.COLORS["card_alt"]
TILE_SLOT = theme.COLORS["input"]
TILE_PAD = 6
TILE_LINE = 16
FALLBACK_ASPECT = 1.4142
ZOOM_STEP = 1.25
MIN_ZOOM = 0.1
MAX_ZOOM = 4.0
INITIAL_THUMBNAILS = 12
NEIGHBOURHOOD = 6
MAX_TILE_IMAGES = 400
DEFAULT_PANE_HEIGHT = 320


class PreviewPanel(theme.Frame):
    """Thumbnail browser + large preview + page info, embedded in the MAPPING tab."""

    def __init__(
        self,
        parent: tk.Misc,
        context: GuiContext,
        loader: Any,
        *,
        thumbnail_width: int = DEFAULT_THUMBNAIL_WIDTH,
        pane_height: int = DEFAULT_PANE_HEIGHT,
    ) -> None:
        super().__init__(parent)
        self.ctx = context
        self.loader = loader
        self.thumbnail_width = int(thumbnail_width)
        self.pane_height = int(pane_height)

        #: wired by the mapping tab
        self.on_select_pages: Callable[[list[int], int | None], None] | None = None
        self.on_action: Callable[[str], None] | None = None

        self._rows: list[Any] = []
        self._state_by_page: dict[int, str] = {}
        self._document: Any = None
        self._pdf: Path | None = None
        self._page_count = 0
        self._selection: list[int] = []
        self._focus: int | None = None
        self._anchor: int | None = None
        self._requested: set[int] = set()
        self._thumb_sizes: dict[int, tuple[int, int]] = {}
        self._errors: dict[int, str] = {}
        self._tiles: dict[int, dict] = {}
        self._images: dict[tuple, tk.PhotoImage] = {}
        self._preview_images: list[tk.PhotoImage] = []
        self._preview_size: tuple[int, int] = (0, 0)
        self._preview_key: tuple = ()
        self._geometry: Any = None
        self._zoom = 0.0  # 0.0 = FIT
        self._columns = 1
        self._content_height = 0.0
        self._buttons: list[Any] = []
        self._busy = False  # the last value pushed to the buttons (a no-op is skipped)
        self._build()


    # ------------------------------------------------------------------ widgets

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        header = theme.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.header_label = theme.Heading(header, text="Lapas: -")
        self.header_label.grid(row=0, column=0, sticky="w")
        self.header_detail = theme.Label(header, text="")
        self.header_detail.grid(row=0, column=1, sticky="e")

        holder = theme.Frame(self, height=self.pane_height)
        holder.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        holder.grid_propagate(False)  # the pane keeps its height; the table below grows
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)

        panes = theme.Frame(holder)
        panes.grid(row=0, column=0, sticky="nsew")
        panes.columnconfigure(0, weight=3)
        panes.columnconfigure(1, weight=5)
        panes.rowconfigure(0, weight=1)

        thumbs = shell.TitledCard(panes, title="Lapas (thumbnail)")
        thumbs.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        thumbs_body = thumbs.body
        thumbs_body.columnconfigure(0, weight=1)
        thumbs_body.rowconfigure(0, weight=1)
        self.thumb_canvas = tk.Canvas(
            thumbs_body, highlightthickness=0, background=TILE_SLOT
        )
        self.thumb_canvas.grid(row=0, column=0, sticky="nsew")
        thumb_scroll = theme.Scrollbar(
            thumbs_body, orientation="vertical", command=self.thumb_canvas.yview
        )
        thumb_scroll.grid(row=0, column=1, sticky="ns")
        self.thumb_canvas.configure(yscrollcommand=thumb_scroll.set)
        self.thumb_canvas.bind("<Button-1>", self._on_thumb_click)
        self.thumb_canvas.bind("<Configure>", self._on_thumb_resize)
        self.thumb_canvas.bind("<MouseWheel>", self._on_wheel)

        preview = shell.TitledCard(panes, title="Priekšskatījums")
        preview.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        preview_body = preview.body
        preview_body.columnconfigure(0, weight=1)
        preview_body.rowconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(
            preview_body, highlightthickness=0, background=TILE_SLOT
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", self._on_preview_resize)
        controls = theme.Frame(preview_body)
        controls.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        for label, command in (
            ("FIT", self.on_fit),
            ("100%", self.on_actual_size),
            ("+", self.on_zoom_in),
            ("-", self.on_zoom_out),
        ):
            button = theme.Button(controls, text=label, width=54, command=command)
            button.pack(side="left", padx=2)
            self._buttons.append(button)
        self.zoom_label = theme.Label(controls, text="fit")
        self.zoom_label.pack(side="left", padx=(8, 0))
        self.output_button = theme.Button(
            controls, text="OPEN OUTPUT", kind="primary", command=lambda: self._action("open_output")
        )
        self.output_button.pack(side="right", padx=2)
        self._buttons.append(self.output_button)

        info = theme.Frame(self)
        info.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        for column in (1, 3):
            info.columnconfigure(column, weight=1)
        self.info_labels: dict[str, Any] = {}
        fields = (
            ("PDF", "pdf"),
            ("Lapa", "page"),
            ("Izmērs", "size"),
            ("Template", "template"),
            ("Layer", "layer"),
            ("Output", "output"),
            ("Statuss", "state"),
            ("Mēģinājumi", "attempts"),
        )
        for index, (label, key) in enumerate(fields):
            line, column = divmod(index, 2)
            theme.Label(info, text=f"{label}:", text_color=theme.COLORS["muted"]).grid(
                row=line, column=column * 2, sticky="nw", pady=1
            )
            value = theme.Label(info, text="-", justify="left", wraplength=460)
            value.grid(row=line, column=column * 2 + 1, sticky="nw", padx=(6, 16), pady=1)
            self.info_labels[key] = value

        self.detail_label = theme.Label(
            self,
            text="",
            text_color=theme.COLORS["red"],
            wraplength=1200,
            justify="left",
        )
        self.detail_label.grid(row=3, column=0, sticky="w", pady=(4, 0))

        bar = theme.Frame(self)
        bar.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        actions = (
            ("ASSIGN TEMPLATE TO SELECTED", "assign", "primary"),
            ("USE DEFAULT TEMPLATE", "default", "ghost"),
            ("ENABLE", "enable", "ghost"),
            ("DISABLE", "disable", "ghost"),
            ("RESET", "reset", "ghost"),
        )
        for index in range(len(actions)):
            bar.columnconfigure(index, weight=1)
        for index, (label, name, kind) in enumerate(actions):
            button = theme.Button(
                bar, text=label, kind=kind, command=lambda value=name: self._action(value)
            )
            button.grid(row=0, column=index, sticky="ew", padx=2)
            self._buttons.append(button)


    # ---------------------------------------------------------------- public API

    def show_document(self, pdf: str | Path | None, rows: list[Any], document: Any = None) -> None:
        """Show one document: (re)build the tiles and start the first renders.

        Called by the MAPPING tab whenever its table refreshes. Only a document or
        page count change rebuilds the tiles; a state change is a cheap text update.
        """
        previous = self._pdf
        new_pdf = Path(pdf) if pdf else None
        changed = previous != new_pdf
        if changed:
            self._reset_for_document(new_pdf)
        self._rows = list(rows)
        self._document = document
        page_count = max((int(row.page) for row in rows), default=0)
        if document is not None:
            page_count = max(page_count, int(getattr(document, "page_count", 0) or 0))
        if page_count != self._page_count:
            self._page_count = page_count
            self._requested.clear()
            self._thumb_sizes.clear()
            self._tiles.clear()
            self._images.clear()
            self._draw_tiles()
        if self._focus is None and self._page_count:
            self._focus = 1  # show page 1 right away, before any click
        self.update_rows(rows)
        self._update_header()
        self._update_info()
        self._request_initial()
        self._request_preview()  # the focused page gets its large preview too

    def update_rows(self, rows: list[Any]) -> None:
        """Cheap state refresh (after a run / a REFRESH STATUS): text only, no render."""
        self._rows = list(rows)
        self._state_by_page = {int(row.page): row.state for row in rows}
        for page, tile in self._tiles.items():
            tile["enabled"] = bool(getattr(self._row_for(page), "enabled", True))
            state = self._state_by_page.get(page, "")
            if page in self._errors:
                state = "PREVIEW ERROR"
            self._set_tile_state(page, state)
        self._update_info()

    def select_pages(self, pages: list[int], focus: int | None = None) -> None:
        """The tab tells us what is selected (single source of truth).

        An empty selection only clears the highlights: the preview pane keeps showing
        the last focused page (that is what the operator expects after SELECT NONE).
        """
        selection = [int(page) for page in pages if int(page) >= 1]
        self._selection = selection
        if focus is not None:
            self._focus = int(focus)
        elif selection and self._focus not in selection:
            self._focus = selection[0]
        self._highlight_tiles()
        self._update_info()
        if self._focus is not None:
            self._anchor = self._focus
            self._ensure_visible(self._focus)
            self._request_preview()
            self._request_around(self._focus)

    def on_preview_result(self, result: Any) -> None:
        """One finished render (from the event pump, Tk thread only)."""
        name = getattr(result, "document_name", "")
        if self._pdf is None or name != self._pdf.name:
            return  # a stale document: the loader already drops those, this is a guard
        page = int(result.page)
        if not result.ok:
            self._errors[page] = str(result.error)
            self._thumb_sizes.pop(page, None)
            self._set_tile_state(page, "PREVIEW ERROR")
            if page == self._focus:
                self.detail_label.configure(text=f"PREVIEW ERROR: {result.error}")
            self._request_next_thumbnail()
            return
        if result.kind == KIND_THUMBNAIL:
            self._thumb_sizes[page] = (int(result.width), int(result.height))
            self._draw_thumbnail(page, result.image)
            self._request_next_thumbnail()
        else:
            self._preview_size = (int(result.width), int(result.height))
            if result.geometry is not None:
                self._geometry = result.geometry
            # `_zoom` stays what the operator asked for (0 = FIT), never the scale
            # the renderer happened to use for that request
            self._draw_preview(result.image)
            self._update_info()

    def set_busy(self, busy: bool) -> None:
        """While a batch runs the page actions are disabled (the worker owns state).

        An unchanged value skips the ten button redraws; `output_button` is written
        from outside this method (`_update_info`), so it is re-asserted on every call
        - that is what keeps the window's pump able to correct it.
        """
        busy = bool(busy)
        if self._busy == busy:
            self._refresh_output_button()
            return
        self._busy = busy
        for button in self._buttons:
            button.configure(state="disabled" if busy else "normal")
        self._refresh_output_button()

    # -------------------------------------------------------------- test access

    def tile_states(self) -> dict[int, str]:
        return {page: str(tile.get("state", "")) for page, tile in self._tiles.items()}

    def tile_errors(self) -> dict[int, str]:
        return dict(self._errors)

    def info_lines(self) -> dict[str, str]:
        return {key: str(label["text"]) for key, label in self.info_labels.items()}

    def selected_pages(self) -> list[int]:
        return list(self._selection)

    def focus_page(self) -> int | None:
        return self._focus

    def preview_size(self) -> tuple[int, int]:
        return self._preview_size

    def thumbnail_count(self) -> int:
        """How many thumbnails are actually painted (images, not placeholders)."""
        return len(self._thumb_sizes)

    def page_count(self) -> int:
        return self._page_count


    # ----------------------------------------------------------------- internals

    def _reset_for_document(self, pdf: Path | None) -> None:
        self._pdf = pdf
        self._page_count = 0
        self._selection = []
        self._focus = None
        self._anchor = None
        self._requested.clear()
        self._thumb_sizes.clear()
        self._tiles.clear()
        self._images.clear()
        self._preview_images.clear()
        self._preview_size = (0, 0)
        self._preview_key = ()
        self._geometry = None
        self._errors.clear()
        self._zoom = 0.0
        self.zoom_label.configure(text="fit")
        self.thumb_canvas.delete("all")
        self.preview_canvas.delete("all")
        try:
            self.loader.cancel()
            self.loader.set_document(pdf)
        except Exception as exc:  # noqa: BLE001 - a preview problem must never break the GUI
            self.ctx.report(f"Preview: {exc}", error=True)

    def _update_header(self) -> None:
        if self._pdf is None:
            self.header_label.configure(text="Lapas: -")
            self.header_detail.configure(text="")
            return
        status = ""
        if self._document is not None:
            status = str(getattr(self._document, "status_text", "") or "")
        self.header_label.configure(text=f"PDF: {self._pdf.name} | Lapas: {self._page_count}")
        detail = status
        if self._errors:
            detail = (detail + " | " if detail else "") + f"preview kļūdas: {len(self._errors)}"
        self.header_detail.configure(text=detail)

    def _row_for(self, page: int | None) -> Any:
        if page is None:
            return None
        return next((row for row in self._rows if int(row.page) == int(page)), None)

    def _update_info(self) -> None:
        row = self._row_for(self._focus)
        if row is None:
            for key, label in self.info_labels.items():
                label.configure(text="-" if key != "pdf" else (self._pdf.name if self._pdf else "-"))
            self.detail_label.configure(text="")
            return
        geometry = self._geometry
        size = geometry.size_label if geometry is not None and geometry.page == row.page else "-"
        output_missing = False
        try:
            output_missing = row.state == "DONE" and not Path(row.output_path).is_file()
        except Exception:  # noqa: BLE001 - a broken path is informational only
            output_missing = False
        self.info_labels["pdf"].configure(text=self._pdf.name if self._pdf else "-")
        self.info_labels["page"].configure(
            text=f"{row.page} / {self._page_count}" if self._page_count else str(row.page)
        )
        self.info_labels["size"].configure(text=size)
        self.info_labels["template"].configure(text=row.template or "(noklusētais)")
        self.info_labels["layer"].configure(text=row.layer)
        self.info_labels["output"].configure(
            text=row.output + ("  [nav atrasts, lai gan DONE]" if output_missing else "")
        )
        self.info_labels["state"].configure(text=row.state)
        self.info_labels["attempts"].configure(text=str(row.attempts) if row.attempts else "0")

        detail = ""
        if row.state == "ERROR":
            detail = f"{row.error_type or 'ERROR'}: {row.error_message or '(nav ziņas)'}"
        elif row.state == "INTERRUPTED":
            detail = row.error_message or "pārtraukts - CONTINUE to pabeigs"
        elif output_missing:
            detail = f"output nav atrasts: {row.output_path}"
        elif self._errors.get(row.page):
            detail = f"PREVIEW ERROR: {self._errors[row.page]}"
        self.detail_label.configure(text=detail)
        self._refresh_output_button()

    def _refresh_output_button(self) -> None:
        """OPEN OUTPUT follows the focused page - `_update_info` writes it as well.

        The wanted state is compared with the state the button really has, so a write
        from outside `set_busy` is corrected in the same tick, while an unchanged
        button costs nothing (no CustomTkinter redraw every 120 ms).
        """
        row = self._row_for(self._focus)
        wanted = "normal" if row is not None and row.state == "DONE" else "disabled"
        if str(self.output_button.cget("state")) != wanted:
            self.output_button.configure(state=wanted)


    # --------------------------------------------------------------- tile drawing

    def _tile_size(self) -> tuple[int, int]:
        """(width, height) of one tile box: image plus the page label and the state."""
        width = self.thumbnail_width + TILE_PAD * 2
        height = int(self.thumbnail_width * FALLBACK_ASPECT) + TILE_LINE * 2 + TILE_PAD * 2
        return width, height

    def _columns_for_width(self, width: int) -> int:
        tile_width, _height = self._tile_size()
        return max(1, int(width // tile_width)) if width > tile_width else 1

    def _draw_tiles(self) -> None:
        """(Re)build every tile as a placeholder; the images arrive from the worker."""
        self.thumb_canvas.delete("all")
        self._tiles = {}
        if self._page_count < 1:
            self.thumb_canvas.configure(scrollregion=(0, 0, 0, 0))
            return
        width = self.thumb_canvas.winfo_width() or 600
        self._columns = self._columns_for_width(width)
        tile_width, tile_height = self._tile_size()
        slot_height = int(self.thumbnail_width * FALLBACK_ASPECT)
        for page in range(1, self._page_count + 1):
            index = page - 1
            column, line = index % self._columns, index // self._columns
            x, y = TILE_PAD + column * tile_width, TILE_PAD + line * tile_height
            frame = self.thumb_canvas.create_rectangle(
                x, y, x + tile_width - TILE_PAD, y + tile_height - TILE_PAD,
                fill=TILE_BACKGROUND, outline=TILE_BORDER, tags=(f"tile:{page}", "tile"),
            )
            slot = self.thumb_canvas.create_rectangle(
                x + TILE_PAD, y + TILE_PAD, x + tile_width - TILE_PAD * 2, y + TILE_PAD + slot_height,
                fill=TILE_SLOT, outline="", tags=(f"tile:{page}", "slot"),
            )
            label = self.thumb_canvas.create_text(
                x + tile_width // 2, y + tile_height - TILE_LINE * 2 - TILE_PAD // 2,
                text=f"{page:03d}", fill=theme.COLORS["text_secondary"],
                tags=(f"tile:{page}", "page-label"),
            )
            state = self.thumb_canvas.create_text(
                x + tile_width // 2, y + tile_height - TILE_LINE - TILE_PAD // 2,
                text="", fill=STATE_COLOURS["WAITING"], tags=(f"tile:{page}", "state"),
            )
            self._tiles[page] = {
                "x": x, "y": y, "w": tile_width - TILE_PAD, "h": tile_height - TILE_PAD,
                "slot_h": slot_height, "frame": frame, "slot": slot, "label": label,
                "state_item": state, "image": None, "state": "", "enabled": True,
            }
        lines = (self._page_count + self._columns - 1) // self._columns
        self._content_height = float(lines * tile_height)
        self.thumb_canvas.configure(
            scrollregion=(0, 0, self._columns * tile_width, self._content_height)
        )
        for page in self._tiles:
            self._set_tile_state(page, self._state_by_page.get(page, ""))
        self._repaint_thumbnails()

    def _repaint_thumbnails(self) -> None:
        """Put already rendered thumbnails back after a reflow (resize / re-open).

        `_draw_tiles` rebuilds the canvas, so the pictures have to be re-added from
        the decoded image cache - otherwise a window resize would blank the browser
        while `_requested` still says "already queued" (no new render would come).
        """
        for page in list(self._thumb_sizes):
            tile = self._tiles.get(page)
            photo = self._images.get((page, "thumb"))
            if tile is None or photo is None:
                continue
            if tile["image"] is None:
                tile["image"] = self.thumb_canvas.create_image(
                    tile["x"] + tile["w"] // 2,
                    tile["y"] + TILE_PAD + tile["slot_h"] // 2,
                    image=photo,
                    tags=(f"tile:{page}", "photo"),
                )
            else:
                self.thumb_canvas.itemconfigure(tile["image"], image=photo)
        self.thumb_canvas.tag_raise("photo")
        self.thumb_canvas.tag_raise("page-label")
        self.thumb_canvas.tag_raise("state")
        self._highlight_tiles()

    def _draw_thumbnail(self, page: int, image_bytes: bytes) -> None:
        tile = self._tiles.get(page)
        if tile is None or not image_bytes:
            return
        photo = self._photo((page, "thumb"), image_bytes, self.thumb_canvas)
        if photo is None:
            return
        centre_y = tile["y"] + TILE_PAD + tile["slot_h"] // 2
        if tile["image"] is None:
            tile["image"] = self.thumb_canvas.create_image(
                tile["x"] + tile["w"] // 2, centre_y, image=photo, tags=(f"tile:{page}", "photo")
            )
        else:
            self.thumb_canvas.itemconfigure(tile["image"], image=photo)
        self.thumb_canvas.tag_raise("photo")
        self.thumb_canvas.tag_raise("page-label")
        self.thumb_canvas.tag_raise("state")
        self._highlight_tiles()

    def _photo(self, key: tuple, image_bytes: bytes, master: tk.Misc) -> tk.PhotoImage | None:
        """Decode one PNG into a Tk image owned by `master` (never the default root).

        The master matters: an image without one belongs to the default Tk interpreter,
        which is not necessarily the window's (customtkinter and ttk create their own),
        and `create_image` would then fail with `image "pyimageN" doesn't exist`.
        """
        cached = self._images.get(key)
        if cached is not None:
            return cached
        try:
            photo = tk.PhotoImage(
                master=master, data=base64.b64encode(image_bytes).decode("ascii")
            )
        except Exception as exc:  # noqa: BLE001 - a broken image is a preview problem
            self.ctx.report(f"Preview attēlu nevar parādīt: {exc}", error=True)
            return None
        self._images[key] = photo
        self._trim_images()
        return photo


    def _trim_images(self) -> None:
        """Bound the decoded images: drop thumbnails far from the focus first."""
        if len(self._images) <= MAX_TILE_IMAGES:
            return
        focus = self._focus or 1
        ordered = sorted(
            (key for key in self._images if key[1] == "thumb"),
            key=lambda key: abs(int(key[0]) - focus),
            reverse=True,
        )
        drop = len(self._images) - MAX_TILE_IMAGES
        for key in ordered[:drop]:
            page = int(key[0])
            self._images.pop(key, None)
            self._thumb_sizes.pop(page, None)
            tile = self._tiles.get(page)
            if tile and tile["image"] is not None:
                self.thumb_canvas.delete(tile["image"])
                tile["image"] = None
            self._requested.discard(page)

    def _set_tile_state(self, page: int, state: str) -> None:
        tile = self._tiles.get(page)
        if tile is None:
            return
        label = "PREVIEW ERROR" if state == "PREVIEW ERROR" else (state or "-")
        tile["state"] = label
        colour = STATE_COLOURS.get(state, STATE_COLOURS.get("WAITING", theme.COLORS["text"]))
        self.thumb_canvas.itemconfigure(tile["state_item"], text=label, fill=colour)
        enabled = bool(tile.get("enabled", True))
        self.thumb_canvas.itemconfigure(
            tile["frame"], fill=TILE_BACKGROUND if enabled else TILE_DISABLED
        )

    def _highlight_tiles(self) -> None:
        selected = set(self._selection)
        for page, tile in self._tiles.items():
            if page == self._focus:
                self.thumb_canvas.itemconfigure(tile["frame"], outline=TILE_FOCUS, width=2)
            else:
                self.thumb_canvas.itemconfigure(
                    tile["frame"], outline=TILE_FOCUS if page in selected else TILE_BORDER, width=1
                )
            if page in selected:
                self.thumb_canvas.itemconfigure(tile["frame"], fill=TILE_SELECTED)
            elif page != self._focus:
                self.thumb_canvas.itemconfigure(
                    tile["frame"],
                    fill=TILE_BACKGROUND if tile.get("enabled", True) else TILE_DISABLED,
                )

    # ------------------------------------------------------------ large preview

    def _draw_preview(self, image_bytes: bytes) -> None:
        self.preview_canvas.delete("all")
        if not image_bytes:
            return
        photo = self._photo((self._focus or 0, "large"), image_bytes, self.preview_canvas)
        if photo is None:
            return
        self._preview_images = [photo]  # only the newest preview is kept
        width = self.preview_canvas.winfo_width() or photo.width()
        height = self.preview_canvas.winfo_height() or photo.height()
        self.preview_canvas.create_image(width // 2, height // 2, image=photo, tags=("preview",))
        self.preview_canvas.create_text(
            8, height - 8, anchor="sw", fill=theme.COLORS["muted"],
            text=f"{photo.width()} x {photo.height()} px",
        )
        label = "fit" if self._zoom == 0 else f"{self._zoom * 100:.0f}%"
        self.zoom_label.configure(text=label)

    def _preview_long_side(self) -> int:
        """How big the render should be: the pane (FIT) or the zoom target."""
        if self._zoom > 0 and self._geometry is not None:
            longest_pt = max(self._geometry.width_pt, self._geometry.height_pt)
            return int(min(4000, max(200, longest_pt * self._zoom)))
        width = self.preview_canvas.winfo_width() or 600
        height = self.preview_canvas.winfo_height() or 400
        return int(min(1200, max(400, max(width, height) - 12)))

    def _request_preview(self, force: bool = False) -> None:
        if self._focus is None or self._pdf is None:
            return
        zoom = self._zoom
        long_side = self._preview_long_side() if zoom <= 0 else 0
        key = (self._focus, int(long_side), float(zoom))
        if not force and key == self._preview_key and self._preview_size != (0, 0):
            return  # the same page at the same size is already on screen
        self._preview_key = key
        try:
            if zoom > 0:
                self.loader.request_preview(self._focus, zoom=zoom)
            else:
                self.loader.request_preview(self._focus, long_side=long_side)
        except Exception as exc:  # noqa: BLE001
            self.ctx.report(f"Preview: {exc}", error=True)

    def on_fit(self) -> None:
        self._zoom = 0.0
        self.zoom_label.configure(text="fit")
        self._request_preview(force=True)

    def on_actual_size(self) -> None:
        self._zoom = 1.0
        self._request_preview(force=True)

    def on_zoom_in(self) -> None:
        self._zoom = min(MAX_ZOOM, round((self._zoom or 1.0) * ZOOM_STEP, 3))
        self._request_preview(force=True)

    def on_zoom_out(self) -> None:
        self._zoom = max(MIN_ZOOM, round((self._zoom or 1.0) / ZOOM_STEP, 3))
        self._request_preview(force=True)


    # --------------------------------------------------------------- scheduling

    def _ordered_pages(self, start: int | None = None) -> list[int]:
        """Thumbnail render order: around the focus, then outward through the PDF."""
        if self._page_count < 1:
            return []
        pivot = int(start or self._focus or 1)
        pivot = min(max(pivot, 1), self._page_count)
        order: list[int] = []
        for offset in range(0, self._page_count):
            for page in (pivot + offset, pivot - offset):
                if 1 <= page <= self._page_count and page not in order:
                    order.append(page)
        return order

    def _request_around(self, page: int, *, radius: int = NEIGHBOURHOOD) -> int:
        pages = [p for p in range(page - radius, page + radius + 1) if 1 <= p <= self._page_count]
        queued = 0
        for candidate in pages:
            if candidate in self._requested:
                continue
            if self._enqueue_thumbnail(candidate):
                queued += 1
        return queued

    def _request_initial(self) -> int:
        if self._pdf is None or self._page_count < 1:
            return 0
        focus = self._focus if self._focus is not None else (self._selection[0] if self._selection else 1)
        self._request_around(int(focus))
        return self._request_next_thumbnails(INITIAL_THUMBNAILS)

    def _request_next_thumbnail(self) -> int:
        return self._request_next_thumbnails(1)

    def _request_next_thumbnails(self, amount: int) -> int:
        queued = 0
        for page in self._ordered_pages():
            if queued >= int(amount):
                break
            if page in self._requested:
                continue
            if self._enqueue_thumbnail(page):
                queued += 1
        return queued

    def _enqueue_thumbnail(self, page: int) -> bool:
        if page in self._requested:
            return False
        try:
            request = self.loader.request_thumbnail(page)
        except Exception as exc:  # noqa: BLE001
            self.ctx.report(f"Preview: {exc}", error=True)
            return False
        if request is None:
            # already queued in the loader, or no document: remember it either way
            self._requested.add(page)
            return False
        self._requested.add(page)
        return True

    def _request_visible(self) -> int:
        """Ask for the thumbnails the operator can currently see (lazy loading)."""
        if self._page_count < 1:
            return 0
        top = self.thumb_canvas.canvasy(0)
        bottom = self.thumb_canvas.canvasy(self.thumb_canvas.winfo_height() or 300)
        _tile_width, tile_height = self._tile_size()
        first = max(1, int(top // tile_height) * self._columns + 1)
        last = min(self._page_count, (int(bottom // tile_height) + 1) * self._columns + self._columns)
        queued = 0
        for page in range(first, last + 1):
            if page in self._requested:
                continue
            if self._enqueue_thumbnail(page):
                queued += 1
        return queued

    # ------------------------------------------------------------------ events

    def _page_at(self, x: int, y: int) -> int | None:
        canvas_x, canvas_y = self.thumb_canvas.canvasx(x), self.thumb_canvas.canvasy(y)
        for page, tile in self._tiles.items():
            if (
                tile["x"] <= canvas_x <= tile["x"] + tile["w"]
                and tile["y"] <= canvas_y <= tile["y"] + tile["h"]
            ):
                return page
        return None

    def _on_thumb_click(self, event: Any) -> None:
        page = self._page_at(event.x, event.y)
        if page is None:
            return
        control = bool(event.state & 0x0004)
        shift = bool(event.state & 0x0001)
        if shift and self._anchor is not None:
            low, high = sorted((self._anchor, page))
            pages = list(range(low, high + 1))
        elif control:
            pages = [p for p in self._selection if p != page]
            if page not in self._selection:
                pages.append(page)
        else:
            pages = [page]
        self._anchor = page
        if self.on_select_pages is not None:
            self.on_select_pages(sorted(pages), page)

    def _on_wheel(self, event: Any) -> None:
        self.thumb_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        self._request_visible()

    def _on_thumb_resize(self, _event: Any = None) -> None:
        columns = self._columns_for_width(self.thumb_canvas.winfo_width() or 600)
        if columns != self._columns and self._page_count:
            self._draw_tiles()
        self._request_visible()

    def _on_preview_resize(self, _event: Any = None) -> None:
        if self._focus is not None and self._zoom == 0.0:
            self._request_preview()

    def _ensure_visible(self, page: int) -> None:
        """Scroll the browser so the tile of `page` is in view (never past the end)."""
        tile = self._tiles.get(page)
        view = self.thumb_canvas.winfo_height() or 0
        if tile is None or view <= 1 or self._content_height <= 0:
            return  # an unmapped canvas has no usable viewport yet
        top = self.thumb_canvas.canvasy(0)
        tile_top = float(tile["y"])
        tile_bottom = float(tile["y"] + tile["h"])
        if tile_top >= top and tile_bottom <= top + view:
            return  # already fully visible
        if tile_top < top:
            target = max(0.0, tile_top - TILE_PAD)
        else:
            target = min(max(0.0, self._content_height - view), tile_bottom - view + TILE_PAD)
        self.thumb_canvas.yview_moveto(min(1.0, max(0.0, target / self._content_height)))

    def _action(self, name: str) -> None:
        """Page actions stay in the MAPPING tab (existing controller/core calls)."""
        if self.on_action is not None:
            self.on_action(name, list(self._selection))

