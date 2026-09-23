"""Multi PDF project queue (milestone 4): identity, order, state, reconcile.

One JOB, several PDFs. These tests cover the whole core contract of that change
without Illustrator: stable `pdf_id` + `job_id` identity, the deterministic queue
order (document order, then page ascending), queue state per document, cross
document output collision safety, the version 1 -> 2 config migration, page count
drift, missing PDFs, explicit RECONCILE (added / removed / restored pages) and the
project level runs (RUN CURRENT PDF, RUN ALL, CONTINUE, RETRY ERRORS).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_ai_batch.core import config as cfg
from pdf_ai_batch.core import jsonio, naming, pagejob, queue, state
from pdf_ai_batch.core.project import JobProject
from pdf_ai_batch.tests.fakes import FakeIllustrator

MASTER = "MASTER_AI_TEMPLATE.ai"
MANUALIS = "manualis.pdf"
APPENDIX = "appendix.pdf"


@pytest.fixture()
def project(tmp_path, make_pdf) -> JobProject:
    """A JOB folder with two PDFs (3 pages each) and a MASTER template."""
    job = JobProject.open(tmp_path / "MULTI_JOB")
    make_pdf(job.pdf_dir / MANUALIS, pages=3)
    make_pdf(job.pdf_dir / APPENDIX, pages=3)
    (job.template_dir / MASTER).write_bytes(b"%PDF-1.5\nMASTER template\n")
    return job


def make_queue(project: JobProject, adapter, **kwargs) -> queue.BatchQueue:
    return queue.BatchQueue.open(project, adapter=adapter, **kwargs)


def configure_two_documents(project: JobProject, *, manualis: int = 3, appendix: int = 3) -> dict:
    """Write a version 2 config with an explicit plan for both PDFs (given order)."""
    config = cfg.new_project_config(
        [
            {
                "pdf": MANUALIS,
                "page_count": manualis,
                "pages": [
                    {"page": page, "output": f"manualis__{page:03d}.ai"}
                    for page in range(1, manualis + 1)
                ],
            },
            {
                "pdf": APPENDIX,
                "page_count": appendix,
                "pages": [
                    {"page": page, "output": f"appendix__{page:03d}.ai"}
                    for page in range(1, appendix + 1)
                ],
            },
        ],
        {"template": MASTER},
    )
    cfg.save_config(project.config_path, config)
    return config


def items_of(batch: queue.BatchQueue, pdf: str) -> list[state.QueueItem]:
    return batch.items_of(pdf)


def test_pdf_ids_are_stable_and_derived_from_the_file_name():
    assert naming.pdf_id_for("manualis.pdf") == "manualis"
    assert naming.pdf_id_for(Path("C:/jobs/PDF/manualis.pdf")) == "manualis"
    assert naming.job_id_for("manualis.pdf", 7) == "manualis_p007"
    assert naming.job_id_parts("manualis_p007") == ("manualis", 7)
    assert naming.job_id_parts("nav_id") == ("", 0)
    # the same page number in two PDFs never collides
    assert naming.job_id_for(MANUALIS, 1) != naming.job_id_for(APPENDIX, 1)
    # comparison key folds case and separators (duplicate document detection)
    assert naming.pdf_key_for("Manual (1).pdf") == naming.pdf_key_for("manual_1.pdf")


def test_two_pdfs_with_the_same_page_numbers_get_unique_ids_and_order(project):
    configure_two_documents(project)

    plan = pagejob.plan_project(project)

    assert [doc.pdf_name for doc in plan.documents] == [MANUALIS, APPENDIX]
    assert [job.job_id for job in plan.pages()] == [
        "manualis_p001",
        "manualis_p002",
        "manualis_p003",
        "appendix_p001",
        "appendix_p002",
        "appendix_p003",
    ]
    assert len({job.job_id for job in plan.pages()}) == 6
    assert {Path(job.output).name for job in plan.pages()} == {
        "manualis__001.ai",
        "manualis__002.ai",
        "manualis__003.ai",
        "appendix__001.ai",
        "appendix__002.ai",
        "appendix__003.ai",
    }

    batch = make_queue(project, FakeIllustrator())
    items = batch.build_queue()

    assert [item.job_id for item in items] == [job.job_id for job in plan.pages()]
    assert [item.pdf_id for item in items] == ["manualis"] * 3 + ["appendix"] * 3
    assert [item.page for item in items] == [1, 2, 3, 1, 2, 3]
    assert batch.counts()["pdfs"] == 2
    assert batch.documents() == ["manualis", "appendix"]


def test_page_number_lookup_needs_a_document_in_a_multi_pdf_job(project):
    configure_two_documents(project)
    batch = make_queue(project, FakeIllustrator())
    batch.build_queue()

    assert batch.find("manualis_p001").page == 1
    assert batch.find("appendix_p001").page == 1
    assert batch.find(1, pdf=APPENDIX).job_id == "appendix_p001"

    with pytest.raises(queue.QueueError, match="vairākos dokumentos"):
        batch.find("1")


def test_a_failure_in_one_pdf_does_not_stop_another_pdf(project):
    configure_two_documents(project)
    adapter = FakeIllustrator(script={"manualis_p002": "error"})
    batch = make_queue(project, adapter)

    summary = batch.run_all_enabled()

    assert adapter.pages_run() == [1, 2, 3, 1, 2, 3]  # manualis page 3 and appendix ran
    states = {item.job_id: item.state for item in batch.items()}
    assert states["manualis_p002"] == state.ERROR
    assert states["manualis_p003"] == state.DONE
    assert [states[f"appendix_p{page:03d}"] for page in (1, 2, 3)] == [state.DONE] * 3
    assert summary.counts["DONE"] == 5 and summary.counts["ERROR"] == 1
    assert summary.aborted is False


def test_a_com_failure_aborts_the_whole_project(project):
    configure_two_documents(project)
    adapter = FakeIllustrator(script={"manualis_p002": "raise"})
    batch = make_queue(project, adapter)

    summary = batch.run_all_enabled()

    assert summary.aborted is True
    assert "COM" in summary.stop_reason
    states = {item.job_id: item.state for item in batch.items()}
    assert states["manualis_p002"] == state.ERROR
    assert states["appendix_p001"] == state.WAITING  # the global policy is unchanged


def test_run_documents_only_touches_one_pdf(project):
    configure_two_documents(project)
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)

    summary = batch.run_documents([MANUALIS], rebuild=True)

    assert adapter.pages_run() == [1, 2, 3]
    assert [item.state for item in items_of(batch, MANUALIS)] == [state.DONE] * 3
    assert [item.state for item in items_of(batch, APPENDIX)] == [state.WAITING] * 3
    assert summary.counts["DONE"] == 3 and summary.counts["WAITING"] == 3
    assert summary.documents[1]["pdf"] == APPENDIX
    assert summary.documents[1]["counts"]["WAITING"] == 3


def test_retry_errors_covers_every_document(project):
    configure_two_documents(project)
    adapter = FakeIllustrator(script={"manualis_p002": "error", "appendix_p001": "error"})
    batch = make_queue(project, adapter)
    batch.run_all_enabled()
    assert batch.counts()["ERROR"] == 2

    adapter.script.clear()
    result = batch.retry_errors(run=True)

    assert set(result.touched) == {"manualis_p002", "appendix_p001"}
    assert result.summary is not None
    assert result.summary.counts["ERROR"] == 0
    assert result.summary.counts["DONE"] == 6
    assert adapter.pages_run()[-2:] == [2, 1]


def test_continue_resumes_every_document_after_a_crash(project):
    configure_two_documents(project)
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue()
    batch.run_documents([MANUALIS], limit=1)  # manualis page 1 DONE
    batch.run_documents([APPENDIX], limit=1)  # appendix page 1 DONE

    for job_id in ("manualis_p002", "appendix_p002"):  # the process was killed here
        item = batch.find(job_id)
        batch.document.replace_item(state.mark_running(item, "run-crash"))
    batch.save()

    summary = batch.continue_queue()

    assert summary.recovered == ["manualis_p002", "appendix_p002"]
    assert summary.counts["INTERRUPTED"] == 0
    assert summary.counts["DONE"] == 6
    assert all(item.state == state.DONE for item in batch.items())
    assert adapter.pages_run() == [1, 1, 2, 3, 2, 3]


def test_summary_reports_every_document(project):
    configure_two_documents(project)
    adapter = FakeIllustrator(script={"appendix_p002": "error", "manualis_p003": "skip"})
    batch = make_queue(project, adapter)

    summary = batch.run_all_enabled()
    text = summary.format()

    assert summary.pdfs == 2
    assert summary.pages_total == 6
    assert "PDFs: 2 | Lapas kopā: 6" in text
    assert MANUALIS in text and APPENDIX in text
    rows = {row["pdf"]: row for row in summary.documents}
    assert rows[MANUALIS]["counts"]["DONE"] == 2
    assert rows[MANUALIS]["counts"]["SKIPPED"] == 1
    assert rows[APPENDIX]["counts"]["DONE"] == 2
    assert rows[APPENDIX]["counts"]["ERROR"] == 1
    assert rows[APPENDIX]["current_page"] == 3
    payload = summary.as_dict()
    assert payload["pdfs"] == 2
    assert len(payload["documents"]) == 2
    assert {item["pdf_id"] for item in payload["items"]} == {"manualis", "appendix"}


def test_output_collisions_are_a_validation_error_and_abort_a_run(project):
    # (1) two configured documents that write the same AI: a config level ERROR
    colliding = cfg.new_project_config(
        [
            {"pdf": MANUALIS, "page_count": 3, "pages": [{"page": 1, "output": "same__001.ai"}]},
            {"pdf": APPENDIX, "page_count": 3, "pages": [{"page": 1, "output": "same__001.ai"}]},
        ],
        {"template": MASTER},
    )
    problems = cfg.validate_config(colliding)
    assert any("vairākiem dokumentiem" in problem for problem in problems)

    # (2) a plan that really collides is stopped before the first Illustrator call:
    # appendix maps page 1 onto the automatic name of manualis page 1
    plan_collision = cfg.new_project_config(
        [
            {"pdf": MANUALIS, "page_count": 3},
            {"pdf": APPENDIX, "page_count": 3, "pages": [{"page": 1, "output": "manualis__001.ai"}]},
        ],
        {"template": MASTER},
    )
    assert cfg.validate_config(plan_collision) == []
    cfg.save_config(project.config_path, plan_collision)

    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue()

    assert set(batch.duplicate_outputs()) == {"manualis__001.ai"}
    summary = batch.run_documents([MANUALIS, APPENDIX])

    assert summary.aborted is True
    assert "dublēti output ceļi" in summary.stop_reason
    assert adapter.pages_run() == []  # nothing ran, the collision stopped the pass


def test_a_version_1_job_keeps_working_and_migrates_on_write(project, make_pdf):
    (project.pdf_dir / APPENDIX).unlink()  # a milestone 3 JOB knew only one PDF
    legacy = {
        "version": 1,
        "pdf": MANUALIS,
        "page_count": 3,
        "defaults": {"template": MASTER, "layer": "ARTWORK", "clear_layer": True},
        "pages": [
            {"page": 1, "enabled": True, "template": None, "layer": "ARTWORK", "output": "manualis__001.ai"}
        ],
    }
    jsonio.write_json_atomic(project.config_path, legacy)

    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue()
    batch.run_documents([MANUALIS])

    # the mapping of the version 1 config was used, not a fresh automatic plan
    assert batch.find("manualis_p001").output.endswith("manualis__001.ai")
    assert [item.state for item in items_of(batch, MANUALIS)] == [state.DONE] * 3

    # every item on disk carries a pdf_id, so the next session groups documents
    payload = json.loads(project.state_path.read_text(encoding="utf-8"))
    assert all(item["pdf_id"] == "manualis" for item in payload["items"])

    # reopening the JOB keeps every state and does not duplicate items
    reopened = make_queue(project, FakeIllustrator())
    assert [item.job_id for item in reopened.items()] == [item.job_id for item in batch.items()]
    assert reopened.counts()["DONE"] == 3
    assert reopened.counts()["pdfs"] == 1

    # editing the plan writes version 2 (lossless migration), the file changes shape
    assert jsonio.read_json(project.config_path)["version"] == 1  # not touched yet
    document, report = pagejob.apply_reconcile(project, MANUALIS)
    stored = jsonio.read_json(project.config_path)
    assert stored["version"] == cfg.CONFIG_VERSION
    assert report["kept"] == [1] and report["added"] == [2, 3]
    assert cfg.document_for(stored, MANUALIS)["pages"][0]["output"] == "manualis__001.ai"


def test_a_state_file_without_pdf_id_is_upgraded_silently(project):
    configure_two_documents(project)
    batch = make_queue(project, FakeIllustrator())
    batch.build_queue()

    payload = json.loads(project.state_path.read_text(encoding="utf-8"))
    for item in payload["items"]:
        item.pop("pdf_id")
    project.state_path.write_text(json.dumps(payload), encoding="utf-8")

    reopened = make_queue(project, FakeIllustrator())

    assert reopened.counts()["pdfs"] == 2
    assert reopened.documents() == ["manualis", "appendix"]
    assert {item.document for item in reopened.items()} == {"manualis", "appendix"}
def test_page_count_drift_is_reported_and_never_rewrites_the_mapping(project, make_pdf):
    configure_two_documents(project)
    before = jsonio.read_text(project.config_path)

    make_pdf(project.pdf_dir / APPENDIX, pages=5)  # the operator replaced the PDF
    plan = pagejob.plan_project(project)

    appendix = plan.document(APPENDIX)
    assert appendix.status == pagejob.DOC_STATUS_STALE
    assert appendix.stale is True
    assert appendix.stored_page_count == 3 and appendix.current_page_count == 5
    assert appendix.status_text() == "CONFIG STALE (stored: 3, current: 5)"
    # the stored plan is used, the two new pages are NOT added behind the operator's back
    assert [job.page for job in appendix.pages] == [1, 2, 3]
    assert any("RECONCILE" in warning for warning in appendix.warnings)
    # and config.json is byte identical
    assert jsonio.read_text(project.config_path) == before

    batch = make_queue(project, FakeIllustrator())
    batch.build_queue()
    assert [item.page for item in items_of(batch, APPENDIX)] == [1, 2, 3]

    # the queue itself reports the drift too
    document = cfg.document_for(cfg.load_config(project.config_path), APPENDIX)
    assert document["page_count"] == 3
    assert pagejob.document_matches_pdf(cfg.load_config(project.config_path), APPENDIX, 5) is False


def test_a_shrunk_pdf_does_not_plan_the_pages_that_vanished(project, make_pdf):
    configure_two_documents(project)
    batch = make_queue(project, FakeIllustrator())
    batch.build_queue()
    assert [item.job_id for item in items_of(batch, APPENDIX)] == [
        "appendix_p001",
        "appendix_p002",
        "appendix_p003",
    ]

    make_pdf(project.pdf_dir / APPENDIX, pages=2)
    plan = pagejob.plan_project(project)
    appendix = plan.document(APPENDIX)

    assert appendix.status == pagejob.DOC_STATUS_STALE
    assert [job.page for job in appendix.pages] == [1, 2]
    assert any("vairs nav PDF" in warning for warning in appendix.warnings)

    batch.build_queue()  # page 3 is disabled, never deleted
    item = batch.find("appendix_p003")
    assert item is not None and item.enabled is False


def test_reconcile_adds_pages_and_keeps_done_states(project, make_pdf):
    configure_two_documents(project)
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue()
    batch.run_documents([MANUALIS])
    done = {item.job_id: item.state for item in items_of(batch, MANUALIS)}
    assert set(done.values()) == {state.DONE}

    make_pdf(project.pdf_dir / MANUALIS, pages=5)
    updated, report = pagejob.apply_reconcile(project, MANUALIS)

    assert report["added"] == [4, 5]
    assert report["kept"] == [1, 2, 3]
    assert report["removed"] == []
    assert report["stored"] == 3 and report["current"] == 5
    document = cfg.document_for(updated, MANUALIS)
    assert document["page_count"] == 5
    assert [entry["output"] for entry in document["pages"]] == [
        "manualis__001.ai",
        "manualis__002.ai",
        "manualis__003.ai",
        "manualis__004.ai",
        "manualis__005.ai",
    ]
    assert cfg.validate_config(updated) == []

    # reopened and re-planned: the DONE pages are still DONE, the new pages are WAITING
    reopened = make_queue(project, FakeIllustrator())
    reopened.build_queue()
    items = {item.job_id: item for item in reopened.items()}
    assert {job_id: item.state for job_id, item in items.items() if job_id in done} == done
    assert items["manualis_p004"].state == state.WAITING
    assert items["manualis_p005"].state == state.WAITING
    # and the plan now covers all five pages
    assert [job.page for job in pagejob.plan_project(project).document(MANUALIS).pages] == [1, 2, 3, 4, 5]


def test_reconcile_archives_removed_pages_and_can_restore_them(project, make_pdf):
    configure_two_documents(project)
    batch = make_queue(project, FakeIllustrator())
    batch.build_queue()
    batch.run_documents([APPENDIX])
    assert batch.counts()["DONE"] == 3

    make_pdf(project.pdf_dir / APPENDIX, pages=2)
    updated, report = pagejob.apply_reconcile(project, APPENDIX)

    assert report["removed"] == [3]
    assert report["kept"] == [1, 2]
    document = cfg.document_for(updated, APPENDIX)
    assert [entry["page"] for entry in document["pages"]] == [1, 2]
    assert [entry["page"] for entry in document["removed_pages"]] == [3]
    assert document["removed_pages"][0]["output"] == "appendix__003.ai"
    assert cfg.validate_config(updated) == []  # the archive does not break validation

    batch.build_queue()
    removed_item = batch.find("appendix_p003")
    assert removed_item is not None and removed_item.enabled is False  # state kept, never deleted
    assert removed_item.state == state.DONE

    # the page comes back -> RECONCILE restores the old settings, nothing is added
    make_pdf(project.pdf_dir / APPENDIX, pages=3)
    updated2, report2 = pagejob.apply_reconcile(project, APPENDIX)

    assert report2["restored"] == [3] and report2["added"] == []
    document2 = cfg.document_for(updated2, APPENDIX)
    assert [entry["page"] for entry in document2["pages"]] == [1, 2, 3]
    assert document2["pages"][2]["output"] == "appendix__003.ai"
    assert "removed_pages" not in document2

    batch.build_queue()
    assert batch.find("appendix_p003").enabled is True
    assert batch.find("appendix_p003").state == state.DONE  # the finished page was never redone


def test_a_missing_pdf_keeps_its_plan_and_recovers(project, make_pdf):
    configure_two_documents(project)
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue()
    batch.run_documents([APPENDIX], limit=1)  # appendix page 1 is DONE

    (project.pdf_dir / APPENDIX).unlink()

    plan = pagejob.plan_project(project)
    missing = plan.document(APPENDIX)
    assert missing.status == pagejob.DOC_STATUS_MISSING
    assert missing.missing is True
    assert missing.pages == ()
    assert any(APPENDIX in warning for warning in plan.warnings)
    # the document is still listed, in its place, so the operator sees what happened
    assert [doc.pdf_name for doc in plan.documents] == [MANUALIS, APPENDIX]

    batch.build_queue()

    appendix_items = items_of(batch, APPENDIX)
    assert appendix_items  # nothing was deleted
    assert all(item.enabled is False for item in appendix_items)  # and nothing can run
    assert any(item.state == state.DONE for item in appendix_items)  # history kept

    summary = batch.run_all_enabled()
    assert APPENDIX not in {outcome.pdf_id for outcome in summary.outcomes}
    assert [item.state for item in items_of(batch, MANUALIS)] == [state.DONE] * 3

    # the file comes back: the plan and the states are still valid, no reconcile needed
    make_pdf(project.pdf_dir / APPENDIX, pages=3)
    batch.build_queue()

    assert all(item.enabled for item in items_of(batch, APPENDIX))
    assert batch.find("appendix_p001").state == state.DONE
    assert [batch.find(f"appendix_p{page:03d}").state for page in (2, 3)] == [state.WAITING] * 2
    document = cfg.document_for(cfg.load_config(project.config_path), APPENDIX)
    assert [entry["page"] for entry in document["pages"]] == [1, 2, 3]

    summary2 = batch.run_documents([APPENDIX])
    assert [item.state for item in items_of(batch, APPENDIX)] == [state.DONE] * 3
    assert summary2.counts["DONE"] == 6  # manualis + appendix
    assert summary2.counts["WAITING"] == 0


def test_a_disabled_document_never_runs_but_stays_in_the_queue(project):
    configure_two_documents(project)
    config = cfg.load_config(project.config_path)
    config["documents"][1]["enabled"] = False  # appendix switched off
    cfg.save_config(project.config_path, config)

    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    items = batch.build_queue()

    assert [item.enabled for item in items_of(batch, APPENDIX)] == [False] * 3
    assert batch.counts()["pdfs"] == 2  # both documents are still visible

    summary = batch.run_all_enabled()

    assert adapter.pages_run() == [1, 2, 3]  # only manualis
    assert summary.counts["DONE"] == 3
    assert summary.counts["WAITING"] == 3

    # switching it back on makes it runnable again, without losing anything
    config["documents"][1]["enabled"] = True
    cfg.save_config(project.config_path, config)
    batch.build_queue()
    assert all(item.enabled for item in items_of(batch, APPENDIX))
    batch.run_documents([APPENDIX])
    assert batch.counts()["DONE"] == 6


def test_pages_disabled_in_the_plan_are_skipped_by_every_run(project):
    config = configure_two_documents(project)
    config["documents"][1]["pages"][1]["enabled"] = False  # appendix page 2 off
    cfg.save_config(project.config_path, config)

    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue()
    summary = batch.run_all_enabled()

    states = {item.job_id: item.state for item in batch.items()}
    assert states["appendix_p002"] == state.WAITING  # never touched, still enabled=False
    assert batch.find("appendix_p002").enabled is False
    assert adapter.pages_run() == [1, 2, 3, 1, 3]
    assert summary.counts["DONE"] == 5
