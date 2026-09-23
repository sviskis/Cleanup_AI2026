"""Natural sorting, PDF discovery and page counting (PyMuPDF and pypdf)."""

from __future__ import annotations

import pytest

from pdf_ai_batch.core import pdf_info


def test_natural_sort_orders_numbers_numerically():
    names = ["10.ai", "2.ai", "1.ai", "3.ai"]
    ordered = [p.name for p in pdf_info.sorted_naturally([__import__("pathlib").Path(n) for n in names])]
    assert ordered == ["1.ai", "2.ai", "3.ai", "10.ai"]


def test_natural_sort_handles_padded_and_mixed_names():
    from pathlib import Path

    names = ["page10.pdf", "page2.pdf", "page02.pdf", "page1.pdf"]
    ordered = [p.name for p in pdf_info.sorted_naturally([Path(n) for n in names])]
    assert ordered == ["page1.pdf", "page02.pdf", "page2.pdf", "page10.pdf"]


def test_natural_key_is_case_insensitive():
    from pathlib import Path

    assert pdf_info.natural_key("Manual.PDF") == pdf_info.natural_key("manual.pdf")


def test_discover_pdfs_skips_bookkeeping_folders(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "b.PDF").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "AI_OUT").mkdir()
    (tmp_path / "AI_OUT" / "ignore.pdf").write_bytes(b"%PDF-1.4\n")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "c.pdf").write_bytes(b"%PDF-1.4\n")

    flat = pdf_info.discover_pdfs(tmp_path, recursive=False)
    assert [p.name for p in flat] == ["a.pdf", "b.PDF"]

    recursive = pdf_info.discover_pdfs(tmp_path, recursive=True)
    assert [p.name for p in recursive] == ["a.pdf", "b.PDF", "c.pdf"]


def test_count_pages_with_pymupdf(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "three.pdf", pages=3)
    count, method = pdf_info.count_pages(pdf)
    assert count == 3
    assert method == "PyMuPDF"


@pytest.mark.parametrize("pages", [1, 14, 42])
def test_count_pages_matches_the_generated_page_count(make_pdf, tmp_path, pages):
    pdf = make_pdf(tmp_path / f"doc_{pages}.pdf", pages=pages)
    count, _method = pdf_info.count_pages(pdf)
    assert count == pages


def test_pypdf_fallback_is_used_when_pymupdf_fails(make_pdf, tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "fallback.pdf", pages=5)

    def broken_pymupdf():
        raise ImportError("PyMuPDF disabled for this test")

    monkeypatch.setattr(pdf_info, "load_pymupdf", broken_pymupdf)
    count, method = pdf_info.count_pages(pdf)
    assert count == 5
    assert method == "pypdf"


def test_missing_pdf_raises():
    with pytest.raises(pdf_info.PdfPageCountError):
        pdf_info.count_pages("C:/definitely/not/here.pdf")


def test_pdf_info_reports_file_details(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "info.pdf", pages=2)
    info = pdf_info.pdf_info(pdf)
    assert info.page_count == 2
    assert info.name == "info.pdf"
    assert info.size_bytes > 0
    assert info.first_page_size is not None
    width, height = info.first_page_size
    assert width == pytest.approx(595, abs=1)
    assert height == pytest.approx(842, abs=1)
