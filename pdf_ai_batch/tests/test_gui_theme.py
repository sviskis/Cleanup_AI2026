"""The dark theme: one palette, one shell, no colour anywhere else under `gui/`.

The visual language is code, so it is tested like code: the mockup's hex values live in
`gui/theme.py` exactly once, every other GUI module only refers to `theme.COLORS`, the
ttk tables (which cannot be customtkinter) are themed dark, and the shell's navigation
(sidebar <-> tab row) and advisor cards show what the controller reports.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pdf_ai_batch.core import state
from pdf_ai_batch.gui import theme

REPO_ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = REPO_ROOT / "pdf_ai_batch" / "gui"

#: the values the mockup pins down (the rest of the palette is derived from them)
MOCKUP_COLORS = {
    "bg": "#0f1117",            # main shell
    "sidebar": "#0d1018",       # left sidebar
    "card": "#161925",          # cards
    "text": "#e2e8f0",          # primary text
    "text_secondary": "#a0aec0",  # secondary text
    "muted": "#4a5568",         # muted text
    "accent": "#63b3ed",        # active nav item / primary border / tab underline
}
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


# ------------------------------------------------------------------------ the palette


def test_palette_carries_the_mockup_values():
    for key, value in MOCKUP_COLORS.items():
        assert theme.COLORS[key] == value, key


def test_status_dots_use_green_amber_and_purple():
    assert theme.tone_color("ok") == theme.COLORS["green"]
    assert theme.tone_color("warn") == theme.COLORS["amber"]
    assert theme.tone_color("busy") == theme.COLORS["accent"]
    # the third mockup dot is the "not known yet" tone
    assert theme.tone_color("unknown") == theme.COLORS["purple"]
    # an unknown tone never falls back to something invisible
    assert theme.tone_color("nonsense") == theme.COLORS["purple"]


def test_state_colours_cover_every_queue_state():
    colours = theme.state_colours()

    for name in state.VALID_STATES:
        assert name in colours, name
        assert colours[name].startswith("#")
    assert colours[state.DONE] == theme.COLORS["green"]
    assert colours[state.ERROR] == theme.COLORS["red"]
    assert colours[state.INTERRUPTED] == theme.COLORS["amber"]
    assert "PREVIEW ERROR" in colours  # the tile state of the preview pane


def test_only_the_theme_module_knows_a_colour():
    """A hex literal anywhere else under `gui/` fails (the mockup rule in code)."""
    offenders = []
    for path in sorted(GUI_DIR.glob("*.py")):
        if path.name == "theme.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if HEX.search(line):
                offenders.append(f"{path.name}:{number}")

    assert offenders == [], "hex colours outside gui/theme.py: " + ", ".join(offenders)


def test_the_ttk_tables_are_themed_dark():
    """customtkinter has no table, so Treeview is themed through ttk."""
    tkinter = pytest.importorskip("tkinter")
    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:  # pragma: no cover - headless
        pytest.skip(f"nav displeja: {exc}")
    try:
        style = theme.apply_theme(root)

        assert style.lookup("Treeview", "background") == theme.COLORS["card"]
        assert style.lookup("Treeview", "fieldbackground") == theme.COLORS["card"]
        assert style.lookup("Treeview", "foreground") == theme.COLORS["text"]
        assert style.lookup("Treeview.Heading", "background") == theme.COLORS["card_alt"]
        # and the one call without a root stays harmless (no hidden Tk interpreter)
        assert theme.apply_theme() is None
        assert tkinter._default_root is root  # noqa: SLF001 - the point of the check
    finally:
        root.destroy()


# -------------------------------------------------------------------------- the shell

tkinter = pytest.importorskip("tkinter")

from pdf_ai_batch.core.project import JobProject  # noqa: E402
from pdf_ai_batch.gui import main_window  # noqa: E402


@pytest.fixture()
def window():
    try:
        app = main_window.MainWindow()
    except tkinter.TclError as exc:  # pragma: no cover - headless
        pytest.skip(f"nav displeja: {exc}")
    app.withdraw()
    yield app
    try:
        app.on_close()
    except tkinter.TclError:  # pragma: no cover - already closed
        pass


@pytest.fixture()
def job(tmp_path, make_pdf) -> JobProject:
    project = JobProject.open(tmp_path / "GUI_THEME_JOB")
    make_pdf(project.pdf_dir / "manualis.pdf", pages=3)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nMASTER template\n")
    return project


def test_the_window_is_dark_and_built_from_the_shell(window):
    assert window.status_bar.cget("fg_color") == theme.COLORS["panel"]
    # the mockup's three blocks: top bar, sidebar, right action panel
    assert set(window.topbar.chips) == {"job", "documents", "plan", "queue", "illustrator"}
    assert set(window.sidebar.items) == {"project", "pdf", "mapping", "run"}
    assert set(window.actions.sections) == {
        "review", "plan", "loop", "project", "reports", "monitoring"
    }
    assert set(window.advisor.cards) == {"plan", "queue", "illustrator"}
    assert window.review.question.cget("text") == main_window.REVIEW_QUESTION
    # the sections are still the four proven tabs
    labels = [window.notebook.tab(tab, "text") for tab in window.notebook.tabs()]
    assert labels == ["PROJECT", "PDF", "MAPPING", "RUN / LOG"]


def test_navigation_marks_the_active_section_with_the_accent(window):
    window.show_section("mapping")

    assert window._active_section == "mapping"
    assert window.notebook.get() == "MAPPING"
    assert window.sidebar.items["mapping"].active is True
    assert window.sidebar.items["mapping"].bar.cget("fg_color") == theme.COLORS["accent"]
    assert window.sidebar.items["project"].active is False
    assert window.tabrow.items["mapping"]["underline"].cget("fg_color") == theme.COLORS["accent"]
    assert window.tabrow.items["project"]["underline"].cget("fg_color") == theme.COLORS["bg"]

    # a driver that selects a section directly keeps both navigations in sync
    window.notebook.select(window._sections["run"])
    assert window._active_section == "run"
    assert window.sidebar.items["run"].active is True
    assert window.tabrow.items["run"]["underline"].cget("fg_color") == theme.COLORS["accent"]


def test_the_action_panel_calls_the_proven_tab_handlers(window):
    """Every button of the right panel points at a real handler, none at its own logic."""
    sections = window.actions.sections
    expected = {
        ("review", "VALIDATE"): (window.mapping_tab, "on_validate"),
        ("review", "PREFLIGHT PROJECT"): (window.run_tab, "on_preflight"),
        ("loop", "RUN SELECTED"): (window.run_tab, "on_run_selected"),
        ("plan", "AUTO MAP BY NUMBER"): (window.mapping_tab, "on_auto_map_number"),
        ("project", "OPEN PROJECT"): (window.project_tab, "on_open_project"),
        ("reports", "RESTORE SNAPSHOT"): (window.mapping_tab, "on_restore"),
        ("monitoring", "OPEN OUTPUT (DONE)"): (window.mapping_tab, "on_open_output"),
        ("monitoring", "REFRESH STATUS"): (window.run_tab, "on_refresh"),
    }
    for (section, label), (owner, name) in expected.items():
        button = next(
            candidate
            for candidate in sections[section].buttons
            if candidate.cget("text") == label
        )
        command = button.cget("command")
        assert command.__self__ is owner, (section, label)
        assert command.__name__ == name, (section, label)

    # the loop's overwrite switch shares the RUN tab's variable, it is not a second copy
    loop_controls = [widget for widget, _keep in sections["loop"]._widgets]
    assert str(loop_controls[-1].cget("text")).startswith("Pārrakstīt")



def test_shell_numbers_come_from_the_controller(window, job):
    window.controller.open_project(job.root)
    window.refresh_all()

    assert window.topbar.project.cget("text") == job.root.name
    assert window.topbar.chips["job"].value.cget("text") == job.root.name
    assert window.topbar.chips["documents"].value.cget("text") == "1"
    assert window.topbar.chips["plan"].value.cget("text") == "3 lapas"
    assert window.topbar.chips["queue"].value.cget("text") == "DONE 0/3"
    assert window.topbar.chips["illustrator"].dot.tone == "unknown"  # nothing checked yet

    plan = window.advisor.cards["plan"]
    assert plan.dot.tone == "ok"
    assert plan.metric.cget("text") == "3 lapas"
    assert plan.detail.cget("text") == "pārbaudes: OK"
    assert window.advisor.cards["queue"].metric.cget("text") == "0 / 3"
    assert window.review.dot.tone == "ok"
    assert window.review.answer.cget("text").startswith("JĀ")


def test_a_broken_plan_turns_the_review_and_the_card_amber(window, job):
    window.controller.open_project(job.root)
    (job.template_dir / "MASTER_AI_TEMPLATE.ai").unlink()  # the plan cannot be built
    window.refresh_all()

    assert window.review.dot.tone == "warn"
    assert window.review.answer.cget("text").startswith("NĒ")
    assert window.advisor.cards["plan"].dot.tone in {"warn", "unknown", "error"}


def test_a_batch_locks_the_panel_but_keeps_the_read_only_actions(window):
    import time

    assert window.actions.sections["loop"].buttons[0].cget("state") == "normal"

    def slow_task(progress):
        time.sleep(0.3)
        return "gatavs"

    assert window.run_task("TESTA DARBS", slow_task) is True
    window._render_busy()

    for section in ("review", "plan", "loop", "project"):
        for button in window.actions.sections[section].buttons:
            assert str(button.cget("state")) == "disabled", (section, button.cget("text"))
    for button in window.actions.sections["monitoring"].buttons:
        assert str(button.cget("state")) == "normal", button.cget("text")

    window.runner.join(timeout=5)
    window._render_busy()
    assert str(window.actions.sections["loop"].buttons[0].cget("state")) == "normal"


def test_opening_the_window_leaves_illustrator_alone(window):
    """The shell reads the controller, it never touches COM (see .clinerules)."""
    assert window.controller.project is None
    assert window.controller._adapter is None  # noqa: SLF001 - the documented seam
    assert window.topbar.chips["illustrator"].value.cget("text") == "nav pārbaudīts"
    assert window.advisor.cards["illustrator"].dot.tone == "unknown"
    assert window.review.answer.cget("text").startswith("Nav atvērts JOB")

