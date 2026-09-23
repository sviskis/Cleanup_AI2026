"""PDF preview: thumbnails and large page renders (PyMuPDF only).

Rendering belongs to Python and to this package ONLY:

    PDF -> PyMuPDF -> PNG bytes -> Tk widgets

No Illustrator, no Acrobat/COM, no external viewers, no Ghostscript, no OCR. The
GUI never talks to PyMuPDF directly (see `gui/preview_loader.py`, which runs the
render calls in a worker thread and streams the results back through the event bus).

Public API:

    render_thumbnail(pdf, page)          small tile image (default width 160 px)
    render_preview(pdf, page, ...)       larger image for the preview pane
    page_geometry(pdf, page)             size in points/mm, rotation, page count
    document_fingerprint(pdf)            (path, mtime, size) - the cache identity
    PreviewCache(root)                   disposable disk cache (JOB/.cache/preview)
    PreviewError                         any rendering failure, safely catchable
"""

from __future__ import annotations

from .cache import CACHE_DIR_NAME, CACHE_ROOT_NAME, CacheKey, PreviewCache
from .renderer import (
    DEFAULT_PREVIEW_LONG_SIDE,
    DEFAULT_THUMBNAIL_WIDTH,
    MAX_ZOOM,
    MIN_ZOOM,
    PageGeometry,
    PreviewError,
    RenderedPage,
    document_fingerprint,
    page_geometry,
    png_size,
    render_page,
    render_preview,
    render_thumbnail,
)

__all__ = [
    "CACHE_DIR_NAME",
    "CACHE_ROOT_NAME",
    "CacheKey",
    "DEFAULT_PREVIEW_LONG_SIDE",
    "DEFAULT_THUMBNAIL_WIDTH",
    "MAX_ZOOM",
    "MIN_ZOOM",
    "PageGeometry",
    "PreviewCache",
    "PreviewError",
    "RenderedPage",
    "document_fingerprint",
    "page_geometry",
    "png_size",
    "render_page",
    "render_preview",
    "render_thumbnail",
]
