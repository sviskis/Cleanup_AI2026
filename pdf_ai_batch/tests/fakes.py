"""A fake Illustrator adapter for the queue tests (no COM, no Illustrator).

The real adapter is `pdf_ai_batch/adapters/illustrator.py`; it offers exactly the
two methods the queue uses:

    run_job(request) -> JobResult
    close_documents(under_dir=...)

`FakeIllustrator` scripts behaviour per page and records everything the tests need
to prove: the request, the state.json content at the moment of the call (to verify
that RUNNING is persisted before Illustrator is asked) and the close calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from pdf_ai_batch.core.contract import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_SKIP,
    JobResult,
)

FAKE_STATS = {
    "safe_groups_ungrouped": 2,
    "risky_groups_preserved": 1,
    "vector_masks_released": 1,
    "risky_masks_preserved": 0,
    "mask_paths_deleted": 1,
    "crop_perimeters_deleted": 3,
    "short_crop_marks_deleted": 1,
    "crop_objects_deleted": 4,
}


class IllustratorError(RuntimeError):
    """Named like the real adapter error, so the queue classifies it as COM."""


class FakeIllustrator:
    """Scripted stand-in for the Illustrator adapter.

    script maps page number or job_id to a behaviour:

        None / missing   -> OK and the output file is written
        "skip"           -> the worker returns SKIP
        "error"          -> the worker returns ERROR
        "ok_no_output"   -> OK but no output file at all (DONE rule)
        "empty_output"   -> OK but a 0 byte output file (DONE rule)
        "raise"          -> the adapter itself raises (COM level failure)
        callable         -> your own behaviour, returns a JobResult
    """

    def __init__(
        self,
        *,
        script: dict | None = None,
        output_bytes: bytes = b"%PDF-1.5\nfake AI\n",
        state_path: str | Path | None = None,
    ) -> None:
        self.script = dict(script or {})
        self.output_bytes = output_bytes
        self.state_path = Path(state_path) if state_path else None
        self.calls: list[dict] = []
        self.states_seen: list[dict] = []
        self.closed_calls: list[object] = []
        self.ensure_app_calls = 0

    # ------------------------------------------------------------ adapter surface

    def ensure_app(self) -> bool:
        self.ensure_app_calls += 1
        return True

    def close_documents(self, under_dir=None, include_untitled: bool = False) -> int:
        self.closed_calls.append(under_dir)
        return 0

    def run_job(self, request: dict) -> JobResult:
        self.calls.append(dict(request))
        if self.state_path is not None and self.state_path.is_file():
            self.states_seen.append(json.loads(self.state_path.read_text(encoding="utf-8")))
        behaviour = self.script.get(request.get("job_id"), self.script.get(request.get("page")))
        return self._behave(behaviour, request)

    # --------------------------------------------------------------------- helpers

    def pages_run(self) -> list[int]:
        return [call["page"] for call in self.calls]

    def _base_result(self, request: dict, status: str, message: str = "", error_type: str = "") -> JobResult:
        return JobResult(
            status=status,
            job_id=request["job_id"],
            run_id=request["run_id"],
            page=int(request["page"]),
            output=request["output"],
            message=message,
            error_type=error_type,
        )

    def _write_output(self, request: dict) -> None:
        target = Path(request["output"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.output_bytes)

    def _behave(self, behaviour, request: dict) -> JobResult:
        if callable(behaviour):
            return behaviour(request)

        if behaviour is None:
            self._write_output(request)
            result = self._base_result(request, STATUS_OK)
            result.objects_copied = 3
            result.stats = dict(FAKE_STATS)
            return result

        if behaviour == "skip":
            return self._base_result(request, STATUS_SKIP, "Output jau eksistē")

        if behaviour == "error":
            return self._base_result(
                request, STATUS_ERROR, "testa kļūda (worker)", "PROCESSING"
            )

        if behaviour == "ok_no_output":
            # a worker that reports OK but never wrote the output (failed save)
            target = Path(request["output"])
            if target.exists():
                target.unlink()
            result = self._base_result(request, STATUS_OK)
            result.objects_copied = 1
            return result

        if behaviour == "empty_output":
            target = Path(request["output"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"")
            return self._base_result(request, STATUS_OK)

        if behaviour == "raise":
            raise IllustratorError("COM nav pieejams (fake)")

        raise ValueError(f"nezināma fake uzvedība: {behaviour!r}")
