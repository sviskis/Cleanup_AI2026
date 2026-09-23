"""IllustratorAdapter - the ONLY place in the project that talks to COM.

Design rules from the approved plan:

* attach to a running Illustrator first, launch it only when it is not running
* all COM calls live in this module (no win32com anywhere else)
* business data never travels through COM arguments: the request is written to
  runtime/current_job.json (atomic rename) and the worker writes
  runtime/current_result.json, which Python reads and validates
* a stale result file is deleted before every job, and a result is accepted only
  when job_id AND run_id match the request
* a timeout never hangs the batch: it returns a failed job outcome with a clear
  error type and the tail of the worker log

The adapter is deliberately usable with a fake "app" object (see
pdf_ai_batch/tests/test_adapter_handshake.py), so the handshake can be tested
without Illustrator.
"""

from __future__ import annotations

import logging
import platform
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core import jsonio
from ..core.contract import (
    STATUS_ERROR,
    JobResult,
    missing_result,
    parse_result,
    result_matches,
    validate_request,
)

PROG_ID = "Illustrator.Application"
RESULT_FILE_NAME = "current_result.json"
REQUEST_FILE_NAME = "current_job.json"
LOG_FILE_NAME = "worker.log"
DEFAULT_TIMEOUT = 900.0
DEFAULT_POLL = 0.5
WORKER_LOG_TAIL = 2500


class IllustratorError(RuntimeError):
    """Raised for COM level problems (not for a failed job)."""


@dataclass
class Handshake:
    """Diagnostic record of one run_job handshake."""

    job_id: str = ""
    run_id: str = ""
    invoked: bool = False
    waited_seconds: float = 0.0
    rejected_results: int = 0
    status: str = ""
    note: str = ""
    error_type: str = ""


@dataclass
class AppInfo:
    name: str = ""
    version: str = ""
    build: str = ""
    documents_open: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "build": self.build,
            "documents_open": self.documents_open,
        }


