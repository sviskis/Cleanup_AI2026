"""Plan history tests (milestone 8): atomic snapshots, undo, restore.

`core/history.py` records the plan before every meaningful change
(`JOB/CONFIG/history/*.json`) and can put an older plan back. What matters: the
snapshot content is the exact plan, a snapshot is written atomically, an undo returns
the exact previous config, a restore keeps the current plan first (so it is
reversible), retention never eats pinned snapshots, a corrupt snapshot is refused
instead of applied, and neither `state.json` nor an output file is ever touched.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from pdf_ai_batch.core import config as cfg
from pdf_ai_batch.core import history
from pdf_ai_batch.core.project import JobProject


def make_job(tmp_path, make_pdf, name: str = "HISTORY_JOB") -> JobProject:
    project = JobProject.open(tmp_path / name)
    make_pdf(project.pdf_dir / "manualis.pdf", pages=4)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nm\n")
    (project.template_dir / "001_cover.ai").write_bytes(b"%PDF-1.5\nc\n")
    return project


def write_plan(project: JobProject, *, pages: int = 4, first_template: str | None = None) -> dict:
    """A real config.json with one document and `pages` page entries."""
    entries = [
        {
            "page": page,
            "enabled": True,
            "template": first_template if page == 1 else None,
            "layer": "ARTWORK",
            "output": f"manualis__{page:03d}.ai",
        }
        for page in range(1, pages + 1)
    ]
    config = cfg.new_project_config(
        [{"pdf": "manualis.pdf", "page_count": pages, "enabled": True, "pages": entries}],
        {"template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK", "clear_layer": True},
    )
    cfg.save_config(project.config_path, config)
    return cfg.load_config(project.config_path)


def templates_of(project: JobProject) -> list[str | None]:
    config = cfg.load_config(project.config_path)
    return [entry["template"] for entry in cfg.page_entries(config, "manualis.pdf")]


def assign(project: JobProject, page: int, template: str | None, *, reason: str = "testa izmaiņa") -> None:
    """A plan edit through the history hook, exactly like the GUI funnel does it."""
    history.snapshot(project, reason=reason, kind=history.KIND_BULK)
    config = cfg.load_config(project.config_path)
    cfg.document_for(config, "manualis.pdf")["pages"][page - 1]["template"] = template
    cfg.save_config(project.config_path, config)


# ------------------------------------------------------------------------ writing


def test_snapshot_before_a_bulk_mutation_keeps_the_previous_plan(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project, first_template="001_cover.ai")

    assign(project, 3, "001_cover.ai", reason="template piešķire (3)")

    infos = history.list_snapshots(project)
    assert len(infos) == 1
    assert infos[0].reason == "template piešķire (3)"
    assert infos[0].kind == history.KIND_BULK
    assert infos[0].documents == 1 and infos[0].pages == 4
    assert infos[0].path.parent == project.config_dir / "history"
    payload = history.load_snapshot(infos[0].path)
    assert payload["version"] == history.SNAPSHOT_VERSION
    assert payload["job"] == "HISTORY_JOB"
    assert payload["meta"]["pinned"] is False
    assert payload["meta"]["config_version"] == cfg.CONFIG_VERSION
    entries = cfg.page_entries(payload["config"], "manualis.pdf")
    assert entries[2]["template"] is None  # the plan BEFORE the change
    assert templates_of(project)[2] == "001_cover.ai"  # the plan on disk now


def test_snapshot_contains_plan_data_only(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project, first_template="001_cover.ai")

    info = history.snapshot(project, reason="tikai plāns")
    text = info.path.read_text(encoding="utf-8")

    for forbidden in ("state", "attempts", "run_id", "error_type", "last_run_id"):
        assert f'"{forbidden}"' not in text
    assert set(json.loads(text)) == {
        "version",
        "created",
        "kind",
        "reason",
        "job",
        "app_version",
        "meta",
        "config",
    }


def test_snapshot_names_are_timestamps_and_never_reused(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project)
    when = datetime(2026, 9, 23, 20, 15, 3)

    first = history.snapshot(project, reason="pirmais", when=when)
    second = history.snapshot(project, reason="otrais", when=when)

    assert first.name == "2026-09-23_201503.json"
    assert second.name == "2026-09-23_201503-2.json"
    assert json.loads(first.path.read_text(encoding="utf-8"))["reason"] == "pirmais"
    assert [info.name for info in history.list_snapshots(project)] == [
        second.name,
        first.name,
    ]


def test_snapshot_without_a_plan_is_refused(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)

    with pytest.raises(history.HistoryError):
        history.snapshot(project, reason="nav plāna")
    with pytest.raises(history.HistoryError):
        history.snapshot(project, {}, reason="tukšs")
    assert history.count_snapshots(project) == 0


# ---------------------------------------------------------------------- undo


def test_undo_restores_the_exact_previous_config(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project, first_template="001_cover.ai")
    before = project.config_path.read_bytes()

    assign(project, 2, "001_cover.ai")
    assign(project, 3, "001_cover.ai")
    after_both = project.config_path.read_bytes()
    assert templates_of(project)[1:3] == ["001_cover.ai", "001_cover.ai"]

    result = history.undo_last(project)  # one step back: before the LAST change

    assert result is not None
    assert result.restored.reason == "testa izmaiņa"
    assert result.recovery is not None  # the state we came from was kept
    assert templates_of(project)[1:3] == ["001_cover.ai", None]
    assert history.count_snapshots(project) == 3  # two + the recovery copy

    # the undo itself is undoable (the recovery copy is the newest snapshot)
    back = history.undo_last(project)
    assert back is not None
    assert project.config_path.read_bytes() == after_both

    # the FIRST plan is one RESTORE away - that is what the dialog lists
    oldest = history.list_snapshots(project)[-1]
    history.restore_snapshot(project, oldest)
    assert project.config_path.read_bytes() == before


def test_undo_is_itself_reversible(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project)
    assign(project, 1, "001_cover.ai")
    after_edit = project.config_path.read_bytes()

    first = history.undo_last(project)
    assert first is not None and templates_of(project)[0] is None

    second = history.undo_last(project)
    assert second is not None
    assert project.config_path.read_bytes() == after_edit  # back to the edited plan


def test_undo_without_history_returns_none(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project)

    assert history.undo_last(project) is None  # nothing was changed yet
    history.snapshot(project, reason="tāds pats plāns")
    assert history.undo_last(project) is None  # the snapshot equals the current plan


def test_undo_survives_a_broken_snapshot(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project, first_template="001_cover.ai")
    before = project.config_path.read_bytes()
    broken = history.history_dir(project) / "2026-09-23_000000.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{ not json", encoding="utf-8")

    assign(project, 2, "001_cover.ai")
    result = history.undo_last(project)

    assert result is not None
    assert templates_of(project)[1] is None
    assert project.config_path.read_bytes() == before


# ------------------------------------------------------------------- restore


def test_restore_snapshots_the_current_plan_first(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project, first_template="001_cover.ai")
    old = history.snapshot(project, reason="vecais plāns")
    assign(project, 2, "001_cover.ai")
    assign(project, 3, "001_cover.ai")
    edited = project.config_path.read_bytes()

    result = history.restore_snapshot(project, old)

    assert result.restored.name == old.name
    assert result.recovery is not None
    assert result.recovery.kind == history.KIND_RESTORE
    assert "atjaunošanas" in result.recovery.reason
    assert templates_of(project)[1:3] == [None, None]
    payload = history.load_snapshot(result.recovery.path)
    assert cfg.page_entries(payload["config"], "manualis.pdf")[1]["template"] == "001_cover.ai"

    # and the restore itself is undoable
    back = history.undo_last(project)
    assert back is not None
    assert project.config_path.read_bytes() == edited


def test_restore_refuses_a_corrupt_snapshot(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project)
    before = project.config_path.read_bytes()
    broken = history.history_dir(project) / "broken.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text(json.dumps({"version": 1, "config": {"pages": []}}), encoding="utf-8")

    with pytest.raises(history.HistoryError):
        history.restore_snapshot(project, broken)
    with pytest.raises(history.HistoryError):
        history.load_snapshot(broken)
    assert project.config_path.read_bytes() == before  # nothing was written


def test_restore_rejects_a_wrong_version(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project)
    path = history.history_dir(project) / "future.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 99, "config": write_plan(project)}), encoding="utf-8")

    with pytest.raises(history.HistoryError):
        history.load_snapshot(path)
    info = history.info_of(path)
    assert info.version == 99  # still listed, never applied
    assert any(item.name == "future.json" for item in history.list_snapshots(project))


# ------------------------------------------------------------------ retention


def test_retention_keeps_the_newest_and_never_a_pinned_snapshot(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project)
    pinned = history.snapshot(project, reason="pinned kopija", pinned=True)
    for index in range(6):
        history.snapshot(project, reason=f"izmaiņa {index}", keep=3)

    infos = history.list_snapshots(project)
    names = [info.name for info in infos]

    assert len(infos) == 4  # keep=3 plus the pinned one
    assert pinned.name in names
    assert [info.pinned for info in infos].count(True) == 1
    # newest first: the last written snapshot is the first entry
    stamps = [info.path.stat().st_mtime for info in infos]
    assert stamps == sorted(stamps, reverse=True)
    assert history.latest_snapshot(project).reason == "izmaiņa 5"
    assert history.latest_snapshot(project).name != pinned.name


def test_retention_zero_disables_pruning(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project)
    for index in range(5):
        history.snapshot(project, reason=f"izmaiņa {index}", keep=0)

    assert history.count_snapshots(project) == 5


# ------------------------------------------------------------- atomicity + safety


def test_a_failed_snapshot_write_leaves_nothing_behind(tmp_path, make_pdf, monkeypatch):
    project = make_job(tmp_path, make_pdf)
    write_plan(project)
    before = project.config_path.read_bytes()

    def broken(path, data, indent=2):
        raise OSError("disk full")

    monkeypatch.setattr(history.jsonio, "write_json_atomic", broken)

    with pytest.raises(history.HistoryError):
        history.snapshot(project, reason="neizdosies")
    assert history.count_snapshots(project) == 0
    assert project.config_path.read_bytes() == before
    assert not list(history.history_dir(project).glob("*.tmp"))


def test_history_never_touches_state_or_outputs(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project)
    output = project.output_dir / "manualis__001.ai"
    output.write_bytes(b"%PDF-1.5\nfinished\n")
    project.state_path.write_text('{"schema": 1, "items": []}', encoding="utf-8")
    before_state = project.state_path.read_bytes()
    before_output = output.read_bytes()

    assign(project, 1, "001_cover.ai")
    history.undo_last(project)
    history.restore_snapshot(project, history.list_snapshots(project)[0])

    assert project.state_path.read_bytes() == before_state
    assert output.read_bytes() == before_output


# ---------------------------------------------------- v1 migration, UTF-8, summaries


def test_v1_config_is_snapshotted_as_v2(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    legacy = {
        "version": 1,
        "defaults": {"template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK", "clear_layer": True},
        "pdf": "manualis.pdf",
        "page_count": 3,
        "pages": [
            {
                "page": 1,
                "enabled": True,
                "template": "001_cover.ai",
                "layer": "ARTWORK",
                "output": "manualis__001.ai",
            },
            {
                "page": 2,
                "enabled": True,
                "template": None,
                "layer": "ARTWORK",
                "output": "manualis__002.ai",
            },
            {
                "page": 3,
                "enabled": True,
                "template": None,
                "layer": "ARTWORK",
                "output": "manualis__003.ai",
            },
        ],
    }
    project.config_path.write_text(json.dumps(legacy), encoding="utf-8")

    info = history.snapshot(project, reason="v1 plāns")
    payload = history.load_snapshot(info.path)

    assert payload["config"]["version"] == cfg.CONFIG_VERSION
    assert payload["meta"]["config_version"] == cfg.CONFIG_VERSION
    assert info.documents == 1 and info.pages == 3
    assert cfg.page_entries(payload["config"], "manualis.pdf")[0]["template"] == "001_cover.ai"


def test_snapshots_keep_multi_pdf_plans_and_utf8_names(tmp_path, make_pdf):
    project = JobProject.open(tmp_path / "Žurnāls 2026")
    make_pdf(project.pdf_dir / "Māja Āčēģī.pdf", pages=2)
    make_pdf(project.pdf_dir / "Vāks.pdf", pages=2)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nm\n")
    documents = []
    for name, stem in (("Māja Āčēģī.pdf", "maja"), ("Vāks.pdf", "vaks")):
        documents.append(
            {
                "pdf": name,
                "page_count": 2,
                "pages": [
                    {
                        "page": page,
                        "enabled": True,
                        "template": None,
                        "layer": "ARTWORK",
                        "output": f"{stem}__{page:03d}.ai",
                    }
                    for page in (1, 2)
                ],
            }
        )
    cfg.save_config(
        project.config_path,
        cfg.new_project_config(
            documents,
            {"template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK", "clear_layer": True},
        ),
    )

    info = history.snapshot(project, reason="divi PDF")
    payload = history.load_snapshot(info.path)
    restored = history.restore_snapshot(project, info)

    assert info.documents == 2 and info.pages == 4
    assert [block["pdf"] for block in payload["config"]["documents"]] == [
        "Māja Āčēģī.pdf",
        "Vāks.pdf",
    ]
    assert restored.documents == 2 and restored.pages == 4
    text = project.config_path.read_text(encoding="utf-8")
    assert "Māja Āčēģī.pdf" in text
    assert "Ã" not in text  # no mojibake


def test_snapshot_summary_is_human_readable(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf)
    write_plan(project)

    info = history.snapshot(project, reason="preset magazine", kind=history.KIND_PRESET)
    text = info.summary()

    assert "preset magazine" in text
    assert "1 PDF, 4 lapas" in text
    assert info.created in text
    assert history.latest_snapshot(project).name == info.name
    assert history.history_dir(project).name == "history"



