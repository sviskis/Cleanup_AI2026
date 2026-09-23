"""Preview cache: keys, hits, invalidation, bounds, safe-to-delete folder."""

from __future__ import annotations

import os
import time

import pytest

from pdf_ai_batch.preview import CacheKey, PreviewCache
from pdf_ai_batch.preview.cache import (
    CACHE_DIR_NAME,
    CACHE_GITIGNORE,
    KIND_PREVIEW,
    KIND_THUMBNAIL,
    fingerprint_digest,
    safe_name,
)


def _fingerprint(path, *, mtime: float = 1000.0, size: int = 12345) -> tuple[str, float, int]:
    return (str(path).replace("\\", "/"), mtime, size)


def test_cache_lives_in_the_job_dot_cache_folder(tmp_path):
    cache = PreviewCache(tmp_path / "JOB_TEST")

    assert cache.directory == tmp_path / "JOB_TEST" / ".cache" / CACHE_DIR_NAME
    assert cache.directory.exists() is False  # created on demand, never eagerly


def test_put_get_roundtrip_and_directory_marker(tmp_path):
    cache = PreviewCache(tmp_path / "JOB")
    key = CacheKey.for_thumbnail(_fingerprint("C:/job/PDF/manual.pdf"), 3, 160)

    written = cache.put(key, b"\x89PNG-fake-bytes")

    assert written is not None and written.is_file()
    assert written.parent == cache.directory
    assert cache.get(key) == b"\x89PNG-fake-bytes"
    assert (cache.directory / ".gitignore").read_text(encoding="ascii") == CACHE_GITIGNORE
    assert cache.stats()["files"] == 1


def test_same_pdf_page_and_fingerprint_hits_the_same_file(tmp_path):
    cache = PreviewCache(tmp_path / "JOB")
    fingerprint = _fingerprint("C:/job/PDF/manual.pdf")
    first = CacheKey.for_thumbnail(fingerprint, 7, 160)
    second = CacheKey.for_thumbnail(fingerprint, 7, 160)

    assert first.file_name() == second.file_name()
    cache.put(first, b"data")

    assert cache.get(second) == b"data"


def test_a_different_render_size_is_a_different_entry(tmp_path):
    fingerprint = _fingerprint("C:/job/PDF/manual.pdf")
    thumb = CacheKey.for_thumbnail(fingerprint, 7, 160)
    big = CacheKey.for_preview(fingerprint, 7, long_side=1000)
    zoomed = CacheKey.for_preview(fingerprint, 7, zoom=1.0)

    names = {thumb.file_name(), big.file_name(), zoomed.file_name()}

    assert len(names) == 3
    assert big.kind == KIND_PREVIEW and thumb.kind == KIND_THUMBNAIL


def test_two_pdfs_never_collide(tmp_path):
    cache = PreviewCache(tmp_path / "JOB")
    one = CacheKey.for_thumbnail(_fingerprint("C:/job/PDF/manualis.pdf"), 1, 160)
    two = CacheKey.for_thumbnail(_fingerprint("C:/job/PDF/appendix.pdf"), 1, 160)

    cache.put(one, b"manualis")
    cache.put(two, b"appendix")

    assert cache.get(one) == b"manualis"
    assert cache.get(two) == b"appendix"
    assert cache.stats()["files"] == 2


def test_modified_pdf_produces_a_new_key_and_invalidation_removes_the_old_one(tmp_path):
    cache = PreviewCache(tmp_path / "JOB")
    pdf = tmp_path / "manual.pdf"
    old = _fingerprint(pdf, mtime=1.0, size=100)
    new = _fingerprint(pdf, mtime=2.0, size=200)
    old_key = CacheKey.for_thumbnail(old, 1, 160)
    new_key = CacheKey.for_thumbnail(new, 1, 160)
    cache.put(old_key, b"old")
    cache.put(new_key, b"new")

    assert old_key.file_name() != new_key.file_name()  # mtime + size are in the name

    removed = cache.invalidate_pdf(pdf.name, keep=new)

    assert removed == 1
    assert cache.get(old_key) is None
    assert cache.get(new_key) == b"new"


