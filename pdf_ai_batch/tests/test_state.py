"""state.json: the model, atomic persistence, recovery and durability rules.

Nothing here needs Illustrator: the state layer is pure Python on top of the
shared atomic JSON writer.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pdf_ai_batch.core import state

JOB_ROOT = "C:/JOB"


def make_item(page: int = 1, **overrides) -> state.QueueItem:
    """A queued page; `overrides` may set any QueueItem field."""
    item = state.new_item(
        job_id=f"manual_p{page:03d}",
        page=page,
        pdf=f"{JOB_ROOT}/PDF/manual.pdf",
        template=f"{JOB_ROOT}/TEMPLATE/MASTER_AI_TEMPLATE.ai",
        output=f"{JOB_ROOT}/AI_OUT/manual__{page:03d}.ai",
    )
    if overrides:
        item = state.replace(item, **overrides)
    return item


def make_document(*items: state.QueueItem) -> state.StateDocument:
    document = state.StateDocument(job_root=JOB_ROOT, session_id="test-session")
    document.items.extend(items)
    return document


def test_new_item_has_waiting_state_and_timestamps():
    item = make_item(3)
    assert item.state == state.WAITING
    assert item.attempts == 0
    assert item.enabled is True
    assert item.created and item.created == item.updated
    assert item.runnable is True
    assert item.pdf_name == "manual.pdf"


def test_item_round_trips_through_dict():
    item = make_item(2)
    restored, problems = state.QueueItem.from_dict(item.to_dict())
    assert problems == []
    assert restored == item
    assert list(item.to_dict()) == list(state.ITEM_FIELDS)


def test_save_and_load_state_is_atomic_and_utf8(tmp_path):
    path = tmp_path / "CONFIG" / "state.json"
    document = make_document(
        make_item(1, output="C:/JOB/AI_OUT/M\u0101ja \u0100\u010d\u0113\u0123\u012b__001.ai")
    )
    saved = state.save_state(path, document)

    assert saved == path
    assert path.is_file()
    assert not path.with_name("state.json.tmp").exists()  # atomic rename, no leftovers
    raw = path.read_text(encoding="utf-8")
    assert "M\u0101ja \u0100\u010d\u0113\u0123\u012b__001.ai" in raw  # real UTF-8, no escapes
    assert json.loads(raw)["version"] == state.STATE_VERSION

    loaded = state.load_state(path, job_root=JOB_ROOT)
    assert loaded.problems == []
    assert loaded.items == document.items
    assert loaded.job_root == JOB_ROOT


def test_load_missing_state_is_empty_without_problems(tmp_path):
    document = state.load_state(tmp_path / "state.json", job_root=JOB_ROOT)
    assert document.items == []
    assert document.problems == []


def test_load_corrupted_json_reports_the_problem_and_never_raises(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ this is not json", encoding="utf-8")

    document = state.load_state(path, job_root=JOB_ROOT)
    assert document.items == []
    assert len(document.problems) == 1
    assert "nav nolasāms" in document.problems[0]


def test_load_of_a_wrong_shape_reports_problems(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[]", encoding="utf-8")
    assert "nav objekts" in state.load_state(path).problems[0]

    path.write_text(json.dumps({"version": 1, "items": "nope"}), encoding="utf-8")
    assert "items nav saraksts" in state.load_state(path).problems[0]

    path.write_text(json.dumps({"version": 99, "items": []}), encoding="utf-8")
    assert "versija" in state.load_state(path).problems[0]


def test_load_keeps_valid_items_and_reports_broken_ones(tmp_path):
    path = tmp_path / "state.json"
    good = make_item(1).to_dict()
    broken = make_item(2).to_dict()
    broken["pdf"] = "relative/PDF/manual.pdf"
    third = make_item(3).to_dict()
    third["state"] = "NONSENSE"
    path.write_text(json.dumps({"version": 1, "items": [good, broken, third]}), encoding="utf-8")

    document = state.load_state(path, job_root=JOB_ROOT)
    assert [item.page for item in document.items] == [1, 2, 3]
    assert any("pdf nav absolūts" in problem for problem in document.problems)
    assert any("nezināms stāvoklis" in problem for problem in document.problems)
    assert document.items[2].state == state.WAITING  # unknown state is re-queued


def test_load_reports_duplicate_job_ids_and_keeps_the_first(tmp_path):
    path = tmp_path / "state.json"
    first = make_item(1).to_dict()
    duplicate = make_item(1).to_dict()
    duplicate["state"] = state.DONE
    path.write_text(json.dumps({"version": 1, "items": [first, duplicate]}), encoding="utf-8")

    document = state.load_state(path, job_root=JOB_ROOT)
    assert len(document.items) == 1
    assert document.items[0].state == state.WAITING
    assert any("dublēts job_id" in problem for problem in document.problems)


def test_validate_document_finds_duplicates_and_unknown_states():
    duplicated = make_document(make_item(1), make_item(1))
    problems = state.validate_document(duplicated)
    assert any("dublēts job_id" in problem for problem in problems)

    broken = make_document(make_item(2))
    broken.items[0] = state.replace(broken.items[0], state="WHAT")
    assert any("nezināms stāvoklis" in problem for problem in state.validate_document(broken))


def test_recover_running_turns_running_into_interrupted():
    document = make_document(
        make_item(1, state=state.DONE),
        make_item(2, state=state.RUNNING, last_run_id="r-2", attempts=1),
        make_item(3, state=state.WAITING),
    )
    recovered = state.recover_running(document, at=datetime(2026, 9, 23, 18, 0, 0))

    assert recovered == ["manual_p002"]
    item = document.items[1]
    assert item.state == state.INTERRUPTED
    assert item.attempts == 1  # recovery is not an attempt
    assert item.error_type == "INTERRUPTED"
    assert "pārtrūka" in item.error_message
    assert item.runnable is True  # it can be retried / continued
    assert item.finished == "2026-09-23 18:00:00"
    assert [item.state for item in document.items] == [state.DONE, state.INTERRUPTED, state.WAITING]


def test_mark_running_increments_attempts_and_clears_the_previous_error():
    item = make_item(1, error_type="OUTPUT_MISSING", error_message="nav outputa", attempts=1)
    running = state.mark_running(item, "run-2", at=datetime(2026, 9, 23, 18, 1, 0))

    assert running.state == state.RUNNING
    assert running.attempts == 2
    assert running.last_run_id == "run-2"
    assert running.error_type == ""
    assert running.error_message == ""
    assert running.started == "2026-09-23 18:01:00"
    assert running.finished == ""


def test_mark_done_and_mark_error_and_mark_skipped_set_the_timestamps():
    item = state.mark_running(make_item(1), "r1", at=datetime(2026, 9, 23, 18, 0, 0))
    done = state.mark_done(item, "r1", at=datetime(2026, 9, 23, 18, 2, 0))
    assert done.state == state.DONE and done.finished == "2026-09-23 18:02:00"

    failed = state.mark_error(
        item, "r1", "OUTPUT_MISSING", "output fails neeksistē", at=datetime(2026, 9, 23, 18, 3, 0)
    )
    assert failed.state == state.ERROR
    assert failed.error_type == "OUTPUT_MISSING"
    assert failed.error_message == "output fails neeksistē"
    assert failed.finished == "2026-09-23 18:03:00"

    skipped = state.mark_skipped(item, "output jau eksistē")
    assert skipped.state == state.SKIPPED
    assert skipped.error_type == ""
    assert skipped.error_message == "output jau eksistē"


def test_mark_error_truncates_very_long_messages():
    long_message = "x" * (state.MAX_MESSAGE_LENGTH + 500)
    failed = state.mark_error(make_item(1), "r1", "TIMEOUT", long_message)
    assert len(failed.error_message) == state.MAX_MESSAGE_LENGTH
    assert failed.error_message.endswith("...")


def test_mark_waiting_clears_the_error_but_keeps_attempts():
    failed = state.mark_error(make_item(1, attempts=2), "r1", "PROCESSING", "boom")
    waiting = state.mark_waiting(failed)
    assert waiting.state == state.WAITING
    assert waiting.attempts == 2
    assert waiting.error_type == ""
    assert waiting.error_message == ""
    assert waiting.finished == ""
    assert waiting.runnable is True


def test_summary_counts_every_state():
    document = make_document(
        make_item(1, state=state.WAITING),
        make_item(2, state=state.DONE),
        make_item(3, state=state.ERROR),
        make_item(4, state=state.SKIPPED),
        make_item(5, state=state.INTERRUPTED),
        make_item(6, state=state.RUNNING),
        make_item(7, state=state.WAITING, enabled=False),
    )
    counts = state.summary(document)

    assert counts["total"] == 7
    assert counts["enabled"] == 6
    assert counts["WAITING"] == 2
    assert counts["DONE"] == 1
    assert counts["ERROR"] == 1
    assert counts["SKIPPED"] == 1
    assert counts["INTERRUPTED"] == 1
    assert counts["RUNNING"] == 1
    # only enabled WAITING/INTERRUPTED items are picked up by CONTINUE
    assert counts["runnable"] == 2


def test_find_accepts_job_id_page_and_output_name():
    document = make_document(make_item(1), make_item(3, job_id="manual_p003"))
    assert document.find("manual_p003").page == 3
    assert document.find(3).page == 3
    assert document.find("003").page == 3
    assert document.find("manual__001.ai").page == 1
    assert document.find("MANUAL_P001").page == 1
    assert document.find("nope") is None


def test_job_id_for_page_helper_matches_the_naming_rules():
    assert state.job_id_for_page("C:/JOB/PDF/manual.pdf", 7) == "manual_p007"
    assert state.job_id_for_page(Path("C:/JOB/PDF/m\u0101ja.pdf"), 1) == "m\u0101ja_p001"


def test_request_built_from_an_item_carries_absolute_paths():
    request = make_item(2).request("run-1")
    assert request["job_id"] == "manual_p002"
    assert request["pdf"] == f"{JOB_ROOT}/PDF/manual.pdf"
    assert request["output"].endswith("/AI_OUT/manual__002.ai")
    assert request["template_mode"] == "copy"