class IllustratorAdapter:
    """Runs one page job at a time inside Illustrator."""

    def __init__(
        self,
        worker_jsx: str | Path,
        runtime_dir: str | Path,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        poll_interval: float = DEFAULT_POLL,
        logger: logging.Logger | None = None,
    ) -> None:
        self.worker_jsx = Path(worker_jsx)
        self.runtime_dir = Path(runtime_dir)
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self.log = logger or logging.getLogger("pdf_ai_batch.illustrator")
        self._app: Any = None
        self.last_handshake: Handshake | None = None

    # ---------------------------------------------------------------- paths

    @property
    def request_path(self) -> Path:
        return self.runtime_dir / REQUEST_FILE_NAME

    @property
    def result_path(self) -> Path:
        return self.runtime_dir / RESULT_FILE_NAME

    @property
    def worker_log_path(self) -> Path:
        return self.runtime_dir / LOG_FILE_NAME

    def ensure_runtime_dir(self) -> Path:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        return self.runtime_dir

    # ---------------------------------------------------------------- COM app

    def _com_client(self):
        """Import win32com lazily so the rest of the tool has no hard dependency."""
        try:
            import win32com.client  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise IllustratorError(
                "pywin32 nav instalēts (pip install pywin32) - COM nav pieejams"
            ) from exc
        return win32com.client

    def attach(self) -> bool:
        """Attach to a running Illustrator instance."""
        try:
            client = self._com_client()
            self._app = client.GetActiveObject(PROG_ID)
            self.log.info("Pievienojos jau atvērtam Illustrator")
            return True
        except Exception as exc:  # noqa: BLE001
            self.log.debug("Attach neizdevās: %s", exc)
            self._app = None
            return False

    def launch(self, visible: bool = True, wait_seconds: float = 90.0) -> bool:
        """Start Illustrator and attach to it."""
        try:
            client = self._com_client()
            self._app = client.Dispatch(PROG_ID)
            try:
                self._app.Visible = bool(visible)
            except Exception:  # noqa: BLE001 - not fatal
                pass
            deadline = time.monotonic() + max(5.0, wait_seconds)
            while time.monotonic() < deadline:
                if self.app_info().version:
                    self.log.info("Palaidu Illustrator")
                    return True
                time.sleep(1.0)
            self.log.warning("Illustrator palaists, bet versiju neizdevās nolasīt")
            return True
        except Exception as exc:  # noqa: BLE001
            self.log.debug("Launch neizdevās: %s", exc)
            self._app = None
            return False

    def ensure_app(self) -> bool:
        """Attach first, launch only when needed."""
        self.ensure_runtime_dir()
        if self._app is not None:
            return True
        return self.attach() or self.launch()

    def is_available(self) -> bool:
        return self.ensure_app()

    def app_info(self) -> AppInfo:
        """Best effort information about the running Illustrator."""
        info = AppInfo()
        if self._app is None:
            return info
        for attribute, setter in (
            ("Name", "name"),
            ("Version", "version"),
            ("BuildNumber", "build"),
        ):
            try:
                setattr(info, setter, str(getattr(self._app, attribute, "") or ""))
            except Exception:  # noqa: BLE001
                pass
        try:
            info.documents_open = int(len(self._app.Documents))
        except Exception:  # noqa: BLE001
            info.documents_open = 0
        return info

    def health_check(self) -> dict[str, Any]:
        """Everything a preflight needs to know about the Illustrator side."""
        cleanup = self.worker_jsx.parent / "cleanup.jsx"
        report: dict[str, Any] = {
            "python": platform.python_version(),
            "worker_jsx": str(self.worker_jsx),
            "worker_jsx_exists": self.worker_jsx.is_file(),
            "cleanup_jsx_exists": cleanup.is_file(),
            "runtime_dir": str(self.runtime_dir),
            "runtime_writable": _dir_writable(self.runtime_dir),
            "com_attached": self._app is not None,
            "illustrator": self.app_info().as_dict() if self._app is not None else {},
            "timeout_seconds": self.timeout,
        }
        report["ok"] = bool(
            report["worker_jsx_exists"]
            and report["cleanup_jsx_exists"]
            and report["runtime_writable"]
            and report["com_attached"]
        )
        return report

    # ---------------------------------------------------------------- job

    def prepare_handoff(self) -> None:
        """Make sure the runtime folder exists and no stale result is left."""
        self.ensure_runtime_dir()
        jsonio.delete_if_exists(self.result_path)

    def write_request(self, request: dict) -> Path:
        """Write the request atomically (temp file + rename)."""
        problems = validate_request(request)
        if problems:
            raise IllustratorError("Nederīgs pieprasījums: " + "; ".join(problems))
        return jsonio.write_json_atomic(self.request_path, request)

    def invoke_worker(self) -> None:
        """Tell Illustrator to run jsx/worker.jsx (no data through COM)."""
        if self._app is None and not self.ensure_app():
            raise IllustratorError("Illustrator nav pieejams (COM)")
        if not self.worker_jsx.is_file():
            raise IllustratorError(f"worker.jsx nav atrasts: {self.worker_jsx}")
        try:
            self._app.DoJavaScriptFile(str(self.worker_jsx))
        except Exception as exc:  # noqa: BLE001
            raise IllustratorError(f"DoJavaScriptFile neizdevās: {exc}") from exc

    def read_result(self, job_id: str, run_id: str) -> JobResult | None:
        """Read and validate the result file for this job/run."""
        data = jsonio.read_json(self.result_path, default=None)
        if not result_matches(data, job_id, run_id):
            return None
        return parse_result(data)

    def worker_log_tail(self, limit: int = WORKER_LOG_TAIL) -> str:
        """Last part of the worker log, for error messages."""
        text = jsonio.read_text(self.worker_log_path)
        return text[-limit:].strip() if text else ""

    def run_job(self, request: dict) -> JobResult:
        """Full handshake: request -> worker -> validated result.

        Raises IllustratorError only for COM/infrastructure problems; a job that
        fails inside Illustrator comes back as an ERROR JobResult.
        """
        started = time.monotonic()
        job_id = str(request.get("job_id", ""))
        run_id = str(request.get("run_id", ""))
        handshake = Handshake(job_id=job_id, run_id=run_id)
        self.last_handshake = handshake

        self.prepare_handoff()
        self.write_request(request)

        try:
            self.invoke_worker()
        except IllustratorError as exc:
            handshake.status = STATUS_ERROR
            handshake.error_type = "COM"
            handshake.note = str(exc)
            handshake.waited_seconds = time.monotonic() - started
            return missing_result(f"COM kļūda: {exc}", "COM")
        handshake.invoked = True

        def _rejected(candidate: dict) -> None:
            handshake.rejected_results += 1
            self.log.warning(
                "Noraidu rezultātu (job_id=%s run_id=%s) - gaidu %s/%s",
                candidate.get("job_id"),
                candidate.get("run_id"),
                job_id,
                run_id,
            )

        data, reason = jsonio.wait_for_json(
            self.result_path,
            validator=lambda candidate: result_matches(candidate, job_id, run_id),
            timeout=self.timeout,
            poll_interval=self.poll_interval,
            on_poll=_rejected,
        )
        handshake.waited_seconds = time.monotonic() - started

        if data is None:
            handshake.status = STATUS_ERROR
            handshake.error_type = "TIMEOUT" if reason == "timeout" else "BAD_RESULT"
            handshake.note = self.worker_log_tail()
            return missing_result(
                f"Nav derīga rezultāta pēc {self.timeout:.0f}s ({reason}). "
                f"Worker log: {handshake.note or '-'}",
                handshake.error_type,
            )

        result = parse_result(data)
        handshake.status = result.status
        handshake.error_type = result.error_type
        return result

    # ---------------------------------------------------------------- cleanup

    def open_document_paths(self) -> list[str]:
        """Full paths of the documents currently open in Illustrator."""
        if self._app is None:
            return []
        paths: list[str] = []
        try:
            for index in range(len(self._app.Documents)):
                document = self._app.Documents[index]
                try:
                    paths.append(str(document.FullName))
                except Exception:  # noqa: BLE001 - untitled documents raise
                    paths.append("")
        except Exception:  # noqa: BLE001
            return paths
        return paths

    def close_documents(self, under_dir: str | Path | None = None, include_untitled: bool = False) -> int:
        """Close documents opened by the batch.

        With `under_dir` only documents inside that folder are closed - the safe
        form used by the batch (JOB/AI_OUT). Without it every document is closed,
        which is destructive; call that only on purpose.
        """
        if self._app is None:
            return 0
        closed = 0
        target = _normalise_path(under_dir) if under_dir else None
        try:
            for index in range(len(self._app.Documents) - 1, -1, -1):
                document = self._app.Documents[index]
                try:
                    full_name = str(document.FullName)
                except Exception:  # noqa: BLE001 - untitled document
                    full_name = ""
                if full_name:
                    if target and not _normalise_path(full_name).startswith(target):
                        continue
                elif not include_untitled:
                    continue
                try:
                    document.Close(2)  # 2 = do not save changes
                    closed += 1
                except Exception as exc:  # noqa: BLE001
                    self.log.warning("Nevarēju aizvērt dokumentu %s: %s", full_name, exc)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("close_documents kļūda: %s", exc)
        return closed


def _normalise_path(value: str | Path) -> str:
    """Lower case, forward slashes - COM and Python mix both on Windows."""
    return str(value).replace("\\", "/").lower()


def _dir_writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / "__write_test.tmp"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def illustrator_process_running() -> bool:
    """True when an Illustrator process exists (a cheap preflight hint)."""
    if platform.system() != "Windows":
        return False
    try:
        output = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Illustrator.exe"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout
        return "Illustrator.exe" in output
    except (OSError, subprocess.SubprocessError):
        return False
