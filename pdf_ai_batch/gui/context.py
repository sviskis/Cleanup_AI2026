"""What a tab may ask the window for (keeps the tabs free of window internals).

A tab only ever talks to this context: the controller for logic, and the window for
presentation (status bar, log view, refresh, running a task in a worker thread).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .controller import AppController


@dataclass
class GuiContext:
    controller: AppController
    set_status: Callable[[str], None]
    append_log: Callable[[str], None]
    refresh: Callable[[], None]
    run_task: Callable[[str, Callable[[Any], Any]], bool]
    busy: Callable[[], bool]
    window: Any = None  # the Tk root, used as the parent of dialogs

    def report(self, message: str, *, error: bool = False) -> None:
        """Status bar + log in one call (used by every tab)."""
        self.set_status(message)
        self.append_log(("KĻŪDA: " if error else "") + message)