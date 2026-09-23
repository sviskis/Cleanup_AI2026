"""jsonio: atomic writes, tolerant reads, waiting for a matching result file."""

from __future__ import annotations

import json
import time

from pdf_ai_batch.core import jsonio


def test_write_and_read_json_round_trip(tmp_path):
    target = tmp_path / "nested" / "config.json"
    data = {"version": 1, "pages": [{"page": 1, "template": None}], "text": "Maijs Āā"}
    jsonio.write_json_atomic(target, data)

    assert target.is_file()
    assert jsonio.read_json(target) == data
    assert not (target.parent / "config.json.tmp").exists()


def test_write_json_atomic_replaces_previous_content(tmp_path):
    target = tmp_path / "state.json"
    jsonio.write_json_atomic(target, {"status": "WAITING"})
    jsonio.write_json_atomic(target, {"status": "DONE"})
    assert jsonio.read_json(target) == {"status": "DONE"}


def test_read_json_returns_default_for_missing_or_broken_files(tmp_path):
    assert jsonio.read_json(tmp_path / "missing.json", default={}) == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert jsonio.read_json(broken, default={"fallback": True}) == {"fallback": True}
    empty = tmp_path / "empty.json"
    empty.write_text("   \n", encoding="utf-8")
    assert jsonio.read_json(empty, default=None) is None


def test_delete_if_exists_reports_what_it_did(tmp_path):
    target = tmp_path / "gone.json"
    target.write_text("{}", encoding="utf-8")
    assert jsonio.delete_if_exists(target) is True
    assert jsonio.delete_if_exists(target) is False


def test_read_text_of_missing_file_is_empty(tmp_path):
    assert jsonio.read_text(tmp_path / "nope.txt") == ""


def test_wait_for_json_accepts_a_matching_file(tmp_path):
    target = tmp_path / "current_result.json"
    jsonio.write_json_atomic(target, {"job_id": "a_p001", "run_id": "r1", "status": "OK"})

    data, reason = jsonio.wait_for_json(
        target,
        validator=lambda candidate: candidate.get("job_id") == "a_p001" and candidate.get("run_id") == "r1",
        timeout=1.0,
        poll_interval=0.05,
    )
    assert reason == ""
    assert data is not None and data["status"] == "OK"


def test_wait_for_json_ignores_a_stale_result_and_times_out(tmp_path):
    target = tmp_path / "current_result.json"
    jsonio.write_json_atomic(target, {"job_id": "old_p001", "run_id": "old"})

    seen: list[dict] = []
    data, reason = jsonio.wait_for_json(
        target,
        validator=lambda candidate: candidate.get("job_id") == "a_p001",
        timeout=0.3,
        poll_interval=0.05,
        on_poll=seen.append,
    )
    assert data is None
    assert reason == "timeout"
    assert seen and seen[0]["job_id"] == "old_p001"


def test_wait_for_json_returns_invalid_for_unparsable_content(tmp_path):
    target = tmp_path / "current_result.json"
    target.write_text("{ broken", encoding="utf-8")
    data, reason = jsonio.wait_for_json(target, validator=lambda candidate: True, timeout=0.2, poll_interval=0.05)
    assert data is None
    assert reason == "invalid"


def test_wait_for_json_picks_up_a_result_that_arrives_late(tmp_path):
    target = tmp_path / "current_result.json"
    payload = {"job_id": "a_p002", "run_id": "r2", "status": "OK"}

    def write_later() -> None:
        time.sleep(0.15)
        jsonio.write_json_atomic(target, payload)

    import threading

    thread = threading.Thread(target=write_later)
    thread.start()
    data, reason = jsonio.wait_for_json(
        target,
        validator=lambda candidate: candidate.get("job_id") == "a_p002",
        timeout=2.0,
        poll_interval=0.05,
    )
    thread.join()
    assert reason == ""
    assert data == payload


def test_written_json_is_utf8_without_escapes(tmp_path):
    target = tmp_path / "utf8.json"
    jsonio.write_json_atomic(target, {"name": "Āā Čč"})
    raw = target.read_text(encoding="utf-8")
    assert "Āā" in raw
    assert json.loads(raw)["name"] == "Āā Čč"
