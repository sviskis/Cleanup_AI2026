"""The dark visual language of the GUI: one COLORS dict, one ttk pass, themed widgets.

This module is the ONLY place in the GUI that knows a colour. Every widget of the
window is built from the classes below, so the palette, the fonts and the borders are
changed in exactly one place (and `tests/test_gui_theme.py` fails when a hex literal
appears anywhere else under `gui/`).

    COLORS      the palette (dark shell, blue-gray text, one accent)
    FONTS       Segoe UI sizes for the hierarchy (title / heading / body / small / mono)
    apply_theme one pass over customtkinter AND ttk (the Treeview stays ttk - there is
                no CTk table widget - so the ttk style is themed here as well)

The widget classes are thin subclasses of the customtkinter widgets: they only apply
palette defaults ("the border is always `border_soft`, 1 px because tkinter has no
sub-pixel lines") and keep the ttk style read/write access (`label["text"]`) that the
tabs, the tests and the acceptance drivers already use.

No GUI logic lives here: no controller, no queue, no state.json, no COM.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

import customtkinter as ctk

# ----------------------------------------------------------------------------- palette

#: The single source of the dark theme (the mockup's values are the shell, the sidebar,
#: the cards and the accents; everything else is a shade of those).
COLORS = {
    # shell surfaces
    "bg": "#0f1117",            # main shell
    "sidebar": "#0d1018",       # left sidebar
    "card": "#161925",          # cards / tables / panels
    "card_alt": "#1b2030",      # a raised element inside a card (hover, bars)
    "panel": "#12151f",         # right action panel
    "input": "#11141d",         # entries and text areas
    # lines (1 px - tkinter has no sub-pixel borders)
    "border": "#4a5568",        # the mockup's muted tone, used as the border
    "border_soft": "#232838",   # inner separators
    # interaction
    "hover": "#1f2839",
    "selected": "#1d2b3f",
    # text (monochromatic blue-gray)
    "text": "#e2e8f0",          # primary
    "text_secondary": "#a0aec0",  # secondary
    "muted": "#4a5568",         # muted / disabled
    "on_accent": "#0f1117",     # text on the accent fill
    # accent
    "accent": "#63b3ed",
    "accent_dim": "#2b6cb0",
    # status dots and state tones
    "green": "#68d391",
    "amber": "#f6ad55",
    "purple": "#b794f4",
    "red": "#fc8181",
}

#: tone -> colour of a status dot / a state label (the three mockup dot colours plus
#: the two that carry a real meaning in this application: red = error, accent = busy).
TONE_COLORS = {
    "ok": COLORS["green"],
    "warn": COLORS["amber"],
    "busy": COLORS["accent"],
    "idle": COLORS["text_secondary"],
    "muted": COLORS["muted"],
    "error": COLORS["red"],
    "unknown": COLORS["purple"],  # the mockup's purple dot: "not known yet"
}

#: The queue states of `core/state.py` (and the preview-only state) mapped onto a tone.
#: Only the mapping lives here - the state machine itself stays in the core.
STATE_TONES = {
    "DONE": "ok",
    "ERROR": "error",
    "INTERRUPTED": "warn",
    "SKIPPED": "muted",
    "RUNNING": "busy",
    "WAITING": "idle",
    "PREVIEW ERROR": "error",
}

FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"

#: The type hierarchy: three levels of text, one metric line for the advisor cards.
FONTS = {
    "title": (FONT_FAMILY, 14, "bold"),
    "heading": (FONT_FAMILY, 12, "bold"),
    "body": (FONT_FAMILY, 11),
    "small": (FONT_FAMILY, 10),
    #: CTkButton text: a third larger than "small" and bold (the click targets)
    "button": (FONT_FAMILY, 13, "bold"),
    #: the value line of a top bar chip: a third larger than "small" and bold
    "chip": (FONT_FAMILY, 13, "bold"),
    "micro": (FONT_FAMILY, 9),
    "metric": (FONT_FAMILY, 18, "bold"),
    "mono": (FONT_MONO, 10),
}

#: fixed metrics of the shell (kept next to the palette so the layout is one idea)
SIDEBAR_WIDTH = 196
ACTION_PANEL_WIDTH = 268
ROW_HEIGHT = 30
BORDER = 1  # the smallest border tkinter can draw



# ------------------------------------------------------------------- theme application


def apply_theme(root: Any = None) -> ttk.Style | None:
    """Make the whole application dark: customtkinter first, then ttk and tk options.

    Call it once without a root (the customtkinter defaults) and once with the window
    (the ttk style and the native tk options). Returns the configured style - or None
    when no root was given.

    A root is required for the ttk part on purpose: `ttk.Style()` without a master
    creates a *plain* `tkinter.Tk` and makes it the default root, and every master-less
    Tk object of the GUI (a `tk.PhotoImage`, a `tk.BooleanVar`) would then be created in
    that hidden interpreter and be invisible to the window - the classic
    `image "pyimageN" doesn't exist` failure.
    """
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    if root is None:
        return None
    try:
        root.configure(fg_color=COLORS["bg"])
    except (tk.TclError, ValueError):  # pragma: no cover - a non CTk root
        pass
    _style_tk_options(root)
    style = ttk.Style(root)
    _style_ttk(style)
    return style


def _style_tk_options(root: Any) -> None:
    """The native bits (the dropdown menu of a CTkOptionMenu, list boxes) follow too."""
    options = (
        ("*Menu.background", COLORS["card"]),
        ("*Menu.foreground", COLORS["text"]),
        ("*Menu.activeBackground", COLORS["accent"]),
        ("*Menu.activeForeground", COLORS["on_accent"]),
        ("*Menu.relief", "flat"),
        ("*Menu.borderWidth", BORDER),
        ("*Listbox.background", COLORS["card"]),
        ("*Listbox.foreground", COLORS["text"]),
        ("*Listbox.selectBackground", COLORS["accent"]),
        ("*Listbox.selectForeground", COLORS["on_accent"]),
        ("*Listbox.highlightThickness", 0),
        ("*Listbox.borderWidth", 0),
        ("*TCombobox*Listbox.background", COLORS["card"]),
        ("*TCombobox*Listbox.foreground", COLORS["text"]),
        ("*TCombobox*Listbox.selectBackground", COLORS["accent"]),
        ("*Toplevel.background", COLORS["bg"]),
    )
    for pattern, value in options:
        try:
            root.option_add(pattern, value)
        except tk.TclError:  # pragma: no cover - an option the platform does not know
            continue


# --------------------------------------------------------------------------- helpers


def tone_color(tone: str) -> str:
    """The colour of a tone (ok / warn / busy / idle / muted / error / unknown)."""
    return TONE_COLORS.get(str(tone), TONE_COLORS["unknown"])


def state_color(name: str) -> str:
    """The colour of a queue state (DONE, ERROR, ...) or of an unknown state."""
    return tone_color(STATE_TONES.get(str(name), "unknown"))




def _style_ttk(style: ttk.Style) -> None:
    """The ttk widgets that must keep working (Treeview, scrollbars, separators)."""
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure(
        "Treeview",
        background=COLORS["card"],
        fieldbackground=COLORS["card"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border_soft"],
        borderwidth=0,
        relief="flat",
        rowheight=24,
        font=FONTS["small"],
    )
    style.map(
        "Treeview",
        background=[("selected", COLORS["selected"])],
        foreground=[("selected", COLORS["text"])],
    )
    style.configure(
        "Treeview.Heading",
        background=COLORS["card_alt"],
        foreground=COLORS["text_secondary"],
        bordercolor=COLORS["border_soft"],
        borderwidth=0,
        relief="flat",
        padding=(4, 4),
        font=FONTS["micro"],
    )
    style.map("Treeview.Heading", background=[("active", COLORS["hover"])])
    style.configure(
        "TScrollbar",
        background=COLORS["card_alt"],
        troughcolor=COLORS["bg"],
        bordercolor=COLORS["bg"],
        arrowcolor=COLORS["text_secondary"],
        borderwidth=0,
        relief="flat",
    )
    style.map("TScrollbar", background=[("active", COLORS["border"])])
    style.configure("TSeparator", background=COLORS["border_soft"])
    style.configure("TPanedwindow", background=COLORS["bg"])
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
    style.configure(
        "TLabelframe", background=COLORS["bg"], bordercolor=COLORS["border_soft"], borderwidth=BORDER
    )
    style.configure(
        "TLabelframe.Label",
        background=COLORS["bg"],
        foreground=COLORS["text_secondary"],
        font=FONTS["small"],
    )
    style.configure(
        "TCombobox",
        fieldbackground=COLORS["input"],
        background=COLORS["card_alt"],
        foreground=COLORS["text"],
        arrowcolor=COLORS["text_secondary"],
        bordercolor=COLORS["border_soft"],
        lightcolor=COLORS["input"],
        darkcolor=COLORS["input"],
        insertcolor=COLORS["text"],
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", COLORS["input"])],
        foreground=[("readonly", COLORS["text"])],
    )
    style.configure(
        "TEntry",
        fieldbackground=COLORS["input"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border_soft"],
        insertcolor=COLORS["text"],
    )
    style.configure(
        "TProgressbar",
        background=COLORS["accent"],
        troughcolor=COLORS["card_alt"],
        bordercolor=COLORS["bg"],
        lightcolor=COLORS["accent"],
        darkcolor=COLORS["accent"],
    )
    style.configure(
        "TCheckbutton",
        background=COLORS["bg"],
        foreground=COLORS["text_secondary"],
        font=FONTS["small"],
    )


# --------------------------------------------------------------- widgets (ttk style access)


class Readable:
    """`widget["text"]` / `widget["state"]` - the ttk style access the GUI already uses.

    customtkinter widgets only answer through `cget`/`configure`; the tabs, the tests
    and the acceptance drivers read and write `widget[...]`, so the themed classes
    bridge the two. Nothing else is added here - the widgets stay customtkinter's.
    """

    def __getitem__(self, key: str) -> Any:
        return self.cget(key)  # type: ignore[attr-defined]

    def __setitem__(self, key: str, value: Any) -> None:
        self.configure(**{key: value})  # type: ignore[attr-defined]

def state_colours() -> dict[str, str]:
    """Every known state with its colour (the Treeview tags and the tiles use it)."""
    return {name: tone_color(tone) for name, tone in STATE_TONES.items()}


class Frame(Readable, ctk.CTkFrame):
    """A plain themed container (the main shell colour, square, borderless)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", COLORS["bg"])
        kwargs.setdefault("corner_radius", 0)
        kwargs.setdefault("border_width", 0)
        super().__init__(master, **kwargs)


