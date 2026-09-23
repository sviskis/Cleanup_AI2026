"""Adapter handshake tests - the Python side of the contract, without Illustrator.

A fake "app" stands in for Illustrator: its DoJavaScriptFile writes a result file
exactly like jsx/worker.jsx does. That lets these behaviours be verified without
COM:

  * a stale result is deleted before every job
  * the request is written atomically (no temp file left behind, valid JSON)
  * a result is accepted only when job_id AND run_id match
  * a mismatching result is rejected and counted, and the run times out
  * a late result is still picked up
  * the worker log tail is included in timeout messages
  * COM problems are reported as ERROR results, not exceptions
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from pdf_ai_batch.adapters.illustrator import IllustratorAdapter, IllustratorError
from pdf_ai_batch.core import jsonio
from pdf_ai_batch.core.contract import REQUEST_SCHEMA, build_request


class FakeApp:
    """Minimal stand-in for the Illustrator COM object."""

    def __init__(self, worker, result_writer=None, name="Fake Illustrator", version="28.0.0"):
        self._worker = worker
        self._result_writer = result_writer
        self.Name = name
        self.Version = version
        self.BuildNumber = "1"
        self.Documents: list = []
        self.calls: list[str] = []

    def DoJavaScriptFile(self, path: str) -> None:
        self.calls.append(path)
        if self._result_writer is not None:
            self._result_writer()


def make_request(runtime_dir: Path, job_id: str = "manual_p017", run_id: str = "run-1") -> dict:
    return build_request(
        run_id=run_id,
        job_id=job_id,
        pdf=str(runtime_dir / "manual.pdf"),
        page=17,
        template=str(runtime_dir / "017.ai"),
        output=str(runtime_dir / "manual__017.ai"),
    )


def ok_result(job_id: str, run_id: str, out: Path, objects: int = 241) -> dict:
    return {
        "schema": "pdf_ai_batch/job_result/v1",
        "job_id": job_id,
        "run_id": run_id,
        "status": "OK",
        "page": 17,
        "output": str(out),
        "objects_copied": objects,
        "stats": {
            "safe_groups_ungrouped": 19,
            "risky_groups_preserved": 0,
            "vector_masks_released": 3,
            "risky_masks_preserved": 1,
            "mask_paths_deleted": 1,
            "crop_perimeters_deleted": 6,
            "short_crop_marks_deleted": 2,
            "crop_objects_deleted": 8,
        },
    }


@pytest.fixture()
def adapter(fake_repo) -> IllustratorAdapter:
    return IllustratorAdapter(
        worker_jsx=fake_repo / "jsx" / "worker.jsx",
        runtime_dir=fake_repo / "runtime",
        timeout=2.0,
        poll_interval=0.05,
    )


def test_prepare_handoff_creates_runtime_dir_and_removes_stale_result(adapter):
    adapter.runtime_dir.rmdir()
    stale = adapter.result_path
    adapter.runtime_dir.mkdir(parents=True)
    jsonio.write_json_atomic(stale, {"job_id": "old", "run_id": "old"})

    adapter.prepare_handoff()

    assert adapter.runtime_dir.is_dir()
    assert not adapter.result_path.exists()


def test_write_request_is_valid_json_and_atomic(adapter):
    request = make_request(adapter.runtime_dir)
    path = adapter.write_request(request)

    assert path == adapter.request_path
    assert json.loads(path.read_text(encoding="utf-8")) == request
    assert request["schema"] == REQUEST_SCHEMA
    assert not list(adapter.runtime_dir.glob("*.tmp"))


def test_write_request_rejects_invalid_request(adapter):
    with pytest.raises(IllustratorError):
        adapter.write_request({"job_id": "x"})


def test_run_job_accepts_a_matching_result(adapter):
    out = adapter.runtime_dir / "manual__017.ai"
    out.write_bytes(b"AI")

    def writer() -> None:
        jsonio.write_json_atomic(adapter.result_path, ok_result("manual_p017", "run-1", out))

    adapter._app = FakeApp(adapter.worker_jsx, writer)
    result = adapter.run_job(make_request(adapter.runtime_dir))

    assert result.ok
    assert result.objects_copied == 241
    assert result.stat("crop_objects_deleted") == 8
    assert adapter._app.calls == [str(adapter.worker_jsx)]
    assert adapter.last_handshake is not None
    assert adapter.last_handshake.rejected_results == 0
    assert adapter.last_handshake.waited_seconds >= 0


def test_run_job_deletes_the_stale_result_before_invoking_the_worker(adapter):
    """A stale result must never be able to masquerade as this run's answer."""
    out = adapter.runtime_dir / "manual__017.ai"
    out.write_bytes(b"AI")
    jsonio.write_json_atomic(adapter.result_path, ok_result("other_job", "old-run", out))

    adapter.timeout = 0.3
    adapter._app = FakeApp(adapter.worker_jsx, None)  # never writes a new result
    result = adapter.run_job(make_request(adapter.runtime_dir))

    assert result.failed
    assert result.error_type == "TIMEOUT"
    assert adapter.last_handshake is not None
    # the stale file was removed at handoff, so it was never "rejected"
    assert adapter.last_handshake.rejected_results == 0
    assert not adapter.result_path.exists()


def test_run_job_rejects_a_foreign_result_that_appears_during_the_wait(adapter, caplog):
    out = adapter.runtime_dir / "manual__017.ai"
    out.write_bytes(b"AI")

    def writer() -> None:
        jsonio.write_json_atomic(adapter.result_path, ok_result("somebody_else", "other-run", out))

    adapter.timeout = 0.4
    adapter._app = FakeApp(adapter.worker_jsx, writer)
    with caplog.at_level("WARNING", logger="pdf_ai_batch.illustrator"):
        result = adapter.run_job(make_request(adapter.runtime_dir))

    assert result.failed
    assert result.error_type == "TIMEOUT"
    assert adapter.last_handshake.rejected_results >= 1
    # the rejection is traceable in the log, which is what diagnostics need
    assert any("Noraidu rezultātu" in record.getMessage() for record in caplog.records)


