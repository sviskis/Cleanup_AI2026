"""Preview renderer: PyMuPDF rendering, geometry, aspect ratio, safe failures.

Everything here runs WITHOUT Illustrator (that is the whole point of the preview
package: Python renders, the GUI only displays).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_ai_batch.preview import (
    DEFAULT_PREVIEW_LONG_SIDE,
    DEFAULT_THUMBNAIL_WIDTH,
    MAX_ZOOM,
    PreviewError,
    document_fingerprint,
    page_geometry,
    png_size,
    render_page,
    render_preview,
    render_thumbnail,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _landscape(path: Path, pages: int = 2) -> Path:
    mupdf = pytest.importorskip("pymupdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = mupdf.open()
    for index in range(pages):
        page = document.new_page(width=842, height=595)  # A4 landscape
        page.insert_text((72, 72), f"landscape {index + 1}")
    document.save(str(path))
    document.close()
    return path


def test_thumbnail_is_a_png_of_the_requested_width(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=3)

    page = render_thumbnail(pdf, 1)

    assert page.image[:8] == PNG_MAGIC
    assert page.width == DEFAULT_THUMBNAIL_WIDTH
    assert page.nbytes > 500
    assert png_size(page.image) == (page.width, page.height)


def test_thumbnail_preserves_the_aspect_ratio(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=1)  # 595 x 842 pt portrait

    page = render_thumbnail(pdf, 1, width=160)

    ratio = page.width / page.height
    assert ratio == pytest.approx(595 / 842, rel=0.02)
    assert page.height > page.width


def test_landscape_page_keeps_its_own_aspect_ratio(tmp_path):
    pdf = _landscape(tmp_path / "wide.pdf", pages=1)

    page = render_thumbnail(pdf, 1, width=200)

    assert page.width == 200
    assert page.width > page.height
    assert page.width / page.height == pytest.approx(842 / 595, rel=0.02)


def test_preview_fits_the_longest_side(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=2)

    page = render_preview(pdf, 2, max_long_side=400)

    assert page.long_side == 400
    assert page.width < page.height
    assert page.geometry.page == 2
    assert page.geometry.page_count == 2


def test_default_preview_size_is_within_the_documented_range(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=1)

    page = render_preview(pdf, 1)

    assert DEFAULT_PREVIEW_LONG_SIDE == 1000
    assert page.long_side == DEFAULT_PREVIEW_LONG_SIDE


def test_page_geometry_reports_points_and_millimetres(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=3)

    geometry = page_geometry(pdf, 1)

    assert geometry.width_pt == pytest.approx(595, abs=1)
    assert geometry.height_pt == pytest.approx(842, abs=1)
    assert geometry.size_label == "210 x 297 mm"
    assert geometry.rotation == 0
    assert geometry.page_count == 3
    assert geometry.width_mm == pytest.approx(210, abs=1)


def test_zoom_is_clamped_and_aspect_kept(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=1)

    huge = render_page(pdf, 1, zoom=50)
    assert huge.zoom == MAX_ZOOM
    assert huge.width / huge.height == pytest.approx(595 / 842, rel=0.01)

    tiny = render_page(pdf, 1, zoom=0.0001)
    assert tiny.zoom > 0
    assert tiny.width >= 1 and tiny.height >= 1


def test_height_only_constraint_is_honoured(tmp_path):
    pdf = _landscape(tmp_path / "wide.pdf", pages=1)

    page = render_page(pdf, 1, height=150)

    assert page.height == 150


def test_page_out_of_range_is_a_preview_error(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "manual.pdf", pages=2)

    with pytest.raises(PreviewError):
        render_thumbnail(pdf, 3)
    with pytest.raises(PreviewError):
        page_geometry(pdf, 0)


def test_missing_file_is_a_preview_error(tmp_path):
    with pytest.raises(PreviewError):
        render_thumbnail(tmp_path / "nope.pdf", 1)
    with pytest.raises(PreviewError):
        document_fingerprint(tmp_path / "nope.pdf")


def test_corrupt_pdf_is_a_preview_error(tmp_path):
    """A text file named .pdf must not crash anything: it is a preview failure."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is definitely not a pdf\n")

    with pytest.raises(PreviewError):
        render_thumbnail(broken, 1)


def test_empty_file_is_a_preview_error(tmp_path):
    """A 0 byte "PDF" (interrupted download) is a preview failure, never a crash."""
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")

    with pytest.raises(PreviewError):
        page_geometry(empty, 1)


def test_namings_with_latvian_letters_and_spaces_work(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "Māja āža 2026 (1).pdf", pages=1)

    page = render_thumbnail(pdf, 1)
    fingerprint = document_fingerprint(pdf)

    assert page.width == DEFAULT_THUMBNAIL_WIDTH
    assert fingerprint[0].endswith("M\u0101ja \u0101\u017ea 2026 (1).pdf")
    assert fingerprint[2] == pdf.stat().st_size


def test_fingerprint_changes_when_the_file_changes(make_pdf, tmp_path):
    import os
    import time

    pdf = make_pdf(tmp_path / "manual.pdf", pages=2)
    before = document_fingerprint(pdf)
    time.sleep(0.01)
    pdf.write_bytes(pdf.read_bytes() + b"% trailer\n")
    os.utime(pdf, None)

    after = document_fingerprint(pdf)

    assert before[0] == after[0]  # same file
    assert (before[1], before[2]) != (after[1], after[2])


def test_png_size_returns_zero_for_foreign_bytes():
    assert png_size(b"not a png at all") == (0, 0)
    assert png_size(b"") == (0, 0)