class Card(Frame):
    """A card: the mockup's raised surface with a 1 px border and a radius."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", COLORS["card"])
        kwargs.setdefault("corner_radius", 8)
        kwargs.setdefault("border_width", BORDER)
        kwargs.setdefault("border_color", COLORS["border_soft"])
        super().__init__(master, **kwargs)


class Label(Readable, ctk.CTkLabel):
    """A themed text label (secondary text, left aligned, transparent background)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("text_color", COLORS["text_secondary"])
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("anchor", "w")
        kwargs.setdefault("font", FONTS["small"])
        super().__init__(master, **kwargs)


class Title(Label):
    """A section or page heading (primary text, bold)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("text_color", COLORS["text"])
        kwargs.setdefault("font", FONTS["title"])
        super().__init__(master, **kwargs)


class Heading(Label):
    """A card heading (primary text, bold, smaller than a title)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("text_color", COLORS["text"])
        kwargs.setdefault("font", FONTS["heading"])
        super().__init__(master, **kwargs)


class Body(Label):
    """Body text (primary colour, regular weight)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("text_color", COLORS["text"])
        kwargs.setdefault("font", FONTS["body"])
        super().__init__(master, **kwargs)


class Muted(Label):
    """Muted helper text (the third level of the hierarchy)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("text_color", COLORS["muted"])
        super().__init__(master, **kwargs)


