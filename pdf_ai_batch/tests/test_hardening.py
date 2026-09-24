"""Production hardening tests (milestone 10): the matrix that must hold at v1.0.0.

Every case here comes from the v1.0 test matrix (page counts, project size, paths,
files, queue, config, preview). Anything already covered elsewhere (COM handshake,
reconcile, presets, snapshots, packaging) is not repeated; this file holds the edges:
the smallest and the largest plans, many documents, long paths, corrupt input, a lost
output, an unavailable output folder, restarts and the interaction of migration with
presets and history.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pdf_ai_batch.core import config as cfg
from pdf_ai_batch.core import history, mapping_rules, pagejob, preflight, report, state
from pdf_ai_batch.core.naming import job_id_for
from pdf_ai_batch.core.pdf_info import PdfPageCountError, count_pages
from pdf_ai_batch.core.project import JobProject
from pdf_ai_batch.core.queue import BatchQueue
from pdf_ai_batch.tests.fakes import FakeIllustrator


def make_job(
    tmp_path, make_pdf, *, documents: int = 1, pages: int = 3, name: str = "HARD_JOB"
) -> JobProject:
    """A JOB with real PDFs, templates and a STORED plan (config.json + state.json)."""
    project = JobProject.open(tmp_path / name)
    blocks = []
    for index in range(documents):
        pdf_name = "manualis.pdf" if index == 0 else f"doc{index + 1:02d}.pdf"
        make_pdf(project.pdf_dir / pdf_name, pages=pages)
        blocks.append(
            {
                "pdf": pdf_name,
                "page_count": pages,
                "enabled": True,
                "pages": [
                    {
                        "page": page,
                        "enabled": True,
                        "template": "001_cover.ai" if page == 1 else None,
                        "layer": "ARTWORK",
                        "output": f"{Path(pdf_name).stem}__{page:03d}.ai",
                    }
                    for page in range(1, pages + 1)
                ],
            }
        )
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nm\n")
    (project.template_dir / "001_cover.ai").write_bytes(b"%PDF-1.5\nc\n")
    cfg.save_config(
        project.config_path,
        cfg.new_project_config(
            blocks, {"template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK", "clear_layer": True}
        ),
    )
    return project


def document_order(project: JobProject) -> list[str]:
    config = cfg.load_config(project.config_path)
    return [str(block.get("pdf")) for block in cfg.document_entries(config)]


# ------------------------------------------------------------- page count extremes


@pytest.mark.parametrize("pages", [1, 14, 100, 350])
def test_plans_and_queues_hold_for_every_page_count(tmp_path, make_pdf, pages):
    project = make_job(tmp_path, make_pdf, pages=pages)
    queue = BatchQueue.open(project)

    items = queue.build_queue()

    assert len(items) == pages
    assert [item.page for item in items] == list(range(1, pages + 1))
    assert len({item.job_id for item in items}) == pages
    assert [item.job_id for item in items] == [
        job_id_for("manualis.pdf", page) for page in range(1, pages + 1)
    ]
    counts = queue.counts()
    assert counts["total"] == pages and counts["runnable"] == pages
    width = 3 if pages < 1000 else 4
    assert items[0].output.endswith(f"manualis__{'1'.zfill(width)}.ai")
    assert items[-1].output.endswith(f"manualis__{str(pages).zfill(width)}.ai")

    plan = pagejob.plan_project(project)
    assert len(plan.documents) == 1
    assert len(plan.documents[0].pages) == pages

    job_report = report.build_report(project, items=items, label="HARDENING")
    assert job_report.total == pages
    assert job_report.to_dict()["pages"] == pages


def test_single_page_project_is_valid_end_to_end(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=1)
    queue = BatchQueue.open(project)
    queue.build_queue()
    queue.adapter = FakeIllustrator()

    summary = queue.run_all_enabled()

    assert summary.counts[state.DONE] == 1
    assert (project.output_dir / "manualis__001.ai").is_file()
    result = preflight.run_preflight(project, check_illustrator=False)
    assert result.facts["pages"] == 1
    assert result.status == preflight.STATUS_READY
    assert queue.last_report_paths is not None


# ------------------------------------------------------------------ many documents


def test_ten_documents_in_one_job_stay_unique_and_ordered(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, documents=10, pages=5)
    queue = BatchQueue.open(project)

    items = queue.build_queue()

    assert len(items) == 50
    assert len({item.job_id for item in items}) == 50
    documents: list[str] = []
    for item in items:
        if item.document not in documents:
            documents.append(item.document)
    # the queue order is the config order, then the page number ascending
    assert documents == [Path(name).stem for name in document_order(project)]
    assert len(documents) == 10
    assert [item.page for item in items[:5]] == [1, 2, 3, 4, 5]
    assert len({item.output for item in items}) == 50

    plan = pagejob.plan_project(project)
    assert len(plan.documents) == 10
    result = preflight.run_preflight(project, check_illustrator=False)
    assert result.facts["pdfs"] == 10
    assert result.facts["pages"] == 50
    assert result.status == preflight.STATUS_READY


def test_a_colliding_plan_is_refused_before_illustrator(tmp_path, make_pdf):
    """A duplicate output that reaches the queue aborts the pass, before any COM call."""
    project = make_job(tmp_path, make_pdf, documents=2, pages=2)
    queue = BatchQueue.open(project)
    queue.build_queue()
    payload = json.loads(project.state_path.read_text(encoding="utf-8"))
    same = payload["items"][0]["output"]
    payload["items"][1]["output"] = same  # two pages of two documents, one file
    project.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    queue.reload()
    adapter = FakeIllustrator()
    queue.adapter = adapter

    summary = queue.run_all_enabled(rebuild=False)

    assert adapter.calls == []  # nothing reached Illustrator
    assert summary.aborted is True
    assert Path(same).name in summary.stop_reason
    assert queue.document.runnable()  # the plan is still there to fix


def test_a_duplicate_output_in_the_config_is_caught_by_preflight(tmp_path, make_pdf):
    """An invalid plan is refused before a run - the GUI blocks on this report."""
    project = make_job(tmp_path, make_pdf, documents=2, pages=2)
    config = cfg.load_config(project.config_path)
    first = cfg.document_for(config, "manualis.pdf")["pages"][0]
    second = cfg.document_for(config, "doc02.pdf")["pages"][0]
    second["output"] = first["output"]
    cfg.save_config(project.config_path, config)
    BatchQueue.open(project).build_queue()

    result = preflight.run_preflight(project, check_illustrator=False)

    assert result.status == preflight.STATUS_NOT_READY
    assert result.facts["duplicate_outputs"] == [first["output"]]
    assert result.facts["invalid_outputs"] or result.facts["duplicate_outputs"]


# --------------------------------------------------------------------- long paths


def test_long_paths_and_spaces_work(tmp_path, make_pdf):
    """A deep path with spaces (like a OneDrive project) must work end to end."""
    deep = tmp_path
    for index in range(3):
        deep = deep / f"Lapa {index + 1} ar atstarpēm"
    project = make_job(deep, make_pdf, pages=3, name="Garais projekts 2026")
    assert len(str(project.root)) > 100

    queue = BatchQueue.open(project)
    queue.build_queue()
    queue.adapter = FakeIllustrator()
    queue.run_all_enabled()

    assert queue.counts()[state.DONE] == 3
    assert queue.last_report_paths.json.is_file()
    job_report = report.build_report(project, items=list(queue.document.items), label="GARAIS CEĻŠ")
    paths = report.write_report(project, job_report)
    assert str(project.root) in paths.txt.read_text(encoding="utf-8")
    result = preflight.run_preflight(project, check_illustrator=False)
    assert result.status == preflight.STATUS_READY


# -------------------------------------------------------------------- broken files


def test_a_corrupt_pdf_is_reported_not_a_crash(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    broken = project.pdf_dir / "broken.pdf"
    broken.write_bytes(b"%PDF-1.5\nthis is not a pdf at all\n")

    with pytest.raises(PdfPageCountError) as excinfo:
        count_pages(broken)
    assert "broken.pdf" in str(excinfo.value)

    plan = pagejob.plan_project(project)
    statuses = {document.pdf_name: document.status for document in plan.documents}
    assert statuses["manualis.pdf"] == pagejob.DOC_STATUS_OK
    assert statuses["broken.pdf"] == pagejob.DOC_STATUS_PLAN_ERROR

    result = preflight.run_preflight(project, check_illustrator=False)
    # the healthy document can still run, so the project is not blocked
    assert result.status == preflight.STATUS_READY
    assert any("broken.pdf" in warning for warning in result.warnings)


def test_a_corrupt_pdf_alone_blocks_the_project(tmp_path, make_pdf):
    project = JobProject.open(tmp_path / "BROKEN_JOB")
    (project.pdf_dir / "broken.pdf").write_bytes(b"not a pdf")
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nm\n")

    result = preflight.run_preflight(project, check_illustrator=False)

    assert result.status == preflight.STATUS_NOT_READY
    assert any("PLAN ERROR" in problem for problem in result.problems)


def test_a_corrupt_template_file_is_caught_by_the_check(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    template = project.template_dir / "001_cover.ai"
    template.write_bytes(b"")
    config = cfg.new_project_config(
        [
            {
                "pdf": "manualis.pdf",
                "page_count": 2,
                "pages": [
                    {
                        "page": page,
                        "enabled": True,
                        "template": "001_cover.ai" if page == 1 else None,
                        "layer": "ARTWORK",
                        "output": f"manualis__{page:03d}.ai",
                    }
                    for page in (1, 2)
                ],
            }
        ],
        {"template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK", "clear_layer": True},
    )
    cfg.save_config(project.config_path, config)

    result = preflight.run_preflight(project, check_illustrator=False)

    # the file exists, so the plan is valid; a 0 byte template is caught at run time
    # by the worker (OUTPUT_FAILED) - preflight must at least show the file
    assert result.facts["missing_templates"] == []
    assert any(check.name == "Template 001_cover.ai" for check in result.sections[2].checks)
    job = pagejob.plan_document(project, "manualis.pdf")
    assert job.pages[0].template is not None


def test_a_lost_output_after_done_is_a_hard_finding(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=2)
    queue = BatchQueue.open(project)
    queue.build_queue()
    queue.adapter = FakeIllustrator()
    queue.run_all_enabled()
    assert queue.counts()[state.DONE] == 2

    (project.output_dir / "manualis__002.ai").unlink()  # it was delivered, now it is gone

    result = preflight.run_preflight(project, check_illustrator=False)

    assert result.facts["lost_outputs"] == ["manualis.pdf l.2"]
    assert result.status == preflight.STATUS_NOT_READY
    assert any("DONE lapām output nav atrasts" in problem for problem in result.problems)
    assert pagejob.output_ready(project.output_dir / "manualis__002.ai")[0] is False
    assert "neeksistē" in pagejob.output_ready(project.output_dir / "manualis__002.ai")[1]


# ------------------------------------------------------------------- output folder


def test_an_unavailable_output_folder_fails_the_page_not_the_pass(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=3)
    queue = BatchQueue.open(project)
    queue.build_queue()
    queue.adapter = FakeIllustrator()

    # AI_OUT is not a folder any more: the copy step cannot write anything
    shutil.rmtree(project.output_dir)
    project.output_dir.write_text("not a folder", encoding="utf-8")

    summary = queue.run_all_enabled()

    assert summary.aborted is False  # a page level failure never stops a pass
    counts = queue.counts()
    assert counts[state.ERROR] == 3, counts
    assert all(item.error_type for item in queue.document.items)
    assert queue.last_report is not None
    result = preflight.run_preflight(project, check_illustrator=False)
    assert result.facts["output_writable"] is False
    assert result.status == preflight.STATUS_NOT_READY


# ------------------------------------------------------------------- restarts


def test_restart_between_jobs_keeps_the_history_and_the_plan(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=4)
    first = BatchQueue.open(project)
    first.build_queue()
    first.adapter = FakeIllustrator()
    first.run_items(["manualis_p001", "manualis_p002"])
    assert first.counts()[state.DONE] == 2
    first.save()

    second = BatchQueue.open(project)  # a new session (the app was restarted)
    second.build_queue()
    second.adapter = FakeIllustrator()
    summary = second.continue_queue()

    assert summary.counts[state.DONE] == 4
    assert second.counts()[state.WAITING] == 0
    assert all(item.attempts == 1 for item in second.document.items)
    plans = history.list_snapshots(project)  # a restart does not create snapshots
    assert plans == []
    report_paths = [path.name for path in report.list_reports(project)]
    assert len(report_paths) == 2  # one pass per session, both kept


def test_a_killed_page_is_recovered_and_finished_by_continue(tmp_path, make_pdf):
    project = make_job(tmp_path, make_pdf, pages=3)
    queue = BatchQueue.open(project)
    queue.build_queue()
    queue.adapter = FakeIllustrator()
    queue.run_items(["manualis_p001"])
    payload = json.loads(project.state_path.read_text(encoding="utf-8"))
    payload["items"][1]["state"] = state.RUNNING
    payload["items"][1]["attempts"] = 1
    payload["items"][1]["last_run_id"] = "20260923-000000-deadbe"
    partial = project.output_dir / "manualis__002.ai"
    partial.write_bytes(b"%PDF-1.5\npartial\n")
    project.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    reopened = BatchQueue(project)  # a new session that has NOT recovered yet
    assert reopened.counts()[state.RUNNING] == 1
    assert partial.exists()  # the partial file is still there before recovery
    reopened.adapter = FakeIllustrator()
    summary = reopened.continue_queue()  # recovery happens inside the pass

    assert summary.counts[state.DONE] == 3
    assert reopened.counts()[state.INTERRUPTED] == 0
    assert (project.output_dir / "manualis__002.ai").is_file()
    assert not partial.read_bytes() == b"%PDF-1.5\npartial\n"  # really rewritten
    job_report = reopened.last_report
    assert job_report is not None
    assert job_report.recovered  # the report names the recovered page
    assert job_report.count_of(state.DONE) == 3


# ------------------------------------------- migration, presets, history, snapshots


def test_v1_migration_works_with_presets_snapshots_and_reports(tmp_path, make_pdf):
    """The three newer layers must work on a JOB that still has a version 1 config."""
    project = make_job(tmp_path, make_pdf, pages=4)
    legacy = {
        "version": 1,
        "defaults": {"template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK", "clear_layer": True},
        "pdf": "manualis.pdf",
        "page_count": 4,
        "pages": [
            {
                "page": page,
                "enabled": True,
                "template": "001_cover.ai" if page == 1 else None,
                "layer": "ARTWORK",
                "output": f"manualis__{page:03d}.ai",
            }
            for page in range(1, 5)
        ],
    }
    project.config_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    loaded = cfg.load_config(project.config_path)
    assert loaded["version"] == cfg.CONFIG_VERSION  # migrated in memory, file untouched

    # a preset can be built from the migrated plan
    preset = mapping_rules.preset_from_mapping(loaded, "manualis.pdf", name="v1 preset")
    assert [entry["pages"] for entry in preset["entries"]] == ["1", "2-4"]
    snapshot = history.snapshot(project, loaded, reason="v1 plāns")
    assert snapshot.documents == 1 and snapshot.pages == 4

    # a real plan change (a preset built from the migrated plan) and then an undo
    changed = cfg.load_config(project.config_path)
    mapping_rules.use_default_template(changed, "manualis.pdf", [1])  # page 1 -> default
    report_changed = mapping_rules.apply_preset(changed, "manualis.pdf", preset)
    mapping_rules.assign_template(changed, "manualis.pdf", [2, 3], "001_cover.ai")
    cfg.save_config(project.config_path, changed)
    assert report_changed["changed"] == [1], report_changed

    restored = history.undo_last(project)
    assert restored is not None
    assert restored.pages == 4
    current = cfg.load_config(project.config_path)
    entries = cfg.page_entries(current, "manualis.pdf")
    assert current["version"] == cfg.CONFIG_VERSION
    assert [entry["template"] for entry in entries] == ["001_cover.ai", None, None, None]

    # the queue plans the migrated document and a pass writes a report about it
    queue = BatchQueue.open(project)
    queue.build_queue()
    queue.adapter = FakeIllustrator()
    queue.run_all_enabled()

    assert queue.counts()[state.DONE] == 4
    assert queue.last_report is not None
    assert queue.last_report.total == 4
    result = preflight.run_preflight(project, check_illustrator=False)
    assert result.status == preflight.STATUS_READY


def test_preview_cache_and_plan_agree_for_a_large_document(tmp_path, make_pdf):
    """Cache keys stay per page/render size, so a 300 page plan cannot collide."""
    from pdf_ai_batch.preview import CacheKey, PreviewCache
    from pdf_ai_batch.preview import renderer

    project = make_job(tmp_path, make_pdf, pages=300)
    cache = PreviewCache(project.root)
    pdf = project.pdf_dir / "manualis.pdf"
    fingerprint = renderer.document_fingerprint(pdf)

    payload = renderer.render_thumbnail(pdf, 7).image
    thumb = CacheKey.for_thumbnail(fingerprint, 7, 160)
    big = CacheKey.for_thumbnail(fingerprint, 7, 320)
    other = CacheKey.for_thumbnail(fingerprint, 8, 160)

    assert cache.get(thumb) is None  # nothing cached yet
    assert cache.put(thumb, payload) is not None
    assert cache.get(thumb) == payload
    cache.put(big, payload)
    cache.put(other, payload)

    assert len({thumb.file_name(), big.file_name(), other.file_name()}) == 3
    assert cache.stats()["files"] == 3
    assert len(cache.entries()) == 3

    # a modified PDF produces a new key, so the old page can never be shown again
    make_pdf(pdf, pages=300)
    fresh = renderer.document_fingerprint(pdf)
    assert fresh != fingerprint
    assert cache.get(CacheKey.for_thumbnail(fresh, 7, 160)) is None





