"""The window shell of the dark theme: top bar, sidebar, tabs, advisor cards, actions.

Presentation only - every widget here is built from `gui/theme.py`, and none of them
knows the controller: they are told what to show and they report a click. The layout is
the mockup's:

    +---------------------------------------------------------------+  +-----------+
    | project name        status chips            operator / version |  | REVIEW    |
    +---------------------------------------------------------------+  | PLAN      |
    | 1  PROJECT | 2  PDF | 3  MAPPING | 4  RUN / LOG   (tab row)     |  | LOOP      |
    +-----------+-----------------------------------------+---------+  | PROJECT   |
    | 1 PROJEKT | review question + 3 advisor cards        | actions |  | REPORTS   |
    | 2 PDF     | ---------------------------------------- | grouped |  | MONITORING|
    | 3 MAPPING | the section widget (PROJECT/PDF/...)     | by      |  |           |
    | 4 RUN/LOG |                                          | section |  |           |
    +-----------+-----------------------------------------+---------+  +-----------+
    | status line                                          busy label |
    +-----------------------------------------------------------------+

`SectionStack` keeps the small notebook-compatible API (`add`, `tabs`, `tab`, `select`)
the tabs, the tests and the acceptance drivers already use - it is a stacking container,
not a Tk notebook.
"""

from __future__ import annotations

from typing import Any, Callable

from . import theme


class StatusChip(theme.Frame):
    """One pill of the top bar: a status dot, a caption and the value."""

    def __init__(self, master: Any = None, *, caption: str = "", tone: str = "idle", **kwargs: Any) -> None:
        super().__init__(
            master,
            fg_color=theme.COLORS["card"],
            corner_radius=11,
            border_width=theme.BORDER,
            border_color=theme.COLORS["border_soft"],
            height=26,
            **kwargs,
        )
        self.columnconfigure(2, weight=1)
        self.dot = theme.StatusDot(self, tone=tone)
        self.dot.grid(row=0, column=0, padx=(10, 6), pady=6)
        self.caption = theme.Label(self, text=caption, text_color=theme.COLORS["muted"], font=theme.FONTS["micro"])
        self.caption.grid(row=0, column=1, padx=(0, 6))
        #: the value is the readable part of the pill: bigger and bold (the caption
        #: above stays small and muted, so the pair keeps its hierarchy)
        self.value = theme.Label(
            self, text="-", text_color=theme.COLORS["text_secondary"], font=theme.FONTS["chip"]
        )
        self.value.grid(row=0, column=2, padx=(0, 12))

    def set_chip(self, value: str, tone: str | None = None) -> None:
        """Show a new value (and, optionally, a new dot colour)."""
        self.value.configure(text=value)
        if tone is not None:
            self.dot.set_tone(tone)


class TopBar(theme.Frame):
    """Project name left, status chips center, operator / version right."""

    def __init__(self, master: Any = None, *, chips: tuple[tuple[str, str], ...] = (), **kwargs: Any) -> None:
        super().__init__(master, fg_color=theme.COLORS["bg"], **kwargs)
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=0)

        left = theme.Frame(self)
        left.grid(row=0, column=0, sticky="w", padx=(16, 8), pady=(10, 8))
        self.project = theme.Heading(left, text="(nav atvērts)")
        self.project.grid(row=0, column=0, sticky="w")
        self.path = theme.Muted(left, text="")
        self.path.grid(row=1, column=0, sticky="w", pady=(2, 0))

        center = theme.Frame(self)
        center.grid(row=0, column=1, sticky="w", padx=8, pady=(10, 8))
        self.chips: dict[str, StatusChip] = {}
        for column, (key, caption) in enumerate(chips):
            chip = StatusChip(center, caption=caption)
            chip.grid(row=0, column=column, sticky="w", padx=(0, 8))
            self.chips[key] = chip

        right = theme.Frame(self)
        right.grid(row=0, column=2, sticky="e", padx=(8, 16), pady=(10, 8))
        right.columnconfigure(0, weight=1)
        self.operator = theme.Body(right, text="", anchor="e")
        self.operator.grid(row=0, column=0, sticky="e")
        self.version = theme.Muted(right, text="", anchor="e")
        self.version.grid(row=1, column=0, sticky="e", pady=(2, 0))

    def set_project(self, name: str, path: str = "") -> None:
        """The JOB that is open (left block of the top bar)."""
        self.project.configure(text=name)
        self.path.configure(text=path)

    def set_operator(self, name: str, version: str = "") -> None:
        """Who is running this copy (right block of the top bar)."""
        self.operator.configure(text=name)
        self.version.configure(text=version)

    def set_chip(self, key: str, value: str, tone: str | None = None) -> None:
        """Update one chip; an unknown key is ignored (the shell decides what it shows)."""
        chip = self.chips.get(key)
        if chip is not None:
            chip.set_chip(value, tone)