class Metric(Label):
    """The big number of an advisor card."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("text_color", COLORS["text"])
        kwargs.setdefault("font", FONTS["metric"])
        super().__init__(master, **kwargs)


class Button(Readable, ctk.CTkButton):
    """A themed button. `kind` picks the role: ghost, primary, accent, quiet, danger."""

    KINDS = {
        # a normal action in a group
        "ghost": {
            "fg_color": COLORS["card_alt"],
            "hover_color": COLORS["hover"],
            "border_width": BORDER,
            "border_color": COLORS["border_soft"],
            "text_color": COLORS["text_secondary"],
        },
        # the primary action of its group (the mockup's outlined accent button)
        "primary": {
            "fg_color": COLORS["card_alt"],
            "hover_color": COLORS["hover"],
            "border_width": BORDER,
            "border_color": COLORS["accent"],
            "text_color": COLORS["text"],
        },
        # the one filled action of the window (the run loop)
        "accent": {
            "fg_color": COLORS["accent"],
            "hover_color": COLORS["accent_dim"],
            "border_width": 0,
            "text_color": COLORS["on_accent"],
        },
        # a navigation / inline element without a box
        "quiet": {
            "fg_color": "transparent",
            "hover_color": COLORS["hover"],
            "border_width": 0,
            "text_color": COLORS["text_secondary"],
        },
        # a destructive or attention action
        "danger": {
            "fg_color": COLORS["card_alt"],
            "hover_color": COLORS["hover"],
            "border_width": BORDER,
            "border_color": COLORS["red"],
            "text_color": COLORS["red"],
        },
    }

    def __init__(self, master: Any = None, *, kind: str = "ghost", **kwargs: Any) -> None:
        defaults = dict(self.KINDS.get(kind, self.KINDS["ghost"]))
        defaults.setdefault("corner_radius", 6)
        defaults.setdefault("height", ROW_HEIGHT)
        defaults.setdefault("font", FONTS["button"])
        defaults.setdefault("anchor", "w")
        defaults["text_color_disabled"] = COLORS["muted"]
        defaults.update(kwargs)
        super().__init__(master, **defaults)



class CheckBox(Readable, ctk.CTkCheckBox):
    """A themed check box (accent tick, secondary label)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", COLORS["accent"])
        kwargs.setdefault("hover_color", COLORS["accent_dim"])
        kwargs.setdefault("border_color", COLORS["border"])
        kwargs.setdefault("checkmark_color", COLORS["on_accent"])
        kwargs.setdefault("text_color", COLORS["text_secondary"])
        kwargs.setdefault("text_color_disabled", COLORS["muted"])
        kwargs.setdefault("font", FONTS["small"])
        kwargs.setdefault("corner_radius", 4)
        kwargs.setdefault("checkbox_width", 18)
        kwargs.setdefault("checkbox_height", 18)
        super().__init__(master, **kwargs)


