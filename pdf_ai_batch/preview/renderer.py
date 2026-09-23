"""PDF page rendering with PyMuPDF (no Tk, no COM, no Illustrator).

One page at a time, always through `core/pdf_info.load_pymupdf()` (the single place
that knows the PyMuPDF import), so the whole preview stack shares the page count
code path of the queue. Every failure becomes a `PreviewError` - a broken page or a
corrupt PDF must never crash the GUI and must never touch the queue state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.pdf_info import load_pymupdf

DEFAULT_THUMBNAIL_WIDTH = 160
DEFAULT_PREVIEW_LONG_SIDE = 1000
THUMBNAIL_MIN_WIDTH = 60
PREVIEW_MIN_LONG_SIDE = 200
PREVIEW_MAX_LONG_SIDE = 4000
MIN_ZOOM = 0.05
MAX_ZOOM = 4.0
MM_PER_POINT = 25.4 / 72.0
IMAGE_FORMAT = "png"


class PreviewError(RuntimeError):
    """Raised when a page cannot be rendered (corrupt file, broken page, missing)."""


@dataclass(frozen=True)
class PageGeometry:
    """Geometry of one page: what the GUI shows and what the renderer scales from."""

    page: int
    page_count: int
    width_pt: float
    height_pt: float
    rotation: int = 0

    @property
    def width_mm(self) -> float:
        return round(self.width_pt * MM_PER_POINT, 1)

    @property
    def height_mm(self) -> float:
        return round(self.height_pt * MM_PER_POINT, 1)

    @property
    def size_label(self) -> str:
        """Human readable size, e.g. "210 x 297 mm"."""
        return f"{self.width_mm:.0f} x {self.height_mm:.0f} mm"

    @property
    def aspect(self) -> float:
        """width / height (>0). Used to keep the preview inside its pane."""
        if self.height_pt <= 0:
            return 1.0
        return self.width_pt / self.height_pt


@dataclass(frozen=True)
class RenderedPage:
    """One rendered page: PNG bytes plus what the widget needs to place it."""

    image: bytes
    width: int
    height: int
    geometry: PageGeometry
    zoom: float = 1.0
    image_format: str = IMAGE_FORMAT

    @property
    def long_side(self) -> int:
        return max(self.width, self.height)

    @property
    def nbytes(self) -> int:
        return len(self.image)


def document_fingerprint(pdf_path: str | Path) -> tuple[str, float, int]:
    """(absolute forward slashed path, mtime, size) - the identity of a PDF file.

    Part of the cache key: a modified PDF (new page count, edited page) produces a
    different fingerprint, so an old thumbnail can never be shown for new content.
    """
    path = Path(pdf_path)
    try:
        stat = path.stat()
    except OSError as exc:
        raise PreviewError(f"PDF nav pieejams: {path.name} ({exc})") from exc
    return (path.resolve().as_posix(), float(stat.st_mtime), int(stat.st_size))


def png_size(data: bytes) -> tuple[int, int]:
    """Width/height from a PNG byte string (IHDR), (0, 0) when it is not a PNG.

    Used for cache hits: the image is already on disk, and decoding only the header
    avoids a full picture decode just to learn its geometry.
    """
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    try:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
    except Exception:  # noqa: BLE001 - a damaged header is simply "unknown"
        return (0, 0)
    return (width, height)


def _open(pdf_path: str | Path):
    """Open the PDF with PyMuPDF, mapping every failure to PreviewError."""
    path = Path(pdf_path)
    if not path.is_file():
        raise PreviewError(f"PDF nav atrasts: {path}")
    try:
        mupdf = load_pymupdf()
        return mupdf.open(str(path))
    except Exception as exc:  # noqa: BLE001 - a corrupt PDF is a preview problem
        raise PreviewError(f"PDF nevar atvērt: {path.name} ({type(exc).__name__}: {exc})") from exc


def _page(document, page: int):
    """One page object, with the range checked (1 based)."""
    total = int(document.page_count)
    if page < 1 or page > total:
        raise PreviewError(f"lapa {page} ārpus PDF robežām (1..{total})")
    try:
        return document[page - 1]
    except Exception as exc:  # noqa: BLE001 - a broken page object
        raise PreviewError(f"lapu {page} nevar nolasīt ({type(exc).__name__}: {exc})") from exc


def page_geometry(pdf_path: str | Path, page: int) -> PageGeometry:
    """Page size (points + mm), rotation and the page count of the document."""
    document = _open(pdf_path)
    try:
        target = _page(document, int(page))
        try:
            rect = target.rect
            width = float(rect.width)
            height = float(rect.height)
        except Exception as exc:  # noqa: BLE001
            raise PreviewError(f"lapas {page} izmēru nevar nolasīt: {exc}") from exc
        try:
            rotation = int(target.rotation or 0)
        except Exception:  # noqa: BLE001 - rotation is cosmetic
            rotation = 0
        return PageGeometry(
            page=int(page),
            page_count=int(document.page_count),
            width_pt=round(width, 2),
            height_pt=round(height, 2),
            rotation=rotation,
        )
    finally:
        document.close()


def _scale_for(
    geometry: PageGeometry,
    *,
    width: int | None,
    height: int | None,
    max_long_side: int | None,
    zoom: float | None,
) -> float:
    """One uniform scale (aspect ratio preserved) for the requested constraint."""
    if zoom is not None:
        return max(MIN_ZOOM, min(MAX_ZOOM, float(zoom)))
    candidates: list[float] = []
    if width:
        candidates.append(float(width) / max(geometry.width_pt, 1.0))
    if height:
        candidates.append(float(height) / max(geometry.height_pt, 1.0))
    if max_long_side:
        longest = max(geometry.width_pt, geometry.height_pt, 1.0)
        candidates.append(float(max_long_side) / longest)
    if not candidates:
        candidates.append(1.0)
    scale = min(candidates)  # fit inside every given box
    return max(MIN_ZOOM, min(MAX_ZOOM, scale))



def render_page(
    pdf_path: str | Path,
    page: int,
    *,
    width: int | None = None,
    height: int | None = None,
    max_long_side: int | None = None,
    zoom: float | None = None,
) -> RenderedPage:
    """Render one page to PNG bytes. Aspect ratio is always preserved.

    `width` / `height` / `max_long_side` fit the page inside that box; `zoom` (1.0 =
    72 dpi) overrides them. The scale is clamped to `MIN_ZOOM..MAX_ZOOM`, so a tiny
    page is never upscaled into a blur and a huge one is never rendered at an insane
    resolution.
    """
    geometry = page_geometry(pdf_path, int(page))
    scale = _scale_for(
        geometry, width=width, height=height, max_long_side=max_long_side, zoom=zoom
    )
    document = _open(pdf_path)
    try:
        target = _page(document, int(page))
        mupdf = load_pymupdf()
        try:
            pixmap = target.get_pixmap(matrix=mupdf.Matrix(scale, scale), alpha=False)
            data = pixmap.tobytes(IMAGE_FORMAT)
            out_width, out_height = int(pixmap.width), int(pixmap.height)
        except Exception as exc:  # noqa: BLE001 - one unrenderable page
            raise PreviewError(
                f"lapu {page} nevar renderēt ({type(exc).__name__}: {exc})"
            ) from exc
    finally:
        document.close()

    if out_width < 1 or out_height < 1:
        raise PreviewError(f"lapai {page} nav derīgu izmēru")
    return RenderedPage(
        image=data,
        width=out_width,
        height=out_height,
        geometry=geometry,
        zoom=round(scale, 4),
    )


def render_thumbnail(
    pdf_path: str | Path,
    page: int,
    *,
    width: int = DEFAULT_THUMBNAIL_WIDTH,
) -> RenderedPage:
    """Small tile image for the thumbnail browser (width defaults to 160 px)."""
    return render_page(pdf_path, page, width=max(THUMBNAIL_MIN_WIDTH, int(width)))


def render_preview(
    pdf_path: str | Path,
    page: int,
    *,
    max_long_side: int = DEFAULT_PREVIEW_LONG_SIDE,
    zoom: float | None = None,
) -> RenderedPage:
    """Larger image for the preview pane (longest side defaults to 1000 px)."""
    limit = max(PREVIEW_MIN_LONG_SIDE, min(PREVIEW_MAX_LONG_SIDE, int(max_long_side)))
    return render_page(pdf_path, page, max_long_side=limit, zoom=zoom)