class NavItem(theme.Frame):
    """One numbered sidebar item; the active one carries the accent left border."""

    def __init__(
        self,
        master: Any = None,
        *,
        index: int = 1,
        text: str = "",
        command: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, fg_color=theme.COLORS["sidebar"], corner_radius=6, **kwargs)
        self.columnconfigure(1, weight=1)
        self.bar = theme.Frame(self, width=3, height=22, corner_radius=2, fg_color=theme.COLORS["sidebar"])
        self.bar.grid(row=0, column=0, sticky="ns", pady=6)
        self.button = theme.Button(
            self,
            text=f"{index:02d}   {text}",
            kind="quiet",
            height=34,
            command=command,
        )
        self.button.grid(row=0, column=1, sticky="ew", padx=(6, 4), pady=2)
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        """Highlight (accent bar + selected surface) or dim this item."""
        self._active = bool(active)
        self.configure(fg_color=theme.COLORS["selected"] if self._active else theme.COLORS["sidebar"])
        self.bar.configure(
            fg_color=theme.COLORS["accent"] if self._active else theme.COLORS["sidebar"]
        )
        self.button.configure(
            fg_color=theme.COLORS["selected"] if self._active else "transparent",
            text_color=theme.COLORS["text"] if self._active else theme.COLORS["text_secondary"],
        )


class Sidebar(theme.Frame):
    """The numbered navigation on the left (scrollable, never wider than its column)."""

    def __init__(
        self,
        master: Any = None,
        *,
        title: str = "",
        on_select: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, fg_color=theme.COLORS["sidebar"], **kwargs)
        self.on_select = on_select
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.items: dict[str, NavItem] = {}

        if title:
            theme.Label(
                self,
                text=title,
                text_color=theme.COLORS["muted"],
                font=theme.FONTS["micro"],
            ).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 6))

        self.list = theme.ScrollableFrame(self, fg_color=theme.COLORS["sidebar"])
        self.list.grid(row=1, column=0, sticky="nsew")
        self.list.columnconfigure(0, weight=1)

    def add(self, key: str, label: str, *, index: int) -> NavItem:
        """Add one numbered item and return it."""
        item = NavItem(self.list, index=index, text=label, command=lambda name=key: self._clicked(name))
        item.grid(row=len(self.items), column=0, sticky="ew", pady=2)
        self.items[key] = item
        return item

    def select(self, key: str) -> None:
        """Highlight exactly one item."""
        for name, item in self.items.items():
            item.set_active(name == key)

    def _clicked(self, key: str) -> None:
        if self.on_select is not None:
            self.on_select(key)