class Entry(Readable, ctk.CTkEntry):
    """A themed single line input."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", COLORS["input"])
        kwargs.setdefault("border_color", COLORS["border_soft"])
        kwargs.setdefault("border_width", BORDER)
        kwargs.setdefault("text_color", COLORS["text"])
        kwargs.setdefault("corner_radius", 6)
        kwargs.setdefault("height", ROW_HEIGHT)
        kwargs.setdefault("font", FONTS["body"])
        super().__init__(master, **kwargs)


class OptionMenu(Readable, ctk.CTkOptionMenu):
    """A themed dropdown (replaces the ttk.Combobox of the dialogs)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", COLORS["input"])
        kwargs.setdefault("button_color", COLORS["card_alt"])
        kwargs.setdefault("button_hover_color", COLORS["hover"])
        kwargs.setdefault("text_color", COLORS["text"])
        kwargs.setdefault("text_color_disabled", COLORS["muted"])
        kwargs.setdefault("dropdown_fg_color", COLORS["card"])
        kwargs.setdefault("dropdown_hover_color", COLORS["hover"])
        kwargs.setdefault("dropdown_text_color", COLORS["text"])
        kwargs.setdefault("font", FONTS["small"])
        kwargs.setdefault("dropdown_font", FONTS["small"])
        kwargs.setdefault("corner_radius", 6)
        kwargs.setdefault("height", ROW_HEIGHT)
        kwargs.setdefault("anchor", "w")
        super().__init__(master, **kwargs)


