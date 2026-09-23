"""Plan snapshots and undo through the GUI layer (milestone 8).

The controller owns the funnel (`_mutate_config` -> `_before_mutation` -> validate ->
save -> queue rebuild), so the history behaviour is proven here without a display:
every plan edit snapshots the previous plan, UNDO puts it back, RESTORE keeps the
current plan first, and neither the run history nor the queue state is damaged.
"""

from __future__ import annotations

import json

import pytest

from pdf_ai_batch.core import config as cfg
from pdf_ai_batch.core import history
from pdf_ai_batch.core import state
from pdf_ai_batch.core.project import JobProject
from pdf_ai_batch.gui import controller
from pdf_ai_batch.tests.fakes import FakeIllustrator


@pytest.fixture()
def adapter() -> FakeIllustrator:
    return FakeIllustrator()


@pytest.fixture()
def job(tmp_path, make_pdf) -> JobProject:
    project = JobProject.open(tmp_path / "HISTORY_JOB")
    make_pdf(project.pdf_dir / "manualis.pdf", pages=4)
    for name in ("MASTER_AI_TEMPLATE.ai", "001_cover.ai", "002_intro.ai"):
        (project.template_dir / name).write_bytes(b"%PDF-1.5\ntemplate\n")
    return project


@pytest.fixture()
def gui(job, adapter) -> controller.AppController:
    app = controller.AppController(adapter_factory=lambda: adapter)
    app.open_project(job.root)
    app.select_document("manualis.pdf")
    # clear the positional auto plan of page 1: a REAL change, so the plan is saved
    # (there is nothing to snapshot yet - the JOB had no config.json before this)
    app.use_default_template([1])
    return app


def templates_of(app: controller.AppController) -> list[str | None]:
    config = cfg.load_config(app.project.config_path)
    return [entry["template"] for entry in cfg.page_entries(config, "manualis.pdf")]


def stored_config(app: controller.AppController) -> dict:
    return cfg.load_config(app.project.config_path)


# ------------------------------------------------------------------- snapshotting


def test_a_bulk_edit_snapshots_the_plan_before_the_change(gui):
    before = stored_config(gui)
    snapshots_before = gui.snapshot_count()

    gui.assign_template_to_range([2, 3, 4], "002_intro.ai")

    infos = gui.snapshots()
    assert len(infos) == snapshots_before + 1
    newest = infos[0]
    assert "template piešķire (2-4)" in newest.reason
    assert newest.kind == history.KIND_BULK
    payload = history.load_snapshot(newest.path)
    assert payload["config"] == before  # exactly the plan from before the edit
    # page 4 was on the default template before and carries the new one now
    assert cfg.page_entries(payload["config"], "manualis.pdf")[3]["template"] is None
    assert stored_config(gui) != before


def test_every_mutation_kind_is_recorded(gui):
    gui.assign_template_to_range([3, 4], "002_intro.ai")  # bulk assign
    gui.save_preset("history_tests")
    gui.use_default_template([3, 4])  # bulk again
    gui.apply_preset("history_tests")  # preset
    gui.use_default_template([1])  # make the numbered mapping a real change
    gui.auto_map_by_template_number()  # auto map
    gui.set_enabled([4], False)

    kinds = [info.kind for info in gui.snapshots()]

    assert history.KIND_BULK in kinds
    assert history.KIND_PRESET in kinds
    assert history.KIND_AUTOMAP in kinds
    assert history.KIND_PLAN in kinds  # the enable switch


def test_a_no_op_edit_creates_no_snapshot(gui):
    gui.assign_template_to_range([3], "002_intro.ai")
    before = gui.snapshot_count()

    gui.assign_template_to_range([3], "002_intro.ai")  # the very same assignment
    gui.set_enabled([1, 2, 3, 4], True)  # already enabled

    assert gui.snapshot_count() == before


def test_a_snapshot_that_cannot_be_written_blocks_the_mutation(gui, monkeypatch):
    before = stored_config(gui)

    def broken(*args, **kwargs):
        raise history.HistoryError("nav vietas diskā")

    monkeypatch.setattr(history, "snapshot", broken)

    with pytest.raises(controller.ControllerError) as excinfo:
        gui.assign_template_to_range([3], "002_intro.ai")  # a real change
    assert "kopiju nevar izveidot" in str(excinfo.value)
    assert stored_config(gui) == before  # nothing changed without a snapshot


# --------------------------------------------------------------------------- undo