class TabRow(theme.Frame):
    """The horizontal section row below the top bar; the active tab is underlined."""

    def __init__(
        self,
        master: Any = None,
        *,
        on_select: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, fg_color=theme.COLORS["bg"], **kwargs)
        self.on_select = on_select
        self.items: dict[str, dict[str, Any]] = {}

    def add(self, key: str, label: str) -> None:
        """Add one tab (a flat button plus its underline)."""
        holder = theme.Frame(self)
        holder.grid(row=0, column=len(self.items), padx=(0, 4))
        button = theme.Button(
            holder,
            text=label,
            kind="quiet",
            height=32,
            command=lambda name=key: self._clicked(name),
        )
        button.grid(row=0, column=0, sticky="ew")
        underline = theme.Frame(holder, height=2, fg_color=theme.COLORS["bg"], corner_radius=0)
        underline.grid(row=1, column=0, sticky="ew")
        self.items[key] = {"button": button, "underline": underline}

    def select(self, key: str) -> None:
        """Underline the active tab in the accent colour."""
        for name, parts in self.items.items():
            active = name == key
            parts["button"].configure(
                text_color=theme.COLORS["text"] if active else theme.COLORS["text_secondary"]
            )
            parts["underline"].configure(
                fg_color=theme.COLORS["accent"] if active else theme.COLORS["bg"]
            )

    def _clicked(self, key: str) -> None:
        if self.on_select is not None:
            self.on_select(key)



class ReviewBar(theme.Card):
    """The center question: "is the plan ready to run?" plus the answer."""

    def __init__(self, master: Any = None, *, question: str = "", **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self.columnconfigure(1, weight=1)
        self.dot = theme.StatusDot(self, tone="unknown")
        self.dot.grid(row=0, column=0, padx=(14, 10), pady=14, sticky="n")
        self.question = theme.Body(self, text=question)
        self.question.grid(row=0, column=1, sticky="nw", pady=(12, 0), padx=(0, 14))
        self.answer = theme.Label(
            self,
            text="",
            text_color=theme.COLORS["text_secondary"],
            wraplength=620,
            justify="left",
        )
        self.answer.grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=(2, 12))

    def set_answer(self, answer: str, *, tone: str = "unknown") -> None:
        """Show the answer and colour the dot with the tone behind it."""
        self.answer.configure(text=answer)
        self.dot.set_tone(tone)


class AdvisorCard(theme.Card):
    """One advisor card: a status dot, a title, a metric and a one line explanation."""

    def __init__(self, master: Any = None, *, title: str = "", **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self.columnconfigure(1, weight=1)
        self.dot = theme.StatusDot(self, tone="unknown")
        self.dot.grid(row=0, column=0, padx=(14, 8), pady=(12, 0), sticky="n")
        self.title = theme.Label(
            self,
            text=title,
            text_color=theme.COLORS["muted"],
            font=theme.FONTS["micro"],
        )
        self.title.grid(row=0, column=1, sticky="w", pady=(12, 0), padx=(0, 14))
        self.metric = theme.Metric(self, text="-")
        self.metric.grid(row=1, column=1, sticky="w", padx=(0, 14), pady=(2, 0))
        self.detail = theme.Label(
            self,
            text="",
            text_color=theme.COLORS["text_secondary"],
            wraplength=240,
            justify="left",
        )
        self.detail.grid(row=2, column=1, sticky="ew", padx=(0, 14), pady=(2, 12))

    def set_card(self, *, tone: str, metric: str, detail: str) -> None:
        """Fill the card (the tone drives its dot)."""
        self.dot.set_tone(tone)
        self.metric.configure(text=metric)
        self.detail.configure(text=detail)


class AdvisorRow(theme.Frame):
    """The three advisor cards of the mockup, side by side."""

    def __init__(
        self, master: Any = None, *, cards: tuple[tuple[str, str], ...] = (), **kwargs: Any
    ) -> None:
        super().__init__(master, **kwargs)
        self.cards: dict[str, AdvisorCard] = {}
        for column, (key, title) in enumerate(cards):
            self.columnconfigure(column, weight=1, uniform="advisor")
            card = AdvisorCard(self, title=title)
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))
            self.cards[key] = card

    def set_card(self, key: str, *, tone: str, metric: str, detail: str) -> None:
        """Update one card; an unknown key is ignored."""
        card = self.cards.get(key)
        if card is not None:
            card.set_card(tone=tone, metric=metric, detail=detail)



