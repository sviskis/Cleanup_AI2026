"""Background PDF rendering for the GUI: request queue, generations, one worker.

No Tk in this module: it owns the cache, a request queue and ONE worker thread, and
reports every finished page either through the shared `EventBus` (kind
`tasks.EVENT_PREVIEW`, drained by the Tk main thread) or through an `on_result`
callback (used by the tests). Widgets are only ever touched by the main thread.

Why a generation token: switching the document (or a RECONCILE) must never paint a
thumbnail of the previous PDF. `set_document()` bumps the generation; results of an
older generation are dropped instead of delivered, and pending requests of the old
generation are discarded before they are rendered at all.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from ..preview.cache import KIND_PREVIEW, KIND_THUMBNAIL, CacheKey, PreviewCache
from ..preview.renderer import (
    DEFAULT_PREVIEW_LONG_SIDE,
    DEFAULT_THUMBNAIL_WIDTH,
    PageGeometry,
    PreviewError,
    document_fingerprint,
    page_geometry,
    png_size,
    render_preview,
    render_thumbnail,
)

LOGGER_NAME = "pdf_ai_batch.gui.preview"
IDLE_POLL_SECONDS = 0.05


@dataclass(frozen=True)
class PreviewRequest:
    """One page to render: which document state, which page, which size."""

    generation: int
    fingerprint: tuple[str, float, int]
    page: int
    kind: str = KIND_THUMBNAIL
    width: int = 0
    long_side: int = 0
    zoom: float = 0.0
    want_geometry: bool = False
    priority: int = 0

    @property
    def pdf(self) -> str:
        return str(self.fingerprint[0])

    @property
    def document_name(self) -> str:
        return Path(self.fingerprint[0]).name

    def key(self) -> tuple:
        """Identity for de-duplication (same page, same size request, same state)."""
        return (
            self.generation,
            self.page,
            self.kind,
            int(self.width),
            int(self.long_side),
            f"{float(self.zoom):.4f}",
        )

    def cache_key(self) -> CacheKey:
        if self.kind == KIND_THUMBNAIL:
            return CacheKey.for_thumbnail(self.fingerprint, self.page, self.width)
        return CacheKey.for_preview(
            self.fingerprint, self.page, long_side=self.long_side, zoom=self.zoom
        )


@dataclass(frozen=True)
class PreviewResult:
    """One finished (or failed) render, already safe to hand to the GUI."""

    request: PreviewRequest
    ok: bool = False
    image: bytes | None = None
    width: int = 0
    height: int = 0
    zoom: float = 0.0
    geometry: PageGeometry | None = None
    error: str = ""
    from_cache: bool = False
    seconds: float = 0.0

    @property
    def page(self) -> int:
        return self.request.page

    @property
    def kind(self) -> str:
        return self.request.kind

    @property
    def generation(self) -> int:
        return self.request.generation

    @property
    def document_name(self) -> str:
        return self.request.document_name

    @property
    def long_side(self) -> int:
        return max(int(self.width), int(self.height))

    @property
    def nbytes(self) -> int:
        return len(self.image or b"")


class PreviewLoader:
    """Render thumbnails and previews in a worker thread, one page at a time."""

    def __init__(
        self,
        cache: PreviewCache,
        *,
        bus: object | None = None,
        on_result: Callable[[PreviewResult], None] | None = None,
        logger: logging.Logger | None = None,
        thumbnail_width: int = DEFAULT_THUMBNAIL_WIDTH,
        preview_long_side: int = DEFAULT_PREVIEW_LONG_SIDE,
    ) -> None:
        self.cache = cache
        self.bus = bus
        self.on_result = on_result
        self.log = logger or logging.getLogger(LOGGER_NAME)
        self.thumbnail_width = int(thumbnail_width)
        self.preview_long_side = int(preview_long_side)

        self._pending: queue.PriorityQueue = queue.PriorityQueue()
        self._counter = 0
        self._queued_keys: set[tuple] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._generation = 0
        self._fingerprint: tuple[str, float, int] | None = None
        self._stats = {
            "queued": 0,
            "rendered": 0,
            "cache_hits": 0,
            "errors": 0,
            "dropped": 0,
            "total_render_seconds": 0.0,
            "last_render_seconds": 0.0,
        }

    # ------------------------------------------------------------ document scope

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def pdf(self) -> str:
        return str(self._fingerprint[0]) if self._fingerprint else ""

    @property
    def fingerprint(self) -> tuple[str, float, int] | None:
        return self._fingerprint

    def set_document(self, pdf: str | Path | None) -> int:
        """Point the loader at a document (or at nothing); returns the new generation.

        Bumps the generation, forgets every pending request of the previous document
        and records the fingerprint (path + mtime + size) all cache keys use.
        """
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._drop_pending_locked()
            self._fingerprint = None
        if pdf is None:
            return generation
        try:
            fingerprint = document_fingerprint(pdf)
        except PreviewError as exc:
            self.log.warning("Preview: %s", exc)
            return generation
        with self._lock:
            if generation == self._generation:
                self._fingerprint = fingerprint
        return generation

    def invalidate_document(self) -> int:
        """Drop the cached renders of the current PDF (the file changed on disk)."""
        fingerprint = self._fingerprint
        if fingerprint is None:
            return 0
        removed = self.cache.invalidate_pdf(Path(fingerprint[0]).name, keep=fingerprint)
        if removed:
            self.log.info("Preview kešs: iztīrīju %s vecos failus", removed)
        return removed

    # ------------------------------------------------------------------ requests

    def request_thumbnail(self, page: int, *, priority: int = 0) -> PreviewRequest | None:
        return self._enqueue(
            page,
            kind=KIND_THUMBNAIL,
            width=self.thumbnail_width,
            priority=priority,
        )

    def request_thumbnails(self, pages: Sequence[int], *, priority: int = 1) -> int:
        """Queue several thumbnails (already rendered/queued ones are skipped)."""
        queued = 0
        for page in pages:
            if self.request_thumbnail(int(page), priority=priority) is not None:
                queued += 1
        return queued

    def request_preview(
        self,
        page: int,
        *,
        long_side: int | None = None,
        zoom: float | None = None,
        priority: int = -10,
    ) -> PreviewRequest | None:
        """The big preview of one page (highest priority by default)."""
        return self._enqueue(
            page,
            kind=KIND_PREVIEW,
            long_side=self.preview_long_side if long_side is None else int(long_side),
            zoom=0.0 if zoom is None else float(zoom),
            want_geometry=True,
            priority=priority,
        )

    def _enqueue(
        self,
        page: int,
        *,
        kind: str,
        width: int = 0,
        long_side: int = 0,
        zoom: float = 0.0,
        want_geometry: bool = False,
        priority: int = 0,
    ) -> PreviewRequest | None:
        if int(page) < 1:
            return None
        with self._lock:
            fingerprint = self._fingerprint
            if fingerprint is None:
                return None
            request = PreviewRequest(
                generation=self._generation,
                fingerprint=fingerprint,
                page=int(page),
                kind=kind,
                width=int(width),
                long_side=int(long_side),
                zoom=float(zoom),
                want_geometry=bool(want_geometry),
                priority=int(priority),
            )
            if request.key() in self._queued_keys:
                return None
            self._queued_keys.add(request.key())
            self._counter += 1
            self._stats["queued"] += 1
            self._pending.put((request.priority, self._counter, request))
        self._ensure_thread()
        return request

        return self.request.kind

    @property
    def generation(self) -> int:
        return self.request.generation

    @property
    def document_name(self) -> str:
        return self.request.document_name

    @property
    def nbytes(self) -> int:
        return len(self.image or b"")

    # -------------------------------------------------------------------- worker

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._stop.is_set():
                return
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="pdf_ai_batch:preview", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                _priority, _order, request = self._pending.get(timeout=IDLE_POLL_SECONDS)
            except queue.Empty:
                continue
            if request is None:
                continue
            with self._lock:
                self._queued_keys.discard(request.key())
                current = self._generation
            if request.generation != current:
                self._count("dropped")
                continue
            started = time.perf_counter()
            result = self._render(request)
            if result.request.generation != self._generation:
                # superseded while rendering: never deliver a foreign document's page
                self._count("dropped")
                continue
            self._count("rendered")
            if not result.ok:
                self._count("errors")
            seconds = round(time.perf_counter() - started, 4)
            self._stats["last_render_seconds"] = seconds
            self._stats["total_render_seconds"] = round(
                self._stats["total_render_seconds"] + seconds, 4
            )
            self._deliver(
                PreviewResult(
                    request=result.request,
                    ok=result.ok,
                    image=result.image,
                    width=result.width,
                    height=result.height,
                    zoom=result.zoom,
                    geometry=result.geometry,
                    error=result.error,
                    from_cache=result.from_cache,
                    seconds=seconds,
                )
            )

    def _render(self, request: PreviewRequest) -> PreviewResult:
        """Cache first, renderer second; every failure becomes a failed result."""
        key = request.cache_key()
        try:
            cached = self.cache.get(key)
        except Exception as exc:  # noqa: BLE001 - a cache problem must not stop rendering
            self.log.warning("Preview kešs: %s", exc)
            cached = None
        try:
            if cached:
                width, height = png_size(cached)
                self._stats["cache_hits"] += 1
                return PreviewResult(
                    request=request,
                    ok=True,
                    image=cached,
                    width=width,
                    height=height,
                    zoom=request.zoom,
                    geometry=self._geometry(request) if request.want_geometry else None,
                    from_cache=True,
                )
            if request.kind == KIND_THUMBNAIL:
                page = render_thumbnail(request.fingerprint[0], request.page, width=request.width)
            else:
                page = render_preview(
                    request.fingerprint[0],
                    request.page,
                    max_long_side=request.long_side or self.preview_long_side,
                    zoom=request.zoom or None,
                )
        except PreviewError as exc:
            return PreviewResult(request=request, ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - a broken page is a preview failure
            return PreviewResult(request=request, ok=False, error=f"{type(exc).__name__}: {exc}")

        self.cache.put(key, page.image)
        return PreviewResult(
            request=request,
            ok=True,
            image=page.image,
            width=page.width,
            height=page.height,
            zoom=page.zoom,
            geometry=page.geometry,
        )

    def _geometry(self, request: PreviewRequest) -> PageGeometry | None:
        try:
            return page_geometry(request.fingerprint[0], request.page)
        except PreviewError as exc:
            self.log.warning("Preview: %s", exc)
            return None

    def _deliver(self, result: PreviewResult) -> None:
        if self.on_result is not None:
            try:
                self.on_result(result)
                return
            except Exception as exc:  # noqa: BLE001 - a bad sink must not kill the worker
                self.log.error("Preview rezultātu apstrāde neizdevās: %s", exc)
                return
        if self.bus is not None and hasattr(self.bus, "emit"):
            from . import tasks

            self.bus.emit(tasks.EVENT_PREVIEW, result)


    # ------------------------------------------------------------------- upkeep

    def _count(self, name: str, amount: int = 1) -> None:
        self._stats[name] = self._stats.get(name, 0) + amount

    def _drop_pending_locked(self) -> int:
        """Drop every queued request (called with the lock held)."""
        dropped = 0
        while True:
            try:
                _priority, _order, request = self._pending.get_nowait()
            except queue.Empty:
                break
            if request is not None:
                self._queued_keys.discard(request.key())
                dropped += 1
        self._stats["dropped"] += dropped
        return dropped

    def cancel(self) -> int:
        """Forget every pending request (used when the selection changes a lot)."""
        with self._lock:
            return self._drop_pending_locked()

    def pending(self) -> int:
        with self._lock:
            return len(self._queued_keys)

    def stats(self) -> dict:
        with self._lock:
            data = dict(self._stats)
            data["pending"] = len(self._queued_keys)
            data["generation"] = self._generation
            data["pdf"] = str(self._fingerprint[0]) if self._fingerprint else ""
        return data

    def stop(self, *, timeout: float = 2.0) -> None:
        """Stop the worker (window closing); safe to call more than once."""
        self._stop.set()
        with self._lock:
            self._drop_pending_locked()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
            with self._lock:
                self._thread = None

