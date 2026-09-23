"""Worker thread + event bridge between the core and the Tk main thread.

A batch can take minutes (Illustrator processes one page at a time) and Tk widgets
may only be touched from the main thread, so:

    Tk main thread                        worker thread
    ---------------                       -------------
    TaskRunner.start(label, task)  -----> task(progress) runs BatchQueue+adapter
    root.after(120, pump)          <----- events: log / progress / done / error

Nothing in this module imports Tk, so the whole bridge is unit testable without a
display. The GUI never polls the core directly; it only reacts to events.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable

EVENT_LOG = "log"
EVENT_PROGRESS = "progress"
EVENT_DONE = "done"
EVENT_ERROR = "error"

TaskFn = Callable[[Callable[[Any], None]], Any]


@dataclass
class Event:
    """One UI event. `payload` is a log line, a RunOutcome, a summary or an Exception."""

    kind: str
    payload: Any = None


class EventBus:
    """Thread safe event queue, drained only by the Tk main thread."""

    def __init__(self, maxsize: int = 5000) -> None:
        self._queue: queue.Queue[Event] = queue.Queue(maxsize=maxsize)
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def emit(self, kind: str, payload: Any = None) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(Event(kind, payload))
        except queue.Full:  # a slow UI must never block a worker
            pass

    def drain(self, limit: int = 200) -> list[Event]:
        events: list[Event] = []
        while len(events) < limit:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def close(self) -> None:
        """Stop accepting events (window closing)."""
        self._closed = True


class QueueLogHandler(logging.Handler):
    """Forwards log records to the GUI log view through the event bus.

    The canonical logging stays in JOB/LOG/app.log and the batch log; this handler
    is only a VIEW (see docs/GUI.md).
    """

    def __init__(self, bus: EventBus, level: int = logging.INFO) -> None:
        super().__init__(level)
        self.bus = bus

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102 - logging API
        try:
            self.bus.emit(EVENT_LOG, self.format(record))
        except Exception:  # noqa: BLE001 - logging must never raise
            pass


class TaskRunner:
    """Runs one long callable in a worker thread and reports through an EventBus."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._label = ""

    # ------------------------------------------------------------------ status

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def label(self) -> str:
        with self._lock:
            return self._label

    # ------------------------------------------------------------------- start

    def start(self, label: str, task: TaskFn, *, daemon: bool = True) -> bool:
        """Start `task(progress)` in a worker thread; False when one is running.

        `task` receives a `progress` callback that pushes a progress event - this is
        the callback the queue calls after every item (`BatchQueue` progress=...).
        """
        if self.busy:
            return False

        def emit_progress(outcome: Any) -> None:
            self.bus.emit(EVENT_PROGRESS, outcome)

        def run() -> None:
            try:
                result = task(emit_progress)
            except Exception as exc:  # noqa: BLE001 - the thread must never die silently
                self.bus.emit(EVENT_ERROR, exc)
            else:
                self.bus.emit(EVENT_DONE, result)
            finally:
                with self._lock:
                    self._thread = None
                    self._label = ""

        with self._lock:
            self._label = label
            self._thread = threading.Thread(target=run, name=f"pdf_ai_batch:{label}", daemon=daemon)
            self._thread.start()
        return True

    def join(self, timeout: float | None = None) -> None:
        """Wait for the worker (used by tests and by the window closing)."""
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