class ActionSection(theme.Frame):
    """A labelled group of buttons in the right action panel."""

    def __init__(self, master: Any = None, *, title: str = "", **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self.columnconfigure(0, weight=1)
        self.buttons: list[theme.Button] = []
        self._widgets: list[tuple[Any, bool]] = []
        self._row = 1
        self._busy = False  # the last value pushed to the buttons (a no-op is skipped)
        self.title_label = theme.Label(
            self,
            text=title.upper(),
            text_color=theme.COLORS["muted"],
            font=theme.FONTS["micro"],
        )
        self.title_label.grid(row=0, column=0, sticky="ew", padx=4, pady=(10, 4))

    def add_button(
        self,
        label: str,
        command: Callable[[], None],
        *,
        kind: str = "ghost",
        keep_enabled: bool = False,
    ) -> theme.Button:
        """Add one button; `keep_enabled` marks the read-only actions of the window."""
        button = theme.Button(self, text=label, kind=kind, command=command)
        self.buttons.append(button)
        return self._place(button, keep_enabled=keep_enabled)

    def add_widget(self, widget: Any, *, keep_enabled: bool = False) -> Any:
        """Add any other control of the section (a check box, for example)."""
        return self._place(widget, keep_enabled=keep_enabled)

    def set_busy(self, busy: bool) -> None:
        """While a batch runs only the read-only controls stay live.

        An unchanged value returns immediately: `configure()` on a CTkButton redraws
        its whole rounded rectangle, and the window's pump calls this every 120 ms.
        """
        busy = bool(busy)
        if self._busy == busy:
            return
        self._busy = busy
        for widget, keep in self._widgets:
            widget.configure(state="normal" if (not busy or keep) else "disabled")

    def _place(self, widget: Any, *, keep_enabled: bool) -> Any:
        widget.grid(row=self._row, column=0, sticky="ew", padx=4, pady=2)
        self._row += 1
        self._widgets.append((widget, bool(keep_enabled)))
        return widget


class ActionPanel(theme.Frame):
    """The right-hand action panel, grouped by labelled sections."""

    def __init__(
        self,
        master: Any = None,
        *,
        title: str = "",
        sections: tuple[tuple[str, str], ...] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(master, fg_color=theme.COLORS["panel"], **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        if title:
            theme.Label(
                self,
                text=title.upper(),
                text_color=theme.COLORS["text_secondary"],
                font=theme.FONTS["micro"],
            ).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 2))

        self.scroll = theme.ScrollableFrame(self, fg_color=theme.COLORS["panel"])
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.scroll.columnconfigure(0, weight=1)
        self.sections: dict[str, ActionSection] = {}
        self._busy = False  # the last value pushed to the sections (a no-op is skipped)
        for row, (key, label) in enumerate(sections):
            section = ActionSection(self.scroll, title=label)
            section.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 2))
            self.sections[key] = section

    def add(
        self,
        section: str,
        label: str,
        command: Callable[[], None],
        *,
        kind: str = "ghost",
        keep_enabled: bool = False,
    ) -> theme.Button | None:
        """Add a button to a section (an unknown section name is ignored)."""
        group = self.sections.get(section)
        if group is None:
            return None
        return group.add_button(label, command, kind=kind, keep_enabled=keep_enabled)

    def set_busy(self, busy: bool) -> None:
        """Lock the mutating actions of every section at once.

        Only a real change reaches the buttons: the window calls this from its pump
        every 120 ms, and every button configure is a full CustomTkinter redraw.
        """
        busy = bool(busy)
        if self._busy == busy:
            return
        self._busy = busy
        for section in self.sections.values():
            section.set_busy(busy)