def test_run_job_rejects_a_result_with_the_wrong_run_id(adapter):
    out = adapter.runtime_dir / "manual__017.ai"
    out.write_bytes(b"AI")

    def writer() -> None:
        jsonio.write_json_atomic(adapter.result_path, ok_result("manual_p017", "different-run", out))

    adapter._app = FakeApp(adapter.worker_jsx, writer)
    result = adapter.run_job(make_request(adapter.runtime_dir, run_id="run-1"))

    assert result.failed
    assert result.error_type == "TIMEOUT"
    assert adapter.last_handshake.rejected_results >= 1


def test_run_job_picks_up_a_late_result(adapter):
    out = adapter.runtime_dir / "manual__017.ai"
    out.write_bytes(b"AI")

    def writer() -> None:
        time.sleep(0.2)
        jsonio.write_json_atomic(adapter.result_path, ok_result("manual_p017", "run-1", out))

    adapter._app = FakeApp(adapter.worker_jsx, None)
    thread = threading.Thread(target=writer)
    thread.start()
    result = adapter.run_job(make_request(adapter.runtime_dir))
    thread.join()

    assert result.ok
    assert result.objects_copied == 241


def test_run_job_propagates_a_worker_error_result(adapter):
    def writer() -> None:
        jsonio.write_json_atomic(
            adapter.result_path,
            {
                "schema": "pdf_ai_batch/job_result/v1",
                "job_id": "manual_p017",
                "run_id": "run-1",
                "status": "ERROR",
                "page": 17,
                "message": "Neizdevās atvērt PDF",
                "error_type": "OPEN_FAILED",
            },
        )

    adapter._app = FakeApp(adapter.worker_jsx, writer)
    result = adapter.run_job(make_request(adapter.runtime_dir))

    assert result.failed
    assert result.error_type == "OPEN_FAILED"
    assert "atvērt" in result.message


def test_run_job_reports_com_problems_as_a_result(adapter):
    class BrokenApp(FakeApp):
        def DoJavaScriptFile(self, path: str) -> None:
            raise RuntimeError("COM kļūda no fake")

    adapter._app = BrokenApp(adapter.worker_jsx)
    result = adapter.run_job(make_request(adapter.runtime_dir))

    assert result.failed
    assert result.error_type == "COM"
    assert "COM" in result.message


def test_invoke_worker_requires_the_worker_file(adapter, tmp_path):
    adapter.worker_jsx = tmp_path / "missing.jsx"
    adapter._app = FakeApp(adapter.worker_jsx)
    with pytest.raises(IllustratorError):
        adapter.invoke_worker()


def test_health_check_reports_the_environment(adapter):
    report = adapter.health_check()
    assert report["worker_jsx_exists"] is True
    assert report["cleanup_jsx_exists"] is True
    assert report["runtime_writable"] is True
    assert report["com_attached"] is False
    assert report["ok"] is False

    adapter._app = FakeApp(adapter.worker_jsx)
    assert adapter.health_check()["ok"] is True


def test_app_info_and_open_documents(adapter):
    class Doc:
        def __init__(self, name: str):
            self.FullName = name

    adapter._app = FakeApp(adapter.worker_jsx)
    adapter._app.Documents = [Doc("C:/JOB/AI_OUT/a.ai"), Doc("")]
    info = adapter.app_info()
    assert info.version == "28.0.0"
    assert info.documents_open == 2
    assert adapter.open_document_paths() == ["C:/JOB/AI_OUT/a.ai", ""]


def test_close_documents_only_closes_the_requested_folder(adapter):
    closed: list[str] = []

    class Doc:
        def __init__(self, name: str, collection: "FakeDocuments"):
            self.FullName = name
            self._collection = collection

        def Close(self, option: int) -> None:
            closed.append(self.FullName)
            self._collection.remove(self)

    class FakeDocuments:
        """Behaves like the COM Documents collection: closed docs disappear."""

        def __init__(self, names: list[str]):
            self._items = [Doc(name, self) for name in names]

        def remove(self, doc: Doc) -> None:
            if doc in self._items:
                self._items.remove(doc)

        def __len__(self) -> int:
            return len(self._items)

        def __getitem__(self, index: int) -> Doc:
            return self._items[index]

    adapter._app = FakeApp(adapter.worker_jsx)
    adapter._app.Documents = FakeDocuments(["C:/JOB/AI_OUT/a.ai", "C:/Users/me/important.ai"])

    count = adapter.close_documents(under_dir="C:/JOB/AI_OUT")
    assert count == 1
    assert closed == ["C:/JOB/AI_OUT/a.ai"]
    assert len(adapter._app.Documents) == 1

    # closing the rest is possible, but must be asked for explicitly
    assert adapter.close_documents() == 1
    assert closed[-1] == "C:/Users/me/important.ai"
    assert len(adapter._app.Documents) == 0


def test_close_documents_skips_untitled_documents_by_default(adapter):
    closed: list[str] = []

    class Doc:
        def __init__(self, name: str):
            self.FullName = name

        def Close(self, option: int) -> None:
            closed.append(self.FullName or "(untitled)")

    adapter._app = FakeApp(adapter.worker_jsx)
    adapter._app.Documents = [Doc("")]

    assert adapter.close_documents() == 0
    assert adapter.close_documents(include_untitled=True) == 1
    assert closed == ["(untitled)"]
