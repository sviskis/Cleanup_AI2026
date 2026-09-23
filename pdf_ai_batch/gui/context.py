"""What a tab may ask the window for (keeps the tabs free of window internals).

A tab only ever talks to this context: the controller for logic, and the window for
presentation (status bar, log view, refresh, running a task in a worker thread). The
PDF preview loader is handed over here as well - it is the only background renderer
the GUI owns.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
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
    preview_loader: Any = None  # gui/preview_loader.PreviewLoader (background renders)
    open_path: Callable[[Any], None] | None = None  # test seam for OPEN OUTPUT

    def report(self, message: str, *, error: bool = False) -> None:
        """Status bar + log in one call (used by every tab)."""
        self.set_status(message)
        self.append_log(("KĻŪDA: " if error else "") + message)

    def open_file(self, path: str | Path) -> None:
        """Open a finished output with the operating system default (never edit it).

        Windows uses `os.startfile`; anything else (and the tests) can inject
        `open_path`. Nothing here reads or writes the AI.
        """
        target = Path(str(path))
        if self.open_path is not None:
            self.open_path(target)
            return
        if not hasattr(os, "startfile"):
            raise RuntimeError("Šajā sistēmā failu atvēršana nav atbalstīta")
        os.startfile(str(target))  # noqa: S606 - intentional, the operator asked for it