class SectionStack(theme.Frame):
    """The content area: exactly one section widget is visible at a time.

    The sidebar and the tab row decide which one; the container only shows it. The
    `add / tabs / tab / select / bind("<<NotebookTabChanged>>")` calls of `ttk.Notebook`
    are kept, because that is how the window, the tests and the acceptance drivers have
    always switched a section - only the visuals changed.
    """

    def __init__(
        self,
        master: Any = None,
        *,
        on_change: Callable[[Any], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.on_change = on_change
        self._order: list[Any] = []
        self._texts: dict[str, str] = {}
        self._current: Any = None
        self._callbacks: list[Callable[[], None]] = []

    # ---------------------------------------------------------- notebook style API

    def add(self, widget: Any, text: str = "", **_kwargs: Any) -> Any:
        """Stack a section widget and give it a label."""
        widget.grid(row=0, column=0, sticky="nsew")
        widget.grid_remove()
        self._order.append(widget)
        self._texts[str(widget)] = text
        if self._current is None:
            self.select(widget)
        return widget

    def tabs(self) -> tuple[str, ...]:
        """The tab ids (the string form of every section widget)."""
        return tuple(str(widget) for widget in self._order)

    def tab(self, widget: Any, option: str = "text", **_kwargs: Any) -> str:
        """Only the label of a section is asked for (`option="text"`)."""
        return self._texts.get(str(widget), "")

    def select(self, widget: Any = None) -> Any:
        """Show one section (or report the current one when called without an argument)."""
        if widget is None:
            return self._texts.get(str(self._current), "")
        target = self._resolve(widget)
        if target is None:
            return None
        for candidate in self._order:
            if candidate is target:
                candidate.grid()
            else:
                candidate.grid_remove()
        self._current = target
        for callback in list(self._callbacks):
            callback()
        if self.on_change is not None:
            self.on_change(target)
        return target

    def get(self) -> str:
        """The label of the visible section."""
        return self._texts.get(str(self._current), "")

    def current(self) -> Any:
        """The visible section widget."""
        return self._current

    def section(self, text: str) -> Any:
        """The section widget that carries `text` (used to wire the sidebar)."""
        for widget in self._order:
            if self._texts.get(str(widget)) == text:
                return widget
        return None

    def bind(self, sequence: str = "", func: Callable[[], None] | None = None, add: Any = None) -> Any:  # noqa: A003
        """`<<NotebookTabChanged>>` is a callback list; anything else stays a Tk binding."""
        if sequence == "<<NotebookTabChanged>>" and func is not None:
            self._callbacks.append(func)
            return None
        return super().bind(sequence, func, add)

    def _resolve(self, widget: Any) -> Any:
        if widget in self._order:
            return widget
        for candidate in self._order:
            if str(candidate) == str(widget):
                return candidate
        if isinstance(widget, int) and 0 <= widget < len(self._order):
            return self._order[widget]
        return None


class TitledCard(theme.Card):
    """A card with a small heading; `body` is the frame the content is laid out in.

    It is the dark replacement of the old `ttk.LabelFrame`: the rows of the content are
    the same as before, only the surface (card colour, 1 px border, radius) changed.
    """

    def __init__(self, master: Any = None, *, title: str = "", **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        theme.Label(
            self,
            text=title.upper(),
            text_color=theme.COLORS["muted"],
            font=theme.FONTS["micro"],
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 2))
        self.body = theme.Frame(self, fg_color=theme.COLORS["card"])
        self.body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))


class StatusBar(theme.Frame):
    """The bottom line: what just happened, and what is running right now."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        super().__init__(master, fg_color=theme.COLORS["panel"], **kwargs)
        self.columnconfigure(0, weight=1)
        self.status = theme.Label(self, text="", anchor="w", text_color=theme.COLORS["text_secondary"])
        self.status.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=6)
        self.busy_status = theme.Label(
            self, text="", anchor="e", text_color=theme.COLORS["accent"]
        )
        self.busy_status.grid(row=0, column=1, sticky="e", padx=(8, 16), pady=6)
