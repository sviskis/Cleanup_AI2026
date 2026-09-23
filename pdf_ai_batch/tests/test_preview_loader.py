"""Preview loader (background rendering): queue, generations, cache, performance.

No Tk and no Illustrator: the loader is pure Python plus the PyMuPDF renderer, so
the whole "thumbnails populate progressively" behaviour is testable headless.
"""

from __future__ import annotations

import time

import pytest

from pdf_ai_batch.gui.preview_loader import (
    KIND_PREVIEW,
    KIND_THUMBNAIL,
    PreviewLoader,
    PreviewRequest,
)
from pdf_ai_batch.preview import PreviewCache, PreviewError


def _wait_for(loader: PreviewLoader, count: int, timeout: float = 20.0) -> list:
    """Wait until `count` results arrived (results are collected by the sink)."""
    deadline = time.time() + timeout
    while time.time() < deadline and len(loader.collected) < count:
        time.sleep(0.02)
    return loader.collected


@pytest.fixture()
def loader(tmp_path):
    """A loader with a collecting sink (no Tk, no event bus)."""
    made: list[PreviewLoader] = []

    def _make(**kwargs) -> PreviewLoader:
        cache_kwargs = kwargs.pop("cache_kwargs", {})
        instance = PreviewLoader(
            PreviewCache(tmp_path / "JOB", **cache_kwargs), on_result=None, **kwargs
        )
        instance.collected = []  # type: ignore[attr-defined]
        instance.on_result = instance.collected.append
        made.append(instance)
        return instance

    yield _make
    for instance in made:
        instance.stop(timeout=5)


def test_request_without_a_document_is_ignored(loader):
    instance = loader()

    assert instance.request_thumbnail(1) is None
    assert instance.request_preview(1) is None
    assert instance.pending() == 0
    assert instance.pdf == ""


def test_thumbnail_and_preview_are_rendered_and_cached(loader, make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=2)
    instance = loader()
    instance.set_document(pdf)
    instance.request_thumbnail(1)
    instance.request_preview(2)

    results = _wait_for(instance, 2)

    by_kind = {result.kind: result for result in results}
    assert by_kind[KIND_THUMBNAIL].ok and by_kind[KIND_THUMBNAIL].width == 160
    assert by_kind[KIND_PREVIEW].ok and by_kind[KIND_PREVIEW].long_side == 1000
    assert by_kind[KIND_PREVIEW].geometry is not None  # preview carries the page size
    assert by_kind[KIND_THUMBNAIL].geometry is not None  # rendered, not cached
    assert instance.stats()["cache_hits"] == 0
    assert instance.stats()["errors"] == 0
    assert instance.cache.stats()["files"] == 2


def test_second_request_comes_from_the_cache(loader, make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=1)
    instance = loader()
    instance.set_document(pdf)
    instance.request_thumbnail(1)
    _wait_for(instance, 1)
    instance.request_thumbnail(1)
    results = _wait_for(instance, 2)

    assert results[-1].from_cache is True
    assert instance.stats()["cache_hits"] == 1


def test_duplicate_requests_are_queued_only_once(loader, make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=3)
    instance = loader()
    instance.set_document(pdf)

    assert instance.request_thumbnail(2) is not None
    assert instance.request_thumbnail(2) is None  # same page, same size
    assert instance.request_thumbnails([2, 3, 3]) == 1  # page 2 queued, 3 new
    _wait_for(instance, 2)

    assert instance.stats()["queued"] == 2


def test_preview_result_is_delivered_before_queued_thumbnails(loader, make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=8)
    instance = loader()
    instance.set_document(pdf)
    instance.request_thumbnails([1, 2, 3, 4, 5, 6, 7, 8])
    instance.request_preview(5)

    results = _wait_for(instance, 2, timeout=10)

    kinds = [result.kind for result in results[:2]]
    assert KIND_PREVIEW in kinds  # the preview jumped ahead of 7 queued thumbnails
    preview = next(result for result in results if result.kind == KIND_PREVIEW)
    assert preview.page == 5 and preview.long_side == 1000


def test_switching_the_document_drops_pending_and_never_delivers_foreign_pages(
    loader, make_pdf, tmp_path
):
    first = make_pdf(tmp_path / "alpha.pdf", pages=40)
    second = make_pdf(tmp_path / "beta.pdf", pages=40)
    instance = loader()
    instance.set_document(first)
    instance.request_thumbnails(list(range(1, 41)))

    generation = instance.set_document(second)
    instance.request_thumbnails(list(range(1, 6)))

    results = _wait_for(instance, 5, timeout=20)

    assert all(result.generation == generation for result in results)
    assert all(result.document_name == "beta.pdf" for result in results)
    assert instance.stats()["dropped"] > 0  # the 40 old requests were discarded


def test_corrupt_page_is_reported_and_does_not_stop_the_others(loader, make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=3)
    instance = loader()
    instance.set_document(pdf)
    instance.request_thumbnail(99)  # out of range
    instance.request_thumbnail(1)

    results = _wait_for(instance, 2)

    failed = [result for result in results if not result.ok]
    good = [result for result in results if result.ok]
    assert failed and "1..3" in failed[0].error
    assert good and good[0].page == 1  # the good page still rendered
    assert instance.stats()["errors"] == 1


