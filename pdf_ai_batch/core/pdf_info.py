"""PDF discovery, natural sorting and page counting.

Page counting is PYTHON AUTHORITATIVE:

    1. PyMuPDF (fitz)   - primary, exact and fast
    2. pypdf            - fallback when PyMuPDF is missing or fails

Illustrator is never asked how many pages a PDF has. The legacy Illustrator probe
stays in the frozen baseline only (see docs/CODE_ANALYSIS.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_EXCLUDED_DIRS = ("template", "ai_out", "log", "error", "errors", "archive", "config")

_NATURAL_SPLIT = re.compile(r"(\d+)")


class PdfError(RuntimeError):
    """Raised when a PDF cannot be read at all."""


class PdfPageCountError(PdfError):
    """Raised when neither PyMuPDF nor pypdf could determine the page count."""


def natural_key(value: str | Path) -> tuple:
    """Sort key that orders "2.ai" before "10.ai" (case insensitive).

    Rules (deterministic, documented so templates and PDFs always line up):
      * a run of digits sorts before a run of letters, so 001_cover.ai comes
        before MASTER_AI_TEMPLATE.ai
      * digit runs compare numerically first
      * for equal numbers the raw text decides, so "02" comes before "2"
    """
    text = Path(value).name if not isinstance(value, str) else value
    parts = _NATURAL_SPLIT.split(text.lower())
    key: list[object] = []
    for part in parts:
        if part.isdigit():
            key.append((0, int(part), part))
        elif part:
            key.append((1, part))
    return tuple(key)


def sorted_naturally(paths: Iterable[Path]) -> list[Path]:
    """Return the paths sorted naturally by file name."""
    return sorted(paths, key=lambda p: (natural_key(p.name), p.name.lower()))


def discover_pdfs(
    folder: str | Path,
    recursive: bool = True,
    exclude_dirs: Sequence[str] = DEFAULT_EXCLUDED_DIRS,
) -> list[Path]:
    """Find *.pdf files in a folder, skipping bookkeeping sub folders."""
    root = Path(folder)
    if not root.is_dir():
        return []
    excluded = {name.lower() for name in exclude_dirs}
    found: list[Path] = []

    def walk(current: Path, depth: int) -> None:
        if depth > 8:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda p: natural_key(p.name))
        except OSError:
            return
        for entry in entries:
            if entry.is_dir():
                if entry.name.lower() in excluded or entry.name.startswith("."):
                    continue
                if recursive:
                    walk(entry, depth + 1)
            elif entry.is_file() and entry.suffix.lower() == ".pdf":
                found.append(entry)

    walk(root, 0)
    return sorted_naturally(found)


def load_pymupdf():
    """Import PyMuPDF, accepting both the new and the legacy module name.

    PyMuPDF 1.24+ is imported as ``pymupdf``; older releases only provide the
    ``fitz`` alias (which now emits a deprecation warning). Keeping the import in
    one place makes the pypdf fallback easy to test as well.
    """
    try:
        import pymupdf  # type: ignore[import-not-found]

        return pymupdf
    except ImportError:
        pass
    import fitz  # type: ignore[import-not-found]

    return fitz


def count_pages(pdf_path: str | Path) -> tuple[int, str]:
    """Return (page_count, method) where method is "PyMuPDF" or "pypdf"."""
    path = Path(pdf_path)
    if not path.is_file():
        raise PdfPageCountError(f"PDF nav atrasts: {path}")

    errors: list[str] = []

    try:
        mupdf = load_pymupdf()
        with mupdf.open(path) as document:
            count = int(document.page_count)
        if count < 1:
            raise ValueError("page_count < 1")
        return count, "PyMuPDF"
    except Exception as exc:  # noqa: BLE001 - any failure falls back to pypdf
        errors.append(f"PyMuPDF: {exc}")

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        count = len(reader.pages)
        if count < 1:
            raise ValueError("page count < 1")
        return count, "pypdf"
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pypdf: {exc}")

    raise PdfPageCountError(
        f"Nevar noteikt lappušu skaitu failam {path.name}: " + " | ".join(errors)
    )


@dataclass(frozen=True)
class PdfInfo:
    """Everything the orchestrator needs to know about one PDF."""

    path: Path
    page_count: int
    page_count_method: str
    size_bytes: int = 0
    modified: float = 0.0
    first_page_size: tuple[float, float] | None = None
    extra: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem


def first_page_size(pdf_path: str | Path) -> tuple[float, float] | None:
    """Width/height of page 1 in points, or None when unavailable."""
    try:
        mupdf = load_pymupdf()

        with mupdf.open(pdf_path) as document:
            rect = document[0].rect
            return (round(float(rect.width), 2), round(float(rect.height), 2))
    except Exception:  # noqa: BLE001
        return None


def pdf_info(pdf_path: str | Path) -> PdfInfo:
    """Collect page count plus basic file information for one PDF."""
    path = Path(pdf_path)
    count, method = count_pages(path)
    stat = path.stat()
    return PdfInfo(
        path=path,
        page_count=count,
        page_count_method=method,
        size_bytes=stat.st_size,
        modified=stat.st_mtime,
        first_page_size=first_page_size(path),
    )