class ProgressBar(Readable, ctk.CTkProgressBar):
    """A slim accent progress bar.

    Keeps the ttk reading the GUI already had: `bar["value"]` is 0..1000 (the old
    `ttk.Progressbar(maximum=1000)`), while customtkinter itself uses 0.0..1.0.
    """

    SCALE = 1000

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("height", 6)
        kwargs.setdefault("corner_radius", 3)
        kwargs.setdefault("fg_color", COLORS["card_alt"])
        kwargs.setdefault("progress_color", COLORS["accent"])
        kwargs.setdefault("border_width", 0)
        kwargs.pop("maximum", None)  # ttk's maximum is fixed at SCALE here
        super().__init__(master, **kwargs)

    def configure(self, require_redraw: bool = False, **kwargs: Any) -> Any:  # noqa: D102
        value = kwargs.pop("value", None)
        result = super().configure(require_redraw=require_redraw, **kwargs)
        if value is not None:
            self.set(float(value) / self.SCALE)
        return result

    def cget(self, attribute_name: str) -> Any:  # noqa: D102
        if attribute_name == "value":
            return round(self.get() * self.SCALE)
        return super().cget(attribute_name)



class Scrollbar(ctk.CTkScrollbar):
    """A themed scrollbar for the raw tk canvases and list boxes."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", COLORS["bg"])
        kwargs.setdefault("button_color", COLORS["border"])
        kwargs.setdefault("button_hover_color", COLORS["accent_dim"])
        kwargs.setdefault("corner_radius", 6)
        kwargs.setdefault("width", 12)
        super().__init__(master, **kwargs)


class Text(Readable, ctk.CTkTextbox):
    """A themed read-mostly text area (the log view and the report panels)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", COLORS["input"])
        kwargs.setdefault("border_color", COLORS["border_soft"])
        kwargs.setdefault("border_width", BORDER)
        kwargs.setdefault("text_color", COLORS["text_secondary"])
        kwargs.setdefault("font", FONTS["mono"])
        kwargs.setdefault("corner_radius", 6)
        kwargs.setdefault("scrollbar_button_color", COLORS["border_soft"])
        kwargs.setdefault("scrollbar_button_hover_color", COLORS["border"])
        super().__init__(master, **kwargs)


class ScrollableFrame(ctk.CTkScrollableFrame):
    """A themed scrollable container (the sidebar and the right action panel)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", COLORS["card"])
        kwargs.setdefault("corner_radius", 0)
        kwargs.setdefault("border_width", 0)
        kwargs.setdefault("scrollbar_button_color", COLORS["border_soft"])
        kwargs.setdefault("scrollbar_button_hover_color", COLORS["border"])
        super().__init__(master, **kwargs)


class Toplevel(ctk.CTkToplevel):
    """A themed dialog window."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", COLORS["bg"])
        super().__init__(master, **kwargs)


class StatusDot(Frame):
    """The mockup's status dot: an 8 px circle, coloured by tone."""

    SIZE = 8

    def __init__(self, master: Any = None, *, tone: str = "unknown", **kwargs: Any) -> None:
        kwargs["width"] = self.SIZE
        kwargs["height"] = self.SIZE
        kwargs["corner_radius"] = 10  # a circle at this size
        kwargs["fg_color"] = tone_color(tone)
        kwargs.setdefault("bg_color", "transparent")
        super().__init__(master, **kwargs)
        self._tone = tone

    @property
    def tone(self) -> str:
        return self._tone

    def set_tone(self, tone: str) -> None:
        """Colour the dot (ok / warn / busy / idle / error / unknown)."""
        self._tone = tone
        self.configure(fg_color=tone_color(tone))


class Divider(Frame):
    """A hairline separator (1 px is the thinnest line tkinter can draw)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", COLORS["border_soft"])
        kwargs["height"] = BORDER
        kwargs["corner_radius"] = 0
        super().__init__(master, **kwargs)



class ListBox(tk.Listbox):
    """A themed raw list box (customtkinter has no list box; the dialogs need one)."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        kwargs.setdefault("background", COLORS["input"])
        kwargs.setdefault("foreground", COLORS["text"])
        kwargs.setdefault("selectbackground", COLORS["accent"])
        kwargs.setdefault("selectforeground", COLORS["on_accent"])
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("borderwidth", 0)
        kwargs.setdefault("relief", "flat")
        kwargs.setdefault("activestyle", "none")
        kwargs.setdefault("exportselection", False)
        kwargs.setdefault("font", FONTS["body"])
        super().__init__(master, **kwargs)

