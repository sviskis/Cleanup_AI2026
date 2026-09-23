"""MAPPING preview pane: thumbnails <-> Treeview synchronisation (Tk, no Illustrator).

The preview is presentation only: selection still lives in the Treeview (fed by the
controller's plan) and every action ends up in an existing controller/core call.
Skipped automatically when no display is available.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

tkinter = pytest.importorskip("tkinter")

from pdf_ai_batch.core import state  # noqa: E402
from pdf_ai_batch.core.project import JobProject  # noqa: E402
from pdf_ai_batch.gui import main_window  # noqa: E402
from pdf_ai_batch.preview import PreviewError  # noqa: E402
from pdf_ai_batch.tests.fakes import FakeIllustrator  # noqa: E402

MANUALIS = "manualis.pdf"
APPENDIX = "appendix.pdf"


class Click:
    """A stand-in for a Tk mouse event (canvas coordinates + modifier state)."""

    def __init__(self, x: int, y: int, *, state: int = 0) -> None:
        self.x = x
        self.y = y
        self.state = state
        self.delta = 0


def wait_for(window, predicate, timeout: float = 25.0) -> bool:
    """Pump the Tk event loop (so the render worker's events arrive) until true."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        window.update()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def pump(window, seconds: float = 1.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        window.update()
        time.sleep(0.02)


@pytest.fixture()
def adapter() -> FakeIllustrator:
    return FakeIllustrator()


@pytest.fixture()
def job(tmp_path, make_pdf) -> JobProject:
    project = JobProject.open(tmp_path / "GUI_PREVIEW_JOB")
    make_pdf(project.pdf_dir / MANUALIS, pages=3)
    make_pdf(project.pdf_dir / APPENDIX, pages=2)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nMASTER template\n")
    return project


@pytest.fixture()
def window(job, adapter):
    app = build_window(job, adapter)
    yield app
    try:
        app.on_close()
    except tkinter.TclError:  # pragma: no cover
        pass


def build_window(job, adapter):
    """A window with the JOB open on the first document (MAPPING fully refreshed)."""
    try:
        app = main_window.MainWindow(adapter_factory=lambda: adapter)
    except tkinter.TclError as exc:  # pragma: no cover - headless
        pytest.skip(f"nav displeja: {exc}")
    app.withdraw()
    app.controller.open_project(job.root)
    app.controller.select_document(MANUALIS)
    app.refresh_all()
    return app


def panel(window):
    tab = window.mapping_tab
    assert tab.preview_panel is not None, "MAPPING must show the preview pane"
    return tab.preview_panel


def click_tile(window, page: int, *, state: int = 0) -> None:
    """Click inside the tile of `page` (the canvas hit test uses these pixels)."""
    tile = panel(window)._tiles[page]
    panel(window)._on_thumb_click(Click(tile["x"] + 4, tile["y"] + 4, state=state))


def test_preview_pane_is_built_and_shows_the_active_document(window):
    pane = panel(window)

    assert pane.page_count() == 3
    assert len(pane._tiles) == 3
    assert pane.focus_page() == 1  # page 1 is shown before the first click
    assert wait_for(window, lambda: pane.thumbnail_count() >= 1)
    assert pane.info_lines()["pdf"] == MANUALIS
    assert pane.info_lines()["state"] == "WAITING"


def test_thumbnails_render_progressively_and_are_cached(window, job):
    pane = panel(window)

    assert wait_for(window, lambda: pane.thumbnail_count() == 3)
    loader_stats = window.preview_loader.stats()

    assert loader_stats["rendered"] >= 1
    assert (job.root / ".cache" / "preview").is_dir()
    assert window.preview_loader.cache.stats()["files"] >= 1


def test_clicking_a_thumbnail_selects_the_row_and_previews_that_page(window):
    pane = panel(window)

    click_tile(window, 3)

    assert window.mapping_tab.selected_pages() == [3]
    assert pane.selected_pages() == [3] and pane.focus_page() == 3
    assert pane.info_lines()["page"] == "3 / 3"
    assert wait_for(window, lambda: pane.preview_size() != (0, 0))


def test_clicking_a_mapping_row_moves_the_thumbnail_selection(window):
    tree = window.mapping_tab.tree
    rows = tree.get_children()

    tree.selection_set(rows[1])
    window.mapping_tab._on_selection()

    pane = panel(window)
    assert pane.selected_pages() == [2]
    assert pane.focus_page() == 2
    assert pane.info_lines()["page"] == "2 / 3"


def test_ctrl_click_adds_and_shift_click_selects_a_range(window):
    click_tile(window, 1)
    click_tile(window, 3, state=0x0004)  # Control
    assert window.mapping_tab.selected_pages() == [1, 3]

    click_tile(window, 2, state=0x0001)  # Shift: anchor 3 -> range 2..3
    assert window.mapping_tab.selected_pages() == [2, 3]


def test_tile_state_comes_from_state_json_after_a_run(window, adapter):
    """WAITING -> DONE on the thumbnail, straight from core/state."""
    pane = panel(window)
    assert pane.tile_states()[1] == "WAITING"

    window.controller.run_selected(["manualis_p001"])
    window.refresh_all()

    assert pane.tile_states()[1] == "DONE"
    assert pane.tile_states()[2] == "WAITING"
    assert str(window.mapping_tab.tree.item("manualis_p001", "values")[5]) == "DONE"


def test_error_state_exposes_type_message_and_attempts(window, adapter):
    adapter.script[2] = "error"  # FakeIllustrator matches the page number / job_id
    window.controller.run_selected(["manualis_p002"])
    window.refresh_all()

    pane = panel(window)
    pane.select_pages([2], focus=2)

    info = pane.info_lines()
    assert info["state"] == state.ERROR
    assert info["attempts"] == "1"
    assert "PROCESSING" in pane.detail_label["text"]
    assert "testa kļūda" in pane.detail_label["text"]
    assert pane.tile_states()[2] == "ERROR"


def test_preview_failure_marks_only_the_tile_and_keeps_the_queue_state(
    job, adapter, monkeypatch
):
    """A render problem is a UI problem: the tile says so, state.json is untouched."""
    def boom(*_args, **_kwargs):
        raise PreviewError("simulēta preview kļūda")

    monkeypatch.setattr("pdf_ai_batch.gui.preview_loader.render_thumbnail", boom)
    window = build_window(job, adapter)  # patched BEFORE the first render request
    try:
        before = job.state_path.read_bytes()  # written when the queue was built
        pane = panel(window)
        assert wait_for(window, lambda: 1 in pane.tile_errors())
        assert pane.tile_states()[1] == "PREVIEW ERROR"
        assert "simulēta" in pane.tile_errors()[1]
        pane.select_pages([1], focus=1)
        assert "simulēta" in pane.detail_label["text"]
        assert job.state_path.read_bytes() == before
        assert window.mapping_tab.tree.get_children()  # mapping stays usable
    finally:
        window.on_close()


def test_switching_the_active_pdf_clears_the_old_selection_and_thumbnails(window, job):
    pane = panel(window)
    click_tile(window, 3)
    assert window.mapping_tab.selected_pages() == [3]
    assert pane.page_count() == 3

    window.controller.select_document(APPENDIX)
    window.refresh_all()

    assert pane.page_count() == 2
    assert sorted(pane.tile_states()) == [1, 2]  # only PDF B's pages exist now
    assert pane.info_lines()["pdf"] == APPENDIX
    assert wait_for(window, lambda: pane.thumbnail_count() >= 1)
    # the old document's renders must not be painted over the new one
    assert set(pane._thumb_sizes) <= {1, 2}


def test_reopening_the_same_job_serves_thumbnails_from_the_cache(job, adapter):
    first = main_window.MainWindow(adapter_factory=lambda: adapter)
    first.withdraw()
    first.controller.open_project(job.root)
    first.controller.select_document(MANUALIS)
    first.refresh_all()
    first_pane = panel(first)
    assert wait_for(first, lambda: first_pane.thumbnail_count() == 3)
    first.on_close()

    second = main_window.MainWindow(adapter_factory=lambda: adapter)
    second.withdraw()
    try:
        second.controller.open_project(job.root)
        second.controller.select_document(MANUALIS)
        second.refresh_all()
        second_pane = panel(second)
        assert wait_for(second, lambda: second_pane.thumbnail_count() == 3)

        assert second.preview_loader.stats()["cache_hits"] >= 3
    finally:
        second.on_close()


def test_live_refresh_keeps_the_tiles_showing_running(window, monkeypatch):
    """While a batch runs the rows/tiles are re-read, so RUNNING is visible."""
    calls: list[str] = []
    monkeypatch.setattr(window.mapping_tab, "refresh", lambda: calls.append("refresh"))
    monkeypatch.setattr(
        type(window.runner), "busy", property(lambda self: True), raising=False
    )

    window._live_refresh_at = 0.0
    window._maybe_refresh_live_states(100.0)
    window._maybe_refresh_live_states(100.1)  # too soon: no second refresh

    assert calls == ["refresh"]
    assert window._live_refresh_at == 100.0

    monkeypatch.setattr(
        type(window.runner), "busy", property(lambda self: False), raising=False
    )
    window._maybe_refresh_live_states(200.0)
    assert calls == ["refresh"]  # nothing runs: no polling


def test_fit_100_and_zoom_buttons_change_the_render_size(window):
    pane = panel(window)
    assert wait_for(window, lambda: pane.preview_size() != (0, 0))
    fit_size = pane.preview_size()

    pane.on_actual_size()  # 100% = 72 dpi: an A4 page is 595 x 842 px
    assert wait_for(window, lambda: pane.preview_size() != fit_size)
    assert pane.preview_size()[1] == pytest.approx(842, abs=3)

    pane.on_zoom_out()
    assert wait_for(window, lambda: pane.preview_size()[1] != 842)
    smaller = pane.preview_size()
    assert smaller[1] < 842
    pane.on_fit()
    assert pane.zoom_label["text"] == "fit"


def test_open_output_uses_the_context_seam_and_refuses_bad_states(window, adapter, job):
    opened: list[Path] = []
    window.ctx.open_path = opened.append
    window.controller.run_selected(["manualis_p001"])
    window.refresh_all()

    pane = panel(window)
    pane.select_pages([1], focus=1)
    pane._action("open_output")

    output = job.output_dir / "manualis__001.ai"
    assert opened == [output]

    # a DONE page whose output disappeared is reported, not opened
    opened.clear()
    output.unlink()
    pane._action("open_output")
    assert opened == []
    assert "nav atrasts" in window.status["text"]

    # a page that is not DONE is refused as well
    pane.select_pages([2], focus=2)
    pane._action("open_output")
    assert opened == []
    assert "DONE" in window.status["text"]



def test_a_hundred_page_document_opens_without_rendering_everything(window, tmp_path, make_pdf):
    """Opening the JOB must stay fast; thumbnails fill in while the GUI is usable."""
    from pdf_ai_batch.core.project import JobProject

    project = JobProject.open(tmp_path / "GUI_BIG_JOB")
    make_pdf(project.pdf_dir / "big.pdf", pages=120)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%x")

    started = time.perf_counter()
    window.controller.open_project(project.root)
    window.controller.select_document("big.pdf")
    window.refresh_all()
    open_seconds = time.perf_counter() - started

    pane = panel(window)
    assert pane.page_count() == 120
    assert len(pane._tiles) == 120  # placeholders exist, images do not
    assert pane.thumbnail_count() < 10  # the GUI never waits for 120 renders
    assert open_seconds < 10.0

    assert wait_for(window, lambda: pane.thumbnail_count() >= 3, timeout=30)
    assert pane.thumbnail_count() < 120  # progressive, not all at once


def test_preview_modules_are_tk_free_and_the_gui_stays_free_of_pdf_logic():
    """ARCHITECTURE RULE: `preview/` renders with PyMuPDF, `gui/` only displays it."""
    import re

    repo_root = Path(__file__).resolve().parents[2]
    preview_dir = repo_root / "pdf_ai_batch" / "preview"
    gui_dir = repo_root / "pdf_ai_batch" / "gui"
    preview_sources = {path.name: path.read_text(encoding="utf-8") for path in preview_dir.glob("*.py")}
    assert set(preview_sources) >= {"__init__.py", "renderer.py", "cache.py"}
    import_pattern = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", re.MULTILINE)

    for name, source in preview_sources.items():
        modules = set(import_pattern.findall(source))
        assert not any(module.startswith(("tkinter", "win32com", "pythoncom")) for module in modules), (
            name,
            modules,
        )
        assert "DoJavaScriptFile" not in source, name
        assert "state.save_state(" not in source, name  # previews never touch the queue
        assert "config.write" not in source, name
    # PyMuPDF is imported in exactly one place (core/pdf_info.load_pymupdf)
    assert "from ..core.pdf_info import load_pymupdf" in preview_sources["renderer.py"]
    assert "import pymupdf" not in preview_sources["renderer.py"]

    for name in ("preview_loader.py", "preview_panel.py"):
        source = (gui_dir / name).read_text(encoding="utf-8")
        modules = set(import_pattern.findall(source))
        assert not any(
            module.startswith(("pymupdf", "fitz", "win32com", "pythoncom")) for module in modules
        ), (name, modules)
        assert "state.save_state(" not in source, name

    # the panel only draws what it is given: no rendering, no file handles
    panel_checks = (gui_dir / "preview_panel.py").read_text(encoding="utf-8")
    for forbidden in ("render_thumbnail(", "render_preview(", "page_geometry(", "open("):
        assert forbidden not in panel_checks, (forbidden, "preview_panel.py")
    assert "import base64" in panel_checks  # PNG bytes -> PhotoImage, nothing else
    # the loader is the only GUI module that knows the renderer
    loader_source = (gui_dir / "preview_loader.py").read_text(encoding="utf-8")
    assert "from ..preview.renderer import" in loader_source

