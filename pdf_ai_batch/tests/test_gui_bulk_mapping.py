"""Bulk mapping through the controller (milestone 6): ranges, presets, clipboard.

Two things are proven here:

1. every bulk action of the MAPPING tab works through `AppController` and lands in
   `config.json` + the queue (no display, no Illustrator), and
2. the GUI really does not own the mapping rules: the range parser, the numbered
   mapping, the clipboard and the presets all come from `core/mapping_rules.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_ai_batch.core import config as cfg
from pdf_ai_batch.core import mapping_rules as mr
from pdf_ai_batch.core.project import JobProject
from pdf_ai_batch.gui import controller
from pdf_ai_batch.tests.fakes import FakeIllustrator


@pytest.fixture()
def adapter() -> FakeIllustrator:
    return FakeIllustrator()


@pytest.fixture()
def job(tmp_path, make_pdf) -> JobProject:
    """A real JOB: one 12 page PDF, numbered templates, one ambiguous number."""
    project = JobProject.open(tmp_path / "BULK_JOB")
    make_pdf(project.pdf_dir / "manualis.pdf", pages=12)
    templates = project.template_dir
    for name in ("001_cover.ai", "002_intro.ai", "003_separator.ai", "MASTER_AI_TEMPLATE.ai"):
        (templates / name).write_bytes(b"%PDF-1.5\ntemplate\n")
    return project


@pytest.fixture()
def gui(job, adapter) -> controller.AppController:
    app = controller.AppController(adapter_factory=lambda: adapter)
    app.open_project(job.root)
    app.select_document("manualis.pdf")
    return app


def templates_of(app: controller.AppController) -> list[str | None]:
    return [row.template for row in app.mapping_rows()]


def stored_templates(app: controller.AppController, pdf: str = "manualis.pdf") -> list[str | None]:
    config = cfg.load_config(app.project.config_path)
    return [entry["template"] for entry in cfg.page_entries(config, pdf)]


# ------------------------------------------------------------------ range parsing


def test_controller_parses_ranges_with_the_core_page_count(gui):
    assert gui.parse_pages("1") == [1]
    assert gui.parse_pages("2-5") == [2, 3, 4, 5]
    assert gui.parse_pages("1,3,5") == [1, 3, 5]
    assert gui.parse_pages("1-5,8") == [1, 2, 3, 4, 5, 8]
    assert gui.parse_pages("*") == list(range(1, 13))
    assert gui.format_pages([1, 2, 3, 5, 6]) == "1-3,5-6"

    with pytest.raises(controller.ControllerError) as excinfo:
        gui.parse_pages("13")  # beyond the 12 page document
    assert "12" in str(excinfo.value)
    for bad in ("0", "-1", "a", "1-", "1.5"):
        with pytest.raises(controller.ControllerError):
            gui.parse_pages(bad)


def test_gui_controller_does_not_implement_mapping_rules_itself():
    """The GUI has no range parser, no auto map and no preset logic of its own."""
    source = Path(controller.__file__).read_text(encoding="utf-8")

    # the core module is the one and only implementation
    assert "from ..core import history, mapping_rules" in source
    assert "mapping_rules.parse_pages" in source
    # and the controller never re-implements it with a regex or a manual split
    assert "re.compile" not in source
    assert ".split(\"-\")" not in source
    assert "split(',')" not in source
    # no config writing outside the single funnel (json.dumps for the no-op check is fine)
    assert source.count("cfg.save_config(") == 1
    assert "json.dump(" not in source


# -------------------------------------------------------------- bulk assignment


def test_assign_template_to_range_persists_and_rebuilds_the_queue(gui):
    report = gui.assign_template_to_range(gui.parse_pages("2-5"), "002_intro.ai", layer="INTRO")

    assert report["changed"] == [2, 3, 4, 5]
    assert stored_templates(gui)[1:5] == ["002_intro.ai"] * 4
    assert templates_of(gui)[1:5] == ["002_intro.ai"] * 4
    rows = {row.page: row for row in gui.mapping_rows()}
    assert rows[2].layer == "INTRO"
    assert rows[2].template_path.name == "002_intro.ai"
    assert rows[2].state == "WAITING"  # a plan edit never touches the run history


def test_templates_and_run_history_survive_a_bulk_edit(gui, adapter):
    adapter.script[1] = "error"
    gui.run_selected(["manualis_p001"])
    assert gui.mapping_rows()[0].state == "ERROR"

    gui.assign_template_to_range([1, 2, 3], "001_cover.ai")

    assert gui.mapping_rows()[0].state == "ERROR"
    assert gui.mapping_rows()[0].attempts == 1
    assert stored_templates(gui)[:3] == ["001_cover.ai"] * 3


def test_assign_template_to_range_rejects_unknown_pages_and_templates(gui):
    with pytest.raises(controller.ControllerError):
        gui.assign_template_to_range([99], "001_cover.ai")
    with pytest.raises(controller.ControllerError):
        gui.assign_template_to_range([1], "cover.txt")
    # nothing was written at all: no config.json appeared
    assert gui.project.config_path.exists() is False
    assert stored_templates(gui) == []


def test_clear_override_and_use_default(gui):
    gui.assign_template_to_range([1, 2], "001_cover.ai", layer="COVER")
    gui.clear_pages([1])

    rows = {row.page: row for row in gui.mapping_rows()}
    assert stored_templates(gui)[0] is None  # back to the document default
    assert stored_templates(gui)[1] == "001_cover.ai"
    assert rows[1].layer == "ARTWORK"
    assert rows[2].layer == "COVER"
    assert rows[1].template == gui.default_template_name()  # resolved for display

    gui.use_default_template([2])
    assert stored_templates(gui)[1] is None
    assert rows[1].layer == "ARTWORK"


def test_auto_assign_templates_still_works_positionally(gui):
    rows = gui.auto_assign_templates()

    assert [row.template for row in rows][:3] == [
        "001_cover.ai",
        "002_intro.ai",
        "003_separator.ai",
    ]
    # pages beyond the numbered pool use the default (MASTER) template
    assert [row.template for row in rows][3:] == ["MASTER_AI_TEMPLATE.ai"] * 9
    # the fixture's plan already was the positional plan, so nothing had to change
    assert gui.snapshot_count() == 0


def test_auto_assign_templates_saves_a_real_change(gui):
    gui.use_default_template([1, 2, 3])  # a real change: the three pages lose their template
    assert stored_templates(gui)[:3] == [None, None, None]

    gui.auto_assign_templates()

    assert stored_templates(gui)[:3] == ["001_cover.ai", "002_intro.ai", "003_separator.ai"]
    assert stored_templates(gui)[3:] == [None] * 9
    assert gui.snapshot_count() == 1  # the auto assign snapshot (nothing existed before it)


# ------------------------------------------------------- numbered auto mapping


def test_auto_map_by_template_number_through_the_controller(gui):
    gui.use_default_template([1, 2, 3])  # so the numbered mapping really changes something
    assert stored_templates(gui)[:3] == [None, None, None]

    report = gui.auto_map_by_template_number()

    assert report["assigned"] == {1: "001_cover.ai", 2: "002_intro.ai", 3: "003_separator.ai"}
    assert report["problems"] == []
    assert stored_templates(gui)[:4] == ["001_cover.ai", "002_intro.ai", "003_separator.ai", None]
    assert all(row.template != "MASTER_AI_TEMPLATE.ai" for row in gui.mapping_rows()[:3])


def test_auto_map_by_template_number_reports_ambiguity(gui, job):
    (job.template_dir / "002_dubultais.ai").write_bytes(b"%PDF-1.5\nx\n")
    gui.assign_template_to_range([2], "003_separator.ai")  # a deliberate manual override

    report = gui.auto_map_by_template_number()

    assert 2 not in report["assigned"]
    assert report["ambiguous"] == {2: ["002_dubultais.ai", "002_intro.ai"]}
    assert report["problems"]
    # the ambiguous page keeps the operator's mapping: the engine never guesses
    assert stored_templates(gui)[1] == "003_separator.ai"
    assert stored_templates(gui)[0] == "001_cover.ai"
    assert stored_templates(gui)[2] == "003_separator.ai"


# ----------------------------------------------------------- clipboard + presets


def test_copy_and_paste_mapping_within_one_pdf(gui):
    gui.assign_template_to_range([6, 7], "002_intro.ai", layer="INTRO")
    clipboard = gui.copy_mapping([6, 7])

    assert clipboard.pages == [6, 7]
    assert gui.mapping_clipboard is clipboard
    assert "002_intro.ai" in clipboard.summary()

    report = gui.paste_mapping([10, 11])

    assert report["pasted_pages"] == [10, 11]
    assert stored_templates(gui)[9:11] == ["002_intro.ai"] * 2
    assert {row.page: row.layer for row in gui.mapping_rows()}[10] == "INTRO"
    # the source pages are untouched
    assert stored_templates(gui)[5:7] == ["002_intro.ai"] * 2


def test_copy_and_paste_mapping_across_documents(gui, make_pdf, job, adapter):
    make_pdf(job.pdf_dir / "appendix.pdf", pages=8)
    gui.assign_template_to_range([1, 2, 3], "001_cover.ai")

    clipboard = gui.copy_mapping([1, 2, 3])
    gui.select_document("appendix.pdf")
    report = gui.paste_mapping([6, 7, 8])

    assert report["pdf"] == "appendix.pdf"
    assert report["source_pdf"] == "manualis.pdf"
    assert report["pasted_pages"] == [6, 7, 8]
    assert stored_templates(gui, "appendix.pdf")[5:8] == ["001_cover.ai"] * 3
    assert stored_templates(gui, "manualis.pdf")[0] == "001_cover.ai"
    assert clipboard.count == 3


def test_paste_mapping_never_writes_beyond_the_document_and_reports_it(gui):
    gui.assign_template_to_range([1, 2, 3, 4], "001_cover.ai")
    gui.copy_mapping([1, 2, 3, 4])

    report = gui.paste_mapping([9, 10, 11, 12])

    assert report["pasted_pages"] == [9, 10, 11, 12]
    assert report["skipped_pages"] == []
    with pytest.raises(controller.ControllerError) as excinfo:
        gui.paste_mapping([20])
    assert "20" in str(excinfo.value)


def test_paste_without_a_clipboard_is_an_error(gui):
    with pytest.raises(controller.ControllerError) as excinfo:
        gui.paste_mapping([1])
    assert "COPY MAPPING" in str(excinfo.value)


def test_save_preset_apply_preset_and_preview(gui):
    gui.assign_template_to_range([1], "001_cover.ai")
    gui.assign_template_to_range([2, 3, 4], "002_intro.ai")
    gui.assign_template_to_range([5], "003_separator.ai", layer="SEP")

    path = gui.save_preset("magazine_32_pages")

    assert path.name == "magazine_32_pages.json"
    assert path.parent == gui.presets_dir == gui.project.config_dir / "presets"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["version"] == mr.PRESET_VERSION
    assert [entry["pages"] for entry in stored["entries"]] == ["1", "2-4", "5", "6-12"]
    assert [info.name for info in gui.presets()] == ["magazine_32_pages"]

    preview = gui.preset_preview("magazine_32_pages")
    assert preview["targets"] == 12
    assert preview["conflicts"] == {"beyond_page_count": [], "missing_templates": []}
    assert preview["would_change"] == []  # the plan already is the preset

    gui.auto_assign_templates()  # a different plan (positional)
    report = gui.apply_preset("magazine_32_pages")

    # page 1 and 2 already match the preset (positional pool = 001/002/003),
    # pages 3-5 change
    assert report["changed"] == [3, 4, 5]
    assert stored_templates(gui)[:5] == [
        "001_cover.ai",
        "002_intro.ai",
        "002_intro.ai",
        "002_intro.ai",
        "003_separator.ai",
    ]
    assert {row.page: row.layer for row in gui.mapping_rows()}[5] == "SEP"


def test_apply_preset_replace_all_and_unknown_preset(gui):
    gui.assign_template_to_range([1], "001_cover.ai")
    gui.save_preset("mazais")  # captures 1=cover, 2/3 positional, 4-12 = no override
    gui.assign_template_to_range([10, 11, 12], "003_separator.ai")

    report = gui.apply_preset("mazais", replace_all=True)

    # the preset itself puts 10-12 back on the default template
    assert report["changed"] == [10, 11, 12]
    assert report["reset"] == []  # every page is covered by the preset
    assert stored_templates(gui) == [
        "001_cover.ai",
        "002_intro.ai",
        "003_separator.ai",
        *[None] * 9,
    ]

    with pytest.raises(controller.ControllerError):
        gui.preset_preview("nav_eksistē")
    with pytest.raises(controller.ControllerError):
        gui.apply_preset("nav_eksistē")

    # a preset that covers only part of the plan: the rest is reset on request
    partial = {
        "version": mr.PRESET_VERSION,
        "name": "tikai_pirma",
        "entries": [{"pages": "1", "template": "002_intro.ai"}],
    }
    mr.save_preset(gui.presets_dir / "tikai_pirma.json", partial)
    gui.assign_template_to_range([5, 6], "001_cover.ai")

    report = gui.apply_preset("tikai_pirma", replace_all=True)

    assert report["changed"] == [1]
    # only pages that really had an override are reported as reset (4 and 7-12
    # were already on the default template + layer, so nothing churns)
    assert report["reset"] == [2, 3, 5, 6]
    assert stored_templates(gui) == ["002_intro.ai", *[None] * 11]


def test_preset_of_a_larger_document_applies_with_reported_conflicts(gui, make_pdf, job):
    make_pdf(job.pdf_dir / "mazais.pdf", pages=3)
    gui.assign_template_to_range([1], "001_cover.ai")
    gui.assign_template_to_range([2, 3], "002_intro.ai")
    gui.save_preset("no_manualis")

    gui.select_document("mazais.pdf")
    gui.use_default_template(gui.parse_pages("*"))  # mazais starts unassigned
    preview = gui.preset_preview("no_manualis")
    # the preset covers pages 1..12 of the source document, this one has 3
    assert preview["conflicts"]["beyond_page_count"] == list(range(4, 13))
    assert preview["conflicts"]["missing_templates"] == []

    report = gui.apply_preset("no_manualis")

    assert report["changed"] == [1, 2, 3]
    assert report["skipped_pages"] == list(range(4, 13))
    assert stored_templates(gui, "mazais.pdf") == ["001_cover.ai", "002_intro.ai", "002_intro.ai"]


def test_every_config_mutation_goes_through_the_single_funnel(gui, monkeypatch):
    """Milestone 8 snapshots in one place: prove that place is really used."""
    calls: list[tuple[str, str]] = []
    original = gui._before_mutation

    def spy(reason: str, kind: str = "plan") -> None:
        calls.append((reason, kind))
        original(reason, kind)

    monkeypatch.setattr(gui, "_before_mutation", spy)

    # reading is not a mutation (the range parser, the clipboard, a saved preset file)
    gui.parse_pages("1-3")
    gui.save_preset("caur_kanālu")
    assert calls == []

    gui.assign_template_to_range([5], "001_cover.ai")
    assert len(calls) == 1 and "template piešķire" in calls[0][0]
    assert calls[0][1] == "bulk-assign"

    gui.assign_template_to_range([5], "001_cover.ai")  # no change -> no snapshot
    assert len(calls) == 1

    gui.use_default_template([5])
    gui.set_enabled([5], False)
    gui.clear_pages([1])
    gui.copy_mapping([1])
    gui.paste_mapping([3])
    gui.auto_assign_templates()
    gui.apply_preset("caur_kanālu")
    kinds = [kind for _reason, kind in calls]
    reasons = [reason for reason, _kind in calls]

    # assign, use default, enable, clear, paste, auto assign, apply preset = 7 changes
    assert len(calls) == 7
    assert "preset" in kinds and "auto-map" in kinds
    assert kinds.count("bulk-assign") >= 3
    assert any("mapping ielīmēšana" in reason for reason in reasons)
    assert any("lapas" in reason for reason in reasons)  # set_enabled
    assert any("notīru pārrakstus" in reason for reason in reasons)  # clear override


