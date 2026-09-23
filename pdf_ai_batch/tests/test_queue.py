"""The batch queue without Illustrator: every rule of milestone 2 is tested here.

The fake adapter (tests/fakes.py) scripts per page results, so the queue logic is
exercised end to end: transitions, the DONE rule, the failure policy, recovery,
retry/continue semantics, atomic state persistence and the summary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_ai_batch.core import queue, state
from pdf_ai_batch.core.contract import contract_path
from pdf_ai_batch.core.project import JobProject
from pdf_ai_batch.tests.fakes import FakeIllustrator

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def project(tmp_path, make_pdf) -> JobProject:
    """A real JOB folder with a 4 page PDF and a MASTER template."""
    job = JobProject.open(tmp_path / "QUEUE_JOB")
    make_pdf(job.pdf_dir / "manual.pdf", pages=4)
    (job.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nMASTER template\n")
    return job


def make_queue(project: JobProject, adapter, **kwargs) -> queue.BatchQueue:
    return queue.BatchQueue.open(project, adapter=adapter, **kwargs)


def on_disk(project: JobProject) -> dict:
    return json.loads(project.state_path.read_text(encoding="utf-8"))


def disk_items(project: JobProject) -> list[dict]:
    return on_disk(project)["items"]


def states_of(batch: queue.BatchQueue) -> list[str]:
    return [item.state for item in batch.items()]


def test_waiting_through_running_to_done(project):
    adapter = FakeIllustrator(state_path=project.state_path)
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1")

    outcome = batch.run_next()

    assert outcome is not None
    assert outcome.state_name == state.DONE
    item = batch.find("manual_p001")
    assert item.state == state.DONE
    assert item.attempts == 1
    assert item.last_run_id == outcome.run_id
    assert item.started and item.finished
    assert Path(item.output).is_file()

    # RUNNING was persisted BEFORE the worker was called ...
    assert adapter.states_seen[0]["items"][0]["state"] == state.RUNNING
    # ... and the terminal state right after the item
    assert disk_items(project)[0]["state"] == state.DONE
    assert not list(project.config_dir.glob("*.tmp"))


def test_worker_error_becomes_error_state(project):
    adapter = FakeIllustrator(script={1: "error"})
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1")

    outcome = batch.run_next()

    assert outcome.state_name == state.ERROR
    item = batch.find("manual_p001")
    assert item.state == state.ERROR
    assert item.error_type == "PROCESSING"
    assert "testa kļūda" in item.error_message
    assert item.attempts == 1
    assert item.runnable is False  # ERROR waits for retry_errors()
    assert disk_items(project)[0]["state"] == state.ERROR


def test_startup_recovery_turns_a_stale_running_item_into_interrupted(project):
    batch = make_queue(project, FakeIllustrator())
    batch.build_queue(pages="1-2")
    # simulate "killed while page 1 was running"
    document = state.load_state(project.state_path)
    document.items[0] = state.mark_running(document.items[0], "run-killed")
    state.save_state(project.state_path, document)

    fresh = make_queue(project, FakeIllustrator())
    item = fresh.find("manual_p001")

    assert item.state == state.INTERRUPTED
    assert item.state != state.DONE
    assert item.runnable is True
    assert item.attempts == 1
    assert disk_items(project)[0]["state"] == state.INTERRUPTED
    assert fresh.document.problems == []


def test_retry_errors_requeues_and_runs_again(project):
    adapter = FakeIllustrator(script={1: "error"})
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1")
    batch.run_next()
    assert batch.find("manual_p001").state == state.ERROR

    adapter.script[1] = None  # the second attempt succeeds
    result = batch.retry_errors(run=True)

    assert result.touched == ["manual_p001"]
    item = batch.find("manual_p001")
    assert item.state == state.DONE
    assert item.attempts == 2  # the attempt is counted on the real run
    assert adapter.pages_run() == [1, 1]
    assert result.summary is not None and result.summary.counts["DONE"] == 1


def test_retry_interrupted_requeues_and_runs_again(project):
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-2")
    for page, wanted in ((1, state.INTERRUPTED), (2, state.DONE)):
        item = state.replace(batch.find(f"manual_p{page:03d}"), state=wanted)
        batch.document.replace_item(item)
    batch.save()

    result = batch.retry_interrupted(run=True)

    assert result.touched == ["manual_p001"]  # only the INTERRUPTED one
    assert batch.find("manual_p001").state == state.DONE
    assert batch.find("manual_p002").state == state.DONE
    assert adapter.pages_run() == [1]


def test_done_items_are_never_rerun(project):
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-2")
    batch.run_all_enabled(build_kwargs={"pages": "1-2"})
    assert len(adapter.calls) == 2
    assert states_of(batch) == [state.DONE, state.DONE]

    resumed = batch.continue_queue()
    again = batch.run_all_enabled(build_kwargs={"pages": "1-2"})

    assert resumed.outcomes == []
    assert again.outcomes == []
    assert len(adapter.calls) == 2  # nothing ran a second time
    assert states_of(batch) == [state.DONE, state.DONE]


def test_skipped_items_are_never_rerun(project):
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1")
    output = Path(batch.find("manual_p001").output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"existing AI from an earlier run")

    outcome = batch.run_next()

    assert outcome.state_name == state.SKIPPED
    assert adapter.calls == []  # Illustrator was never asked
    assert "jau eksistē" in batch.find("manual_p001").error_message

    batch.continue_queue()
    batch.run_all_enabled(build_kwargs={"pages": "1"})
    assert adapter.calls == []
    assert batch.find("manual_p001").state == state.SKIPPED
    assert output.read_bytes() == b"existing AI from an earlier run"


def test_one_error_does_not_stop_the_queue(project):
    adapter = FakeIllustrator(script={2: "error"})
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-3")

    summary = batch.run_all_enabled(build_kwargs={"pages": "1-3"})

    assert states_of(batch) == [state.DONE, state.ERROR, state.DONE]
    assert summary.counts["DONE"] == 2
    assert summary.counts["ERROR"] == 1
    assert adapter.pages_run() == [1, 2, 3]  # page 3 ran after page 2 failed
    assert summary.aborted is False


def test_ok_result_without_an_output_file_is_an_error(project):
    adapter = FakeIllustrator(script={1: "ok_no_output"})
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1")

    outcome = batch.run_next()

    assert outcome.state_name == state.ERROR  # never DONE
    item = batch.find("manual_p001")
    assert item.state == state.ERROR
    assert item.error_type == "OUTPUT_MISSING"
    assert "neeksistē" in item.error_message
    assert not Path(item.output).exists()


def test_ok_result_with_an_empty_output_file_is_an_error(project):
    adapter = FakeIllustrator(script={1: "empty_output"})
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1")

    batch.run_next()

    item = batch.find("manual_p001")
    assert item.state == state.ERROR
    assert item.error_type == "OUTPUT_MISSING"
    assert "tukšs" in item.error_message


def test_state_json_is_written_after_every_item(project):
    adapter = FakeIllustrator(state_path=project.state_path)
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-3")

    seen_on_disk: list[str] = []

    def progress(outcome: queue.RunOutcome) -> None:
        document = on_disk(project)
        seen_on_disk.append(document["items"][outcome.page - 1]["state"])
        assert document["updated"]

    batch.run_all_enabled(progress=progress, build_kwargs={"pages": "1-3"})

    assert seen_on_disk == [state.DONE, state.DONE, state.DONE]
    assert [doc["items"][index]["state"] for index, doc in enumerate(adapter.states_seen)] == [
        state.RUNNING,
        state.RUNNING,
        state.RUNNING,
    ]
    assert states_of(batch) == [state.DONE, state.DONE, state.DONE]


def test_corrupted_state_is_quarantined_and_the_queue_can_be_rebuilt(project):
    project.state_path.write_text("{ not json at all", encoding="utf-8")
    adapter = FakeIllustrator()

    batch = queue.BatchQueue.open(project, adapter=adapter)

    assert batch.items() == []
    assert any("nav nolasāms" in problem for problem in batch.problems())
    backups = list(project.config_dir.glob("state.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{ not json at all"

    batch.build_queue(pages="1")
    assert batch.find("manual_p001").state == state.WAITING
    assert batch.run_next().state_name == state.DONE


def test_duplicate_job_ids_are_reported_and_never_duplicated(project):
    seeded = make_queue(project, FakeIllustrator())
    seeded.build_queue(pages="1-2")
    items = json.loads(project.state_path.read_text(encoding="utf-8"))["items"]
    items.append(dict(items[0]))
    project.state_path.write_text(json.dumps({"version": 1, "items": items}), encoding="utf-8")

    batch = queue.BatchQueue.open(project, adapter=FakeIllustrator(), recover=False)

    assert [item.job_id for item in batch.items()] == ["manual_p001", "manual_p002"]
    assert any("dublēts job_id" in problem for problem in batch.problems())

    batch.build_queue(pages="1-2")  # a rebuild must not duplicate anything either
    assert len(batch.items()) == 2


def test_attempts_count_only_real_runs(project):
    adapter = FakeIllustrator(script={1: "error"})
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1")

    batch.run_next()
    assert batch.find("manual_p001").attempts == 1

    batch.retry_errors()  # ERROR -> WAITING only, no run
    assert batch.find("manual_p001").attempts == 1

    adapter.script[1] = None
    batch.continue_queue()
    assert batch.find("manual_p001").attempts == 2

    batch.reset_item("manual_p001")  # a reset is not an attempt
    assert batch.find("manual_p001").attempts == 2
    assert batch.find("manual_p001").state == state.WAITING


def test_continue_runs_only_waiting_and_interrupted(project):
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-4")
    planned = {
        1: state.DONE,
        2: state.SKIPPED,
        3: state.ERROR,
        4: state.INTERRUPTED,
    }
    for page, wanted in planned.items():
        batch.document.replace_item(
            state.replace(batch.find(f"manual_p{page:03d}"), state=wanted)
        )
    batch.save()

    summary = batch.continue_queue()

    assert adapter.pages_run() == [4]  # DONE, SKIPPED and ERROR were left alone
    assert states_of(batch) == [
        state.DONE,
        state.SKIPPED,
        state.ERROR,
        state.DONE,
    ]
    assert summary.counts["ERROR"] == 1
    assert summary.counts["DONE"] == 2


def test_retry_helpers_touch_only_their_own_state(project):
    batch = make_queue(project, FakeIllustrator())
    batch.build_queue(pages="1-4")
    planned = {
        1: state.ERROR,
        2: state.INTERRUPTED,
        3: state.DONE,
        4: state.SKIPPED,
    }
    for page, wanted in planned.items():
        batch.document.replace_item(
            state.replace(batch.find(f"manual_p{page:03d}"), state=wanted)
        )
    batch.save()

    errors = batch.retry_errors()
    interrupted = batch.retry_interrupted()

    assert errors.touched == ["manual_p001"]
    assert interrupted.touched == ["manual_p002"]
    assert states_of(batch) == [
        state.WAITING,
        state.WAITING,
        state.DONE,
        state.SKIPPED,
    ]


def test_summary_counts_and_run_statistics(project):
    adapter = FakeIllustrator(script={2: "error"})
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-3")

    summary = batch.run_all_enabled(build_kwargs={"pages": "1-3"})

    assert summary.total == 3
    assert summary.enabled == 3
    assert summary.counts == {
        "WAITING": 0,
        "RUNNING": 0,
        "DONE": 2,
        "ERROR": 1,
        "SKIPPED": 0,
        "INTERRUPTED": 0,
        "total": 3,
        "enabled": 3,
        "runnable": 0,
        "pdfs": 1,
    }
    assert summary.pdfs == 1 and summary.pages_total == 3
    assert len(summary.documents) == 1 and summary.documents[0]["pdf"] == "manual.pdf"
    assert summary.run_stats["ok"] == 2
    assert summary.run_stats["error"] == 1
    assert summary.run_stats["objects_copied"] == 6  # 2 successful pages x 3 objects
    assert summary.run_stats["stats"]["crop_objects_deleted"] == 8

    text = summary.format()
    assert "Kopsavilkums:" in text and "DONE=2" in text and "ERROR=1" in text

    payload = summary.as_dict()
    assert payload["counts"]["DONE"] == 2
    assert [item["page"] for item in payload["items"]] == [1, 2, 3]
    assert payload["items"][1]["error_type"] == "PROCESSING"


def test_com_error_aborts_the_pass_and_leaves_the_rest_waiting(project):
    adapter = FakeIllustrator(script={2: "raise"})
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-3")

    summary = batch.run_all_enabled(build_kwargs={"pages": "1-3"})

    assert summary.aborted is True
    assert "COM" in summary.stop_reason
    assert states_of(batch) == [state.DONE, state.ERROR, state.WAITING]
    assert batch.find("manual_p002").error_type == "COM"
    assert adapter.pages_run() == [1, 2]  # page 3 was not attempted


def test_skip_and_reset_item_transitions(project):
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-3")

    skipped = batch.skip_item("manual_p002", "testa izlaišana")
    assert skipped.state == state.SKIPPED
    assert skipped.error_message == "testa izlaišana"
    assert skipped.runnable is False

    batch.continue_queue()
    assert adapter.pages_run() == [1, 3]  # the skipped page is not run

    reset = batch.reset_item(2)  # accepted by page number as well
    assert reset.job_id == "manual_p002"
    assert reset.state == state.WAITING
    assert reset.error_message == ""

    with pytest.raises(queue.QueueError):
        batch.skip_item("manual_p001")  # DONE must be reset first

    assert batch.reset_item("manual__001.ai").state == state.WAITING  # by output name
    with pytest.raises(queue.QueueError):
        batch.find("does_not_exist")
    with pytest.raises(queue.QueueError):
        batch.reset_item("does_not_exist")


def test_build_queue_merges_history_and_disables_pages_outside_the_plan(project):
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-3")
    batch.run_all_enabled(build_kwargs={"pages": "1-3"})
    assert states_of(batch) == [state.DONE, state.DONE, state.DONE]

    batch.build_queue(pages="1-2")  # page 3 is no longer part of the plan

    assert batch.find("manual_p003").enabled is False
    assert batch.find("manual_p003").state == state.DONE  # history is kept
    assert batch.find("manual_p001").state == state.DONE

    batch.build_queue(pages="1-3")  # and it can come back
    assert batch.find("manual_p003").enabled is True
    assert batch.find("manual_p003").attempts == 1

    batch.build_queue(pages="1-2", reset=True)  # explicit reset of the planned pages
    assert batch.find("manual_p001").state == state.WAITING
    assert batch.find("manual_p001").attempts == 0
    assert batch.find("manual_p003").state == state.DONE  # not planned, untouched


def test_status_table_lists_every_page(project):
    adapter = FakeIllustrator(script={2: "error"})
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-3")
    batch.run_all_enabled(build_kwargs={"pages": "1-3"})

    table = batch.status_table()
    lines = table.splitlines()

    assert lines[0].startswith("PDF") and "PAGE" in lines[0] and "STATE" in lines[0]
    assert lines[1].split()[0] == "manual" and lines[1].split()[1] == "001" and state.DONE in lines[1]
    assert lines[2].split()[1] == "002" and state.ERROR in lines[2]
    assert lines[3].split()[1] == "003" and state.DONE in lines[3]
    assert "Kopā:" in table
    assert "PDFs: 1" in table
    assert "manual_p002" in table  # the failing item is explained below the table
    assert batch.status_rows()[0][:2] == ("manual", "001")


def test_overwrite_replaces_an_existing_output(project):
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1", overwrite=True)
    output = Path(batch.find("manual_p001").output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"stale AI from an older run")

    outcome = batch.run_next()

    assert outcome.state_name == state.DONE
    assert output.read_bytes() != b"stale AI from an older run"
    assert adapter.pages_run() == [1]


def test_a_failed_attempt_removes_the_partial_output_so_a_retry_really_runs(project):
    adapter = FakeIllustrator(script={1: "error"})
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1")
    output = Path(batch.find("manual_p001").output)

    batch.run_next()
    assert batch.find("manual_p001").state == state.ERROR
    assert not output.exists()  # the template copy of the failed attempt is gone

    adapter.script[1] = None
    result = batch.retry_errors(run=True)

    assert result.summary is not None
    assert batch.find("manual_p001").state == state.DONE
    assert output.is_file()


def test_running_without_an_adapter_raises_and_changes_nothing(project):
    batch = queue.BatchQueue.open(project, adapter=None)
    batch.build_queue(pages="1")

    with pytest.raises(queue.QueueError):
        batch.run_next()

    assert batch.find("manual_p001").state == state.WAITING


def test_missing_template_is_an_error_and_the_next_page_still_runs(project):
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-3")
    # page 2 points at a template that disappeared -> environment problem for that
    # page only, exactly like a per page template that was renamed
    batch.document.replace_item(
        state.replace(
            batch.find("manual_p002"),
            template=str(project.template_dir / "002_cover.ai"),
        )
    )
    batch.save()

    summary = batch.continue_queue()  # no rebuild: --continue keeps the stored plan

    assert states_of(batch) == [state.DONE, state.ERROR, state.DONE]
    failed = batch.find("manual_p002")
    assert failed.error_type == "OUTPUT_PREP_FAILED"
    assert "template nav atrasts" in failed.error_message
    assert adapter.pages_run() == [1, 3]  # the broken page was never sent to Illustrator
    assert summary.counts["ERROR"] == 1

    # fixing the environment and retrying completes the page
    batch.document.replace_item(
        state.replace(failed, template=contract_path(project.template_dir / "MASTER_AI_TEMPLATE.ai"))
    )
    batch.save()
    result = batch.retry_errors(run=True)

    assert result.summary is not None
    assert states_of(batch) == [state.DONE, state.DONE, state.DONE]


def test_build_queue_repairs_plan_fields(project):
    """A rebuild refreshes template/output/layer/mode from the project plan."""
    batch = make_queue(project, FakeIllustrator())
    batch.build_queue(pages="1-2")
    batch.document.replace_item(
        state.replace(
            batch.find("manual_p002"),
            template="C:/broken/002_cover.ai",
            layer="WRONG",
        )
    )
    batch.save()

    batch.build_queue(pages="1-2")

    repaired = batch.find("manual_p002")
    assert repaired.template == contract_path(project.template_dir / "MASTER_AI_TEMPLATE.ai")
    assert repaired.layer == "ARTWORK"


def test_pass_statistics_count_skipped_and_done_correctly(project):
    """A SKIPPED outcome is a SKIP, not an error (regression: state names differ)."""
    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-3")
    output = Path(batch.find("manual_p002").output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"already there")

    summary = batch.continue_queue()

    assert [outcome.state_name for outcome in summary.outcomes] == [
        state.DONE,
        state.SKIPPED,
        state.DONE,
    ]
    assert summary.run_stats["ok"] == 2
    assert summary.run_stats["skipped"] == 1
    assert summary.run_stats["error"] == 0
    assert "SKIPPED=1 ERROR=0" in summary.format()


def test_a_missing_per_page_template_only_breaks_that_page(project):
    """A lost template must not abort the plan of every other page."""
    from pdf_ai_batch.core import config as cfg

    pages = [
        {"page": page, "enabled": True, "template": "003_pagina.ai" if page == 3 else None,
         "layer": "ARTWORK", "output": f"manual__{page:03d}.ai"}
        for page in (1, 2, 3, 4)
    ]
    document = cfg.new_config(
        "manual.pdf", 4, pages, {"template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK", "clear_layer": True}
    )
    cfg.save_config(project.config_path, document)
    (project.template_dir / "003_pagina.ai").write_bytes(b"%PDF-1.5\npage 3 template\n")

    adapter = FakeIllustrator()
    batch = make_queue(project, adapter)
    batch.build_queue()
    assert batch.find("manual_p003").template.endswith("003_pagina.ai")

    # the per page template disappears -> only page 3 is affected
    (project.template_dir / "003_pagina.ai").unlink()
    batch.build_queue()
    assert batch.find("manual_p003").template.endswith("003_pagina.ai")
    assert batch.find("manual_p001").state == state.WAITING

    summary = batch.run_all_enabled()

    assert states_of(batch)[:4] == [state.DONE, state.DONE, state.ERROR, state.DONE]
    failed = batch.find("manual_p003")
    assert failed.error_type == "OUTPUT_PREP_FAILED"
    assert "template nav atrasts" in failed.error_message
    assert summary.aborted is False
    assert json.loads(project.state_path.read_text(encoding="utf-8"))["items"][2]["state"] == state.ERROR


def test_run_items_runs_only_the_selection_and_never_finished_pages(project):
    adapter = FakeIllustrator(script={2: "error"})
    batch = make_queue(project, adapter)
    batch.build_queue(pages="1-4")

    first = batch.run_items(["manual_p001", "manual__002.ai", 3])
    assert adapter.pages_run() == [1, 2, 3]
    assert states_of(batch)[:3] == [state.DONE, state.ERROR, state.DONE]

    # a second pass over the same selection: DONE/SKIPPED stay, ERROR needs retry
    again = batch.run_items([1, 2, 3])
    assert again.outcomes == []
    assert adapter.pages_run() == [1, 2, 3]

    adapter.script[2] = None
    retried = batch.retry_errors(run=True)
    assert retried.summary is not None
    assert batch.find("manual_p002").state == state.DONE
    assert adapter.pages_run() == [1, 2, 3, 2]

    with pytest.raises(queue.QueueError):
        batch.run_items(["does_not_exist"])
    assert first.counts["DONE"] == 2


def test_reload_picks_up_state_written_by_another_process(project):
    batch = make_queue(project, FakeIllustrator())
    batch.build_queue(pages="1")
    assert batch.find("manual_p001").state == state.WAITING

    # another process (e.g. the CLI) marks the page DONE
    other = make_queue(project, FakeIllustrator())
    other.run_all_enabled(build_kwargs={"pages": "1"})
    assert batch.find("manual_p001").state == state.WAITING  # this view is stale

    batch.reload()
    assert batch.find("manual_p001").state == state.DONE

    # reload never recovers on its own: a RUNNING item stays RUNNING
    other.document.items[0] = state.mark_running(other.document.items[0], "run-x")
    other.save()
    batch.reload()
    assert batch.find("manual_p001").state == state.RUNNING
    batch.reload(recover=True)
    assert batch.find("manual_p001").state == state.INTERRUPTED


def test_recovery_removes_only_the_partial_output_of_the_interrupted_attempt(project):
    """A killed attempt must not leave a file that makes the retry SKIP."""
    import os
    import time as clock

    batch = make_queue(project, FakeIllustrator())
    batch.build_queue(pages="1-2")
    outputs = {item.page: Path(item.output) for item in batch.items()}
    for path in outputs.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"partial AI from the killed attempt")

    # page 1: the output was written by the interrupted attempt (just now)
    # page 2: an old, unrelated output that must survive
    old = outputs[2]
    old_stamp = clock.time() - 3600
    os.utime(old, (old_stamp, old_stamp))

    document = state.load_state(project.state_path)
    for index, page in enumerate((1, 2)):
        document.items[index] = state.mark_running(document.items[index], f"run-crash-{page}")
    state.save_state(project.state_path, document)

    fresh = make_queue(project, FakeIllustrator())
    fresh.recover_running()

    assert fresh.find("manual_p001").state == state.INTERRUPTED
    assert fresh.find("manual_p002").state == state.INTERRUPTED
    assert not outputs[1].exists()  # partial file of the killed attempt removed
    assert old.is_file()  # older file kept (not ours)

    # the retry of page 1 really processes the page again
    result = fresh.retry_interrupted(run=True)
    assert result.summary is not None
    assert fresh.find("manual_p001").state == state.DONE


def test_queue_modules_never_import_com():
    """The ADAPTER RULE: COM only lives in adapters/illustrator.py."""
    for name in ("queue.py", "state.py", "pagejob.py"):
        source = (REPO_ROOT / "pdf_ai_batch" / "core" / name).read_text(encoding="utf-8")
        assert "win32com" not in source
        assert "pythoncom" not in source
        assert "Dispatch" not in source