def test_undo_puts_the_previous_plan_back_and_keeps_the_queue_valid(gui, adapter):
    adapter.script[1] = "error"
    gui.run_selected(["manualis_p001"])
    assert gui.mapping_rows()[0].state == state.ERROR
    before = stored_config(gui)

    gui.assign_template_to_range([3, 4], "002_intro.ai")
    assert templates_of(gui)[2:4] == ["002_intro.ai"] * 2

    result = gui.undo_plan_change()

    assert result is not None
    assert result.recovery is not None
    assert stored_config(gui) == before  # the exact plan from before the edit
    rows = {row.page: row for row in gui.mapping_rows()}
    assert len(rows) == 4
    assert rows[1].state == state.ERROR  # an undo is a plan change, not a state reset
    assert rows[1].attempts == 1
    assert rows[3].template == "MASTER_AI_TEMPLATE.ai"  # the resolved default again


def test_undo_is_itself_undoable(gui):
    gui.assign_template_to_range([3], "002_intro.ai")
    after_edit = stored_config(gui)

    assert gui.undo_plan_change() is not None
    assert stored_config(gui) != after_edit

    assert gui.undo_plan_change() is not None
    assert stored_config(gui) == after_edit


def test_undo_without_history_reports_nothing_to_undo(tmp_path, make_pdf, adapter):
    project = JobProject.open(tmp_path / "EMPTY_JOB")
    make_pdf(project.pdf_dir / "manualis.pdf", pages=2)
    project.template_dir.joinpath("MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nm\n")
    app = controller.AppController(adapter_factory=lambda: adapter)
    app.open_project(project.root)
    app.select_document("manualis.pdf")
    app.auto_assign_templates()  # the first plan: there was nothing to snapshot

    assert app.undo_plan_change() is None


# ------------------------------------------------------------------------ restore


def test_restore_snapshot_puts_an_older_plan_back(gui):
    gui.assign_template_to_range([3], "002_intro.ai")
    older = gui.snapshots()[-1]
    expected = history.load_snapshot(older.path)["config"]
    gui.assign_template_to_range([4], "002_intro.ai")

    result = gui.restore_snapshot(older.name)

    assert result.restored.name == older.name
    assert result.recovery is not None
    assert stored_config(gui) == expected  # exactly the plan of that snapshot
    assert len(gui.snapshots()) >= 3  # the recovery copy is on the list too
    assert len(gui.mapping_rows()) == 4  # the queue was rebuilt from the plan


def test_restore_accepts_a_path_and_rejects_an_unknown_name(gui):
    gui.assign_template_to_range([3], "002_intro.ai")  # so there is a snapshot to restore
    info = gui.snapshots()[0]

    result = gui.restore_snapshot(str(info.path))
    assert result.restored.name == info.name

    with pytest.raises(controller.ControllerError):
        gui.restore_snapshot("2020-01-01_000000.json")


def test_restore_refuses_a_corrupt_snapshot_and_keeps_the_plan(gui):
    gui.assign_template_to_range([3], "002_intro.ai")
    before = stored_config(gui)
    folder = history.history_dir(gui.project)
    folder.mkdir(parents=True, exist_ok=True)
    broken = folder / "broken.json"
    broken.write_text(json.dumps({"version": 1, "config": {"nonsense": True}}), encoding="utf-8")

    with pytest.raises(controller.ControllerError):
        gui.restore_snapshot(broken.name)
    assert stored_config(gui) == before


def test_snapshot_list_survives_a_corrupt_file(gui):
    gui.assign_template_to_range([3], "002_intro.ai")  # a valid snapshot to list
    folder = history.history_dir(gui.project)
    folder.mkdir(parents=True, exist_ok=True)
    broken = folder / "2026-01-01_000000.json"
    broken.write_text("{ not json", encoding="utf-8")

    infos = gui.snapshots()

    assert any(info.name == "2026-01-01_000000.json" for info in infos)
    assert any(info.kind == history.KIND_BULK for info in infos)  # the valid one is intact


def test_restoring_an_old_snapshot_after_a_reopen(gui, job, adapter):
    """The history lives in the JOB, not in the session: a new GUI sees it."""
    gui.assign_template_to_range([3], "002_intro.ai")
    target = gui.snapshots()[0]
    expected = history.load_snapshot(target.path)["config"]
    gui.assign_template_to_range([4], "002_intro.ai")

    second = controller.AppController(adapter_factory=lambda: adapter)
    second.open_project(job.root)
    second.select_document("manualis.pdf")

    assert second.snapshot_count() == gui.snapshot_count()
    result = second.restore_snapshot(target.name)

    assert result.restored.name == target.name
    assert stored_config(second) == expected
    assert second.undo_plan_change() is not None  # still reversible after the reopen

