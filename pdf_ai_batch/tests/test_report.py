"""Immutable job report tests (milestone 7).

`core/report.py` turns what the queue already has on disk into historical output:
`JOB/LOG/reports/report_<stamp>.json` (canonical) and `.txt` (human readable). What
matters here: the counts match `state.json`, the duration comes from the pass stamps,
errors and retries are represented, the files are UTF-8 and never overwritten, and
writing a report changes neither the plan nor the state.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from pdf_ai_batch.core import contract, pagejob, report, state
from pdf_ai_batch.core import config as cfg
from pdf_ai_batch.core.project import JobProject
from pdf_ai_batch.core.queue import BatchQueue
from pdf_ai_batch.tests.fakes import FakeIllustrator


def make_queue(tmp_path, make_pdf, *, pages: int = 3) -> tuple[JobProject, BatchQueue]:
    """A JOB with a PDF, a MASTER template, a stored config and a built queue."""
    project = JobProject.open(tmp_path / "REPORT_JOB")
    make_pdf(project.pdf_dir / "manualis.pdf", pages=pages)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nmaster\n")
    queue = BatchQueue.open(project)
    items = queue.build_queue()
    if not project.config_path.exists():
        documents: dict[str, dict] = {}
        for item in items:
            row = documents.setdefault(
                item.pdf_name,
                {"pdf": item.pdf_name, "page_count": 0, "enabled": True, "pages": []},
            )
            row["pages"].append(
                {
                    "page": item.page,
                    "enabled": item.enabled,
                    "template": Path(item.template).name if item.template else None,
                    "layer": item.layer,
                    "output": Path(item.output).name,
                }
            )
        for row in documents.values():
            row["page_count"] = len(row["pages"])
        cfg.save_config(
            project.config_path,
            cfg.new_project_config(
                list(documents.values()),
                {"template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK", "clear_layer": True},
            ),
        )
    return project, queue


# ------------------------------------------------------------------------ duration


def test_duration_text_formats_the_pass_length():
    assert report.duration_text(0) == "0.0s"
    assert report.duration_text(3.4) == "3.4s"
    assert report.duration_text(59) == "59.0s"
    assert report.duration_text(60) == "1m 00s"
    assert report.duration_text(1302) == "21m 42s"
    assert report.duration_text(3909) == "1h 05m 09s"
    assert report.duration_text("nope") == "0s"
    assert report.duration_text(-5) == "0.0s"


# ------------------------------------------------------------------------- building


def test_build_report_counts_match_state_json(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=4)
    adapter = FakeIllustrator(script={2: "error", 3: "skip"}, state_path=project.state_path)
    queue.adapter = adapter
    summary = queue.run_all_enabled()

    job_report = report.build_report(
        project, items=list(queue.document.items), summary=summary, label="RUN ALL ENABLED"
    )

    on_disk = state.load_state(project.state_path)
    assert job_report.count_of(state.DONE) == state.counts_of(on_disk.items)[state.DONE] == 2
    assert job_report.count_of(state.SKIPPED) == 1
    assert job_report.count_of(state.ERROR) == 1
    assert job_report.total == 4
    assert job_report.label == "RUN ALL ENABLED"
    assert job_report.job == "REPORT_JOB"
    assert job_report.root == str(project.root)
    assert job_report.objects_processed == 2 * 3  # two OK pages, three objects each
    assert job_report.run["ok"] == 2
    assert job_report.run["error"] == 1
    assert [row["pdf"] for row in job_report.documents] == ["manualis.pdf"]
    assert job_report.documents[0]["counts"][state.DONE] == 2
    assert job_report.started == summary.started
    assert job_report.finished == summary.finished
    assert job_report.session_id == summary.session_id


def test_build_report_represents_errors_and_retries(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=2)
    adapter = FakeIllustrator(script={1: "error"})
    queue.adapter = adapter
    queue.run_all_enabled()  # page 1 ERROR (attempts 1)
    adapter.script.pop(1)
    queue.retry_errors(run=True)  # page 1 DONE (attempts 2)
    queue.retry_errors(run=False)

    job_report = report.build_report(project, items=list(queue.document.items), label="RETRY")

    assert job_report.count_of(state.ERROR) == 0
    assert job_report.retries == 1  # one extra attempt
    assert job_report.errors == ()
    assert job_report.interrupted == ()


def test_build_report_lists_errors_and_interrupted(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=2)
    queue.adapter = FakeIllustrator(script={1: "error"})
    queue.run_all_enabled()
    queue.document.items[1] = state.mark_interrupted(queue.document.items[1], "pārtraukts")
    queue.save()

    job_report = report.build_report(project, items=list(queue.document.items), label="MIX")

    assert [row["page"] for row in job_report.errors] == [1]
    assert job_report.errors[0]["error_type"] == "PROCESSING"
    assert "testa kļūda" in job_report.errors[0]["error_message"]
    assert job_report.errors[0]["attempts"] == 1
    assert [row["page"] for row in job_report.interrupted] == [2]
    text = job_report.to_text()
    assert "ERRORS:" in text
    assert "INTERRUPTED:" in text
    assert "page 01" in text and "page 02" in text


def test_build_report_without_items_reads_state_json(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=2)
    queue.adapter = FakeIllustrator()
    queue.run_all_enabled()

    job_report = report.build_report(project, label="FROM DISK")

    assert job_report.total == 2
    assert job_report.count_of(state.DONE) == 2
    assert job_report.run == {}  # no summary: the counts are cumulative
    assert job_report.objects_processed == 0
    assert job_report.duration >= 0


# -------------------------------------------------------------------------- writing


def test_write_report_creates_json_and_txt(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=2)
    queue.adapter = FakeIllustrator()
    summary = queue.run_all_enabled()

    job_report = report.build_report(project, items=list(queue.document.items), summary=summary, label="RUN ALL")
    paths = report.write_report(project, job_report)

    assert paths.json.is_file() and paths.txt.is_file()
    assert paths.json.parent == project.log_dir / "reports"
    assert paths.json.name.startswith("report_") and paths.json.suffix == ".json"
    assert paths.txt.read_text(encoding="utf-8").startswith("JOB REPORT\n")

    payload = json.loads(paths.json.read_text(encoding="utf-8"))
    assert payload["version"] == report.REPORT_VERSION
    assert payload["job"] == "REPORT_JOB"
    assert payload["label"] == "RUN ALL"
    assert payload["pages"] == 2
    assert payload["pdfs"] == 1
    assert payload["counts"][state.DONE] == 2
    assert payload["duration_seconds"] >= 0
    assert payload["objects_processed"] == 6
    assert payload["documents"][0]["pdf"] == "manualis.pdf"


def test_report_txt_and_json_are_consistent(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=3)
    queue.adapter = FakeIllustrator(script={3: "error"})
    summary = queue.run_all_enabled()
    job_report = report.build_report(project, items=list(queue.document.items), summary=summary)

    text = job_report.to_text()
    payload = job_report.to_dict()

    for name in state.VALID_STATES:
        line = f"{name + ':':<{len('INTERRUPTED') + 1}} {payload['counts'][name]}"
        assert line in text, name
    assert f"Pages:      {payload['pages']}" in text
    assert f"PDFs:       {payload['pdfs']}" in text
    assert f"Duration: {payload['duration']}" in text
    assert f"Objects processed: {payload['objects_processed']}" in text
    assert f"Retries: {payload['retries']}" in text


def test_reports_are_immutable_never_overwritten(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=2)
    job_report = report.build_report(project, items=list(queue.document.items), label="FIRST")
    when = datetime(2026, 9, 23, 21, 15, 3)

    first = report.write_report(project, job_report, when=when)
    first_txt = first.txt.read_text(encoding="utf-8")
    second_report = report.build_report(project, items=list(queue.document.items), label="SECOND")
    second = report.write_report(project, second_report, when=when)

    assert first.json.name == "report_20260923-211503.json"
    assert second.json.name == "report_20260923-211503-2.json"
    assert second.txt.name == "report_20260923-211503-2.txt"
    assert first.txt.read_text(encoding="utf-8") == first_txt  # untouched
    assert json.loads(first.json.read_text(encoding="utf-8"))["label"] == "FIRST"
    assert json.loads(second.json.read_text(encoding="utf-8"))["label"] == "SECOND"
    assert len(report.list_reports(project)) == 2
    assert [path.name for path in report.list_reports(project)] == [
        "report_20260923-211503-2.json",
        "report_20260923-211503.json",
    ]


def test_report_write_does_not_touch_the_plan_or_state(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=2)
    queue.adapter = FakeIllustrator()
    queue.run_all_enabled()
    before_config = project.config_path.read_bytes()
    before_state = project.state_path.read_bytes()

    job_report = report.build_report(project, items=list(queue.document.items), label="SAFE")
    report.write_report(project, job_report)

    assert project.config_path.read_bytes() == before_config
    assert project.state_path.read_bytes() == before_state
    labels = [
        report.read_report(path).get("label") for path in report.list_reports(project)
    ]
    assert "SAFE" in labels  # written next to the report of the pass, not over it


def test_report_keeps_utf8_job_and_document_names(tmp_path, make_pdf):
    folder = tmp_path / "Realitātes tests LV"
    project = JobProject.open(folder)
    make_pdf(project.pdf_dir / "Māja Āčēģī.pdf", pages=2)
    (project.template_dir / "MASTER_AI_TEMPLATE.ai").write_bytes(b"%PDF-1.5\nm\n")
    queue = BatchQueue.open(project)
    queue.build_queue()
    queue.adapter = FakeIllustrator()
    summary = queue.run_all_enabled()

    job_report = report.build_report(project, items=list(queue.document.items), summary=summary)
    paths = report.write_report(project, job_report)

    payload = json.loads(paths.json.read_text(encoding="utf-8"))
    text = paths.txt.read_text(encoding="utf-8")
    assert payload["job"] == "Realitātes tests LV"
    assert payload["documents"][0]["pdf"] == "Māja Āčēģī.pdf"
    assert "Māja Āčēģī.pdf" in text
    assert "Ã" not in text  # no mojibake


def test_read_report_handles_a_broken_file(tmp_path, make_pdf):
    project, _queue = make_queue(tmp_path, make_pdf, pages=1)
    broken = report.reports_dir(project) / "report_broken.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{ not json", encoding="utf-8")

    assert report.read_report(broken) == {}
    assert report.read_report(tmp_path / "nope.json") == {}
    assert report.list_reports(JobProject.open(tmp_path / "NO_REPORTS_JOB")) == []


# ------------------------------------------------------- queue integration (a pass)


def test_every_pass_writes_a_report(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=3)
    queue.adapter = FakeIllustrator()

    summary = queue.run_all_enabled()

    assert queue.last_report is not None
    assert queue.last_report_paths is not None
    assert queue.last_report_paths.txt.is_file()
    assert queue.last_report_paths.json.is_file()
    assert queue.last_report.label == "RUN ALL ENABLED"
    assert queue.last_report.count_of(state.DONE) == 3
    assert queue.last_report.objects_processed == 9
    payload = json.loads(queue.last_report_paths.json.read_text(encoding="utf-8"))
    assert payload["counts"][state.DONE] == 3
    assert payload["label"] == "RUN ALL ENABLED"


def test_selected_pass_and_empty_pass_write_reports(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=3)
    queue.adapter = FakeIllustrator()

    selected = queue.run_items(["manualis_p001"])
    assert queue.last_report.label == "RUN SELECTED"
    assert selected.counts[state.DONE] == 1
    assert json.loads(queue.last_report_paths.json.read_text(encoding="utf-8"))["label"] == "RUN SELECTED"

    empty = queue.run_all_enabled()  # nothing runnable left except the two WAITING pages
    assert queue.last_report.label == "RUN ALL ENABLED"
    assert empty.counts[state.DONE] == 3

    finished = queue.run_all_enabled()  # now nothing is left at all
    assert finished.counts[state.DONE] == 3
    assert queue.last_report.label == "RUN ALL ENABLED"
    assert len(report.list_reports(project)) == 3  # one report per pass, none lost


def test_report_of_an_aborted_pass_names_the_reason(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=3)
    queue.adapter = FakeIllustrator(script={1: "raise"})

    summary = queue.run_all_enabled()

    assert summary.aborted is True
    assert queue.last_report is not None
    assert queue.last_report.aborted is True
    assert "COM" in queue.last_report.stop_reason or "fake" in queue.last_report.stop_reason
    text = queue.last_report_paths.txt.read_text(encoding="utf-8")
    assert "Pass aborted:" in text


def test_report_counts_stay_in_sync_with_state_json(tmp_path, make_pdf):
    project, queue = make_queue(tmp_path, make_pdf, pages=4)
    adapter = FakeIllustrator(script={2: "error", 4: "skip"})
    queue.adapter = adapter
    queue.run_all_enabled()
    adapter.script.clear()
    queue.retry_errors(run=True)

    payload = json.loads(queue.last_report_paths.json.read_text(encoding="utf-8"))
    on_disk = state.load_state(project.state_path)
    counts = state.counts_of(on_disk.items)
    for name in state.VALID_STATES:
        assert payload["counts"][name] == counts[name], name
    assert payload["counts"][state.DONE] == 3
    assert payload["counts"][state.SKIPPED] == 1
    assert payload["retries"] == 1  # page 2 needed a second attempt
    assert payload["pages"] == 4


def test_report_write_failure_never_breaks_a_pass(tmp_path, make_pdf, monkeypatch):
    project, queue = make_queue(tmp_path, make_pdf, pages=2)
    queue.adapter = FakeIllustrator()

    def broken(project_arg, job_report, *, when=None):
        raise OSError("report folder unavailable")

    monkeypatch.setattr(report, "write_report", broken)

    summary = queue.run_all_enabled()

    assert summary.counts[state.DONE] == 2  # the pass finished normally
    assert queue.last_report_paths is None


