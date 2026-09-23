"""The Python <-> JSX contract in one place.

Both sides of the exchange are defined here so that there is exactly ONE
definition of the wire format in the Python code:

    request : written by Python to runtime/current_job.json
    result  : written by jsx/worker.jsx to runtime/current_result.json

Matching rule: a result is only accepted when job_id AND run_id match the
request. Everything else is treated as a stale or foreign file.

The JSX side implements the same names in jsx/cleanup.jsx (statsToContract) and
jsx/worker.jsx; the shared fixtures in tests/fixtures are verified from BOTH
sides (pytest + tests/jscript/test_json_contract.js).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REQUEST_SCHEMA = "pdf_ai_batch/job_request/v1"
RESULT_SCHEMA = "pdf_ai_batch/job_result/v1"

STATUS_OK = "OK"
STATUS_ERROR = "ERROR"
STATUS_SKIP = "SKIP"
VALID_STATUSES = (STATUS_OK, STATUS_ERROR, STATUS_SKIP)

TEMPLATE_MODE_COPY = "copy"      # Python copied the template to the output
TEMPLATE_MODE_SAVEAS = "saveas"  # worker opens the .ait/.ai and saves as the output

LAYER_DEFAULT = "ARTWORK"

DEFAULT_CLEANUP = {
    "releaseSafeVectorMasks": True,
    "deleteCropMarks": True,
    "ungroupPasses": 40,
}

STAT_KEYS = (
    "safe_groups_ungrouped",
    "risky_groups_preserved",
    "vector_masks_released",
    "risky_masks_preserved",
    "mask_paths_deleted",
    "crop_perimeters_deleted",
    "short_crop_marks_deleted",
    "crop_objects_deleted",
)

REQUEST_REQUIRED_KEYS = (
    "schema",
    "run_id",
    "job_id",
    "pdf",
    "page",
    "template",
    "template_mode",
    "output",
    "layer",
    "clear_layer",
    "overwrite",
)

# the fields that always carry a resolved absolute path
CONTRACT_PATH_KEYS = ("pdf", "template", "output")

_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:[\\/]")


def contract_path(value: str | Path) -> str:
    """Absolute path with forward slashes - the only form used on the wire.

    Python owns path resolution (.clinerules). The worker runs inside Illustrator
    with a different current working directory, so a relative path in the request
    would point somewhere else and ``File(request.pdf).exists`` would be false.
    ``Path.resolve()`` makes the field independent of the cwd of whoever reads it.

        "temp\\JOB\\PDF\\a.pdf" -> "C:/repo/temp/JOB/PDF/a.pdf"
    """
    return Path(str(value)).expanduser().resolve().as_posix()


def is_absolute_path(value: str | Path | None) -> bool:
    """True for "C:/job/x", "\\\\server\\share\\x" and "/opt/x" (portable check)."""
    text = str(value or "")
    if not text:
        return False
    if text.startswith("/") or text.startswith("\\\\"):
        return True
    return bool(_DRIVE_LETTER_RE.match(text))


@dataclass
class JobResult:
    """Parsed worker result."""

    status: str
    job_id: str = ""
    run_id: str = ""
    page: int = 0
    output: str = ""
    objects_copied: int = 0
    stats: dict[str, int] = field(default_factory=dict)
    message: str = ""
    error_type: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def skipped(self) -> bool:
        return self.status == STATUS_SKIP

    @property
    def failed(self) -> bool:
        return self.status == STATUS_ERROR

    def stat(self, key: str) -> int:
        try:
            return int(self.stats.get(key, 0))
        except (TypeError, ValueError):
            return 0


def build_request(
    *,
    run_id: str,
    job_id: str,
    pdf: str,
    page: int,
    template: str,
    output: str,
    layer: str = LAYER_DEFAULT,
    clear_layer: bool = True,
    overwrite: bool = False,
    template_mode: str = TEMPLATE_MODE_COPY,
    cleanup: dict | None = None,
) -> dict:
    """Build one page request for the worker.

    `pdf`, `template` and `output` are resolved to absolute forward slash paths
    here, so the request never depends on a current working directory.
    """
    return {
        "schema": REQUEST_SCHEMA,
        "run_id": run_id,
        "job_id": job_id,
        "pdf": contract_path(pdf),
        "page": int(page),
        "template": contract_path(template),
        "template_mode": template_mode,
        "output": contract_path(output),
        "layer": layer or LAYER_DEFAULT,
        "clear_layer": bool(clear_layer),
        "overwrite": bool(overwrite),
        "cleanup": dict(cleanup) if cleanup else dict(DEFAULT_CLEANUP),
    }


def validate_request(request: dict | None) -> list[str]:
    """Return a list of problems with a request (empty = valid)."""
    if not isinstance(request, dict):
        return ["pieprasījums nav objektā"]

    problems: list[str] = []
    for key in REQUEST_REQUIRED_KEYS:
        if request.get(key) in (None, ""):
            problems.append(f"trūkst lauka: {key}")

    if request.get("schema") != REQUEST_SCHEMA:
        problems.append(f"schema nav {REQUEST_SCHEMA}: {request.get('schema')!r}")

    page = request.get("page")
    if not isinstance(page, int) or page < 1:
        problems.append(f"page nav derīgs lappuses numurs: {page!r}")

    for key in CONTRACT_PATH_KEYS:
        value = request.get(key)
        if value and not is_absolute_path(value):
            problems.append(f"{key} nav absolūts ceļš (Python to atrisina): {value!r}")

    mode = request.get("template_mode")
    if mode not in (TEMPLATE_MODE_COPY, TEMPLATE_MODE_SAVEAS):
        problems.append(f"template_mode nav derīgs: {mode!r}")

    cleanup = request.get("cleanup")
    if cleanup is not None and not isinstance(cleanup, dict):
        problems.append("cleanup nav objekts")

    return problems


def result_matches(result: dict | None, job_id: str, run_id: str) -> bool:
    """True when a result belongs to exactly this job and run."""
    if not isinstance(result, dict):
        return False
    return result.get("job_id") == job_id and result.get("run_id") == run_id


def parse_result(data: dict | None) -> JobResult:
    """Turn raw worker JSON into a JobResult (never raises)."""
    if not isinstance(data, dict):
        return JobResult(status=STATUS_ERROR, message="rezultāts nav objektā", error_type="BAD_RESULT")

    status = str(data.get("status") or "").upper()
    if status not in VALID_STATUSES:
        status = STATUS_ERROR

    stats: dict[str, int] = {}
    raw_stats = data.get("stats")
    if isinstance(raw_stats, dict):
        for key in STAT_KEYS:
            value = raw_stats.get(key)
            try:
                stats[key] = int(value)
            except (TypeError, ValueError):
                stats[key] = 0

    def _int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    return JobResult(
        status=status,
        job_id=str(data.get("job_id") or ""),
        run_id=str(data.get("run_id") or ""),
        page=_int(data.get("page")),
        output=str(data.get("output") or ""),
        objects_copied=_int(data.get("objects_copied")),
        stats=stats,
        message=str(data.get("message") or ""),
        error_type=str(data.get("error_type") or ""),
        raw=data,
    )


def missing_result(message: str, error_type: str = "NO_RESULT") -> JobResult:
    """Result-shaped object for the case where no valid result file arrived."""
    return JobResult(status=STATUS_ERROR, message=message, error_type=error_type)


def summarise_results(results: Iterable[JobResult]) -> dict:
    """Counters and summed stats over a list of results (used by the batch)."""
    summary = {"total": 0, "ok": 0, "skipped": 0, "error": 0, "objects_copied": 0}
    totals = {key: 0 for key in STAT_KEYS}
    for result in results:
        summary["total"] += 1
        if result.ok:
            summary["ok"] += 1
        elif result.skipped:
            summary["skipped"] += 1
        else:
            summary["error"] += 1
        summary["objects_copied"] += result.objects_copied
        for key in STAT_KEYS:
            totals[key] += result.stat(key)
    summary["stats"] = totals
    return summary