def test_invalidate_pdf_leaves_other_documents_alone(tmp_path):
    cache = PreviewCache(tmp_path / "JOB")
    pdf = tmp_path / "manual.pdf"
    keep_key = CacheKey.for_thumbnail(_fingerprint(pdf, mtime=5.0, size=1), 1, 160)
    other = CacheKey.for_thumbnail(_fingerprint(tmp_path / "other.pdf"), 1, 160)
    cache.put(keep_key, b"a")
    cache.put(other, b"b")

    removed = cache.invalidate_pdf(pdf.name)  # no keep -> drop everything of this PDF

    assert removed == 1
    assert cache.get(keep_key) is None
    assert cache.get(other) == b"b"


def test_clear_deletes_everything_and_is_safe_when_empty(tmp_path):
    cache = PreviewCache(tmp_path / "JOB")
    for page in range(1, 4):
        cache.put(CacheKey.for_thumbnail(_fingerprint("C:/job/PDF/x.pdf"), page, 160), b"d")

    assert cache.clear() == 3
    assert cache.stats()["files"] == 0
    assert cache.clear() == 0


def test_prune_keeps_the_cache_inside_its_bounds(tmp_path):
    cache = PreviewCache(tmp_path / "JOB", max_files=3, max_bytes=10_000)
    keys = []
    for page in range(1, 7):
        key = CacheKey.for_thumbnail(_fingerprint("C:/job/PDF/x.pdf"), page, 160)
        cache.put(key, b"x" * 10)
        keys.append(key)
        time.sleep(0.01)  # distinct mtimes: the LRU order is observable

    assert cache.stats()["files"] == 3
    assert cache.get(keys[-1]) == b"x" * 10  # newest survives
    assert cache.get(keys[0]) is None  # oldest was pruned


def test_prune_respects_the_byte_budget(tmp_path):
    cache = PreviewCache(tmp_path / "JOB", max_files=0, max_bytes=100)
    for page in range(1, 5):
        cache.put(CacheKey.for_thumbnail(_fingerprint("C:/job/PDF/x.pdf"), page, 160), b"y" * 40)
        time.sleep(0.01)

    assert cache.stats()["bytes"] <= 100


def test_disabled_cache_neither_reads_nor_writes(tmp_path):
    cache = PreviewCache(tmp_path / "JOB", enabled=False)
    key = CacheKey.for_thumbnail(_fingerprint("C:/job/PDF/x.pdf"), 1, 160)

    assert cache.put(key, b"data") is None
    assert cache.get(key) is None
    assert cache.directory.exists() is False


def test_empty_payload_counts_as_a_miss(tmp_path):
    cache = PreviewCache(tmp_path / "JOB")
    key = CacheKey.for_thumbnail(_fingerprint("C:/job/PDF/x.pdf"), 1, 160)
    path = cache.put(key, b"data")
    assert path is not None
    path.write_bytes(b"")

    assert cache.get(key) is None


def test_latvian_names_are_sanitized_in_the_file_name(tmp_path):
    key = CacheKey.for_thumbnail(_fingerprint("C:/job/PDF/Māja āža (1).pdf"), 1, 160)

    name = key.file_name()

    assert name.endswith(".png")
    assert name.isascii()
    assert "M_ja_" in name
    assert key.document_name == "Māja āža (1).pdf"
    assert safe_name("") == "file"


def test_generated_file_names_stay_stable_for_a_given_fingerprint(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"x")
    stat = pdf.stat()
    fingerprint = (str(pdf).replace("\\", "/"), stat.st_mtime, stat.st_size)

    assert fingerprint_digest(fingerprint) == fingerprint_digest(fingerprint)
    assert len(fingerprint_digest(fingerprint)) == 12
    assert os.path.exists(pdf)


def test_cache_key_rejects_page_zero():
    with pytest.raises(ValueError):
        CacheKey.for_thumbnail(_fingerprint("C:/job/PDF/x.pdf"), 0, 160)