def test_render_failure_does_not_touch_the_queue_state(loader, make_pdf, tmp_path, monkeypatch):
    """A render problem is a PREVIEW problem: state.json must stay untouched."""
    from pdf_ai_batch.core import state as core_state
    from pdf_ai_batch.core.project import JobProject

    project = JobProject.open(tmp_path / "JOB_STATE")
    pdf = make_pdf(project.pdf_dir / "manual.pdf", pages=2)
    document = core_state.load_state(project.state_path)
    document.items.append(
        core_state.new_item(
            job_id="manual_p001",
            page=1,
            pdf=str(pdf),
            template="",
            output=str(project.output_dir / "manual__001.ai"),
        )
    )
    core_state.save_state(project.state_path, document)
    before = project.state_path.read_bytes()

    def boom(*_args, **_kwargs):
        raise PreviewError("simulēta renderēšanas kļūda")

    monkeypatch.setattr("pdf_ai_batch.gui.preview_loader.render_thumbnail", boom)
    instance = loader()
    instance.set_document(pdf)
    instance.request_thumbnail(1)
    results = _wait_for(instance, 1)

    assert results[0].ok is False and "simulēta" in results[0].error
    assert project.state_path.read_bytes() == before


def test_invalidate_document_forgets_the_old_renders(loader, make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=1)
    instance = loader()
    instance.set_document(pdf)
    instance.request_thumbnail(1)
    _wait_for(instance, 1)
    assert instance.cache.stats()["files"] == 1

    time.sleep(0.01)
    pdf.write_bytes(pdf.read_bytes())  # same bytes, new mtime
    instance.set_document(pdf)

    removed = instance.invalidate_document()

    assert removed == 1
    assert instance.cache.stats()["files"] == 0


def test_results_can_travel_through_the_event_bus(make_pdf, tmp_path):
    from pdf_ai_batch.gui import tasks

    bus = tasks.EventBus()
    instance = PreviewLoader(PreviewCache(tmp_path / "JOB"), bus=bus)
    try:
        instance.set_document(make_pdf(tmp_path / "manual.pdf", pages=1))
        instance.request_thumbnail(1)
        deadline = time.time() + 20
        event = None
        while time.time() < deadline and event is None:
            for candidate in bus.drain():
                if candidate.kind == tasks.EVENT_PREVIEW:
                    event = candidate
                    break
            time.sleep(0.02)
        assert event is not None
        assert event.payload.page == 1 and event.payload.ok
    finally:
        instance.stop(timeout=5)


def test_stop_ends_the_worker_and_is_idempotent(make_pdf, tmp_path):
    instance = PreviewLoader(PreviewCache(tmp_path / "JOB"))
    instance.set_document(make_pdf(tmp_path / "manual.pdf", pages=1))
    instance.request_thumbnail(1)
    time.sleep(0.1)

    instance.stop(timeout=5)
    instance.stop(timeout=5)

    assert instance.stats()["pending"] == 0


def test_request_dataclass_carries_the_cache_identity(tmp_path):
    fingerprint = ("C:/job/PDF/manual.pdf", 10.0, 20)
    request = PreviewRequest(generation=2, fingerprint=fingerprint, page=4, width=160)

    key = request.cache_key()

    assert key.page == 4 and key.width == 160 and key.kind == KIND_THUMBNAIL
    assert request.document_name == "manual.pdf"
    other = PreviewRequest(generation=3, fingerprint=fingerprint, page=4, width=160)
    assert request.key() != other.key()  # a new generation is a different request



# --------------------------------------------------------------------- performance


def test_hundred_page_pdf_opens_fast_and_renders_progressively(loader, make_pdf, tmp_path):
    """Milestone 5 performance requirement, without a GUI.

    120 pages: opening the document and asking for every thumbnail must return at
    once (no synchronous rendering), the results must arrive in steps and a document
    switch must discard/ignore everything of the previous PDF.
    """
    pdf = make_pdf(tmp_path / "big.pdf", pages=120)
    instance = loader()

    started = time.perf_counter()
    instance.set_document(pdf)
    queued = instance.request_thumbnails(list(range(1, 121)))
    open_seconds = time.perf_counter() - started

    assert queued == 120
    assert open_seconds < 1.0  # the GUI thread is never blocked by rendering
    assert instance.stats()["rendered"] == 0  # nothing rendered synchronously

    _wait_for(instance, 3, timeout=20)
    early = instance.stats()["rendered"]
    assert 0 < early < 120  # progressive, never "all 120 at once"

    _wait_for(instance, 12, timeout=45)
    assert instance.stats()["rendered"] < 120

    # switching documents: the remaining 100+ renders of big.pdf are simply dropped
    other = make_pdf(tmp_path / "other.pdf", pages=5)
    instance.set_document(other)
    instance.request_thumbnails([1, 2])
    _wait_for(instance, len(instance.collected) + 2, timeout=20)
    time.sleep(0.4)

    results = instance.collected
    first_new = next(
        index for index, result in enumerate(results) if result.document_name == "other.pdf"
    )
    assert all(result.document_name == "other.pdf" for result in results[first_new:])
    assert instance.stats()["dropped"] > 0

    thumbs = [r for r in results if r.kind == KIND_THUMBNAIL and r.ok]
    assert max(r.nbytes for r in thumbs) < 200_000  # one thumbnail stays small
    assert instance.cache.stats()["bytes"] < 20 * 1024 * 1024

