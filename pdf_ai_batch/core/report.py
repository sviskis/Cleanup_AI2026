"""Immutable job reports: what a batch/pass really did.

Every pass of the queue (RUN ALL ENABLED, RUN CURRENT PDF, RUN SELECTED, CONTINUE,
RETRY ...) ends with `write_report`, which writes two files into `JOB/LOG/reports/`:

    report_<YYYYmmdd-HHMMSS>.json    canonical, structured, machine readable
    report_<YYYYmmdd-HHMMSS>.txt     the same content, human readable

Reports are **historical outputs**: an existing file is never overwritten (a second
report within the same second gets a `-2` suffix), both files are written atomically,
and producing one reads the state model instead of changing it - `config.json`,
`state.json` and the outputs stay untouched.

    JobReport            one pass: counts, documents, errors, duration, objects
    build_report()       from the queue state + the pass summary (no side effects)
    write_report()       the atomic JSON + TXT pair, returns ReportPaths
    list_reports()       the reports of a JOB, newest first
    read_report()        a report JSON back (for the GUI / tests)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

from . import jsonio, state

REPORT_VERSION = 1
REPORT_DIR_NAME = "reports"
REPORT_PREFIX = "report_"
FILE_STAMP_FORMAT = "%Y%m%d-%H%M%S"
#: how many `-<n>` suffixes a colliding report name may get before we give up
MAX_NAME_ATTEMPTS = 100


def duration_text(seconds: float) -> str:
    """Human readable duration: `21m 42s`, `1h 04m 09s`, `3.4s`."""
    try:
        total = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return "0s"
    if total < 60:
        return f"{total:.1f}s"
    hours, rest = divmod(int(total), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def _epoch(stamp: str) -> float | None:
    """Epoch seconds of a `state.TIMESTAMP_FORMAT` stamp (None when unparsable)."""
    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, state.TIMESTAMP_FORMAT).timestamp()
    except ValueError:
        return None


def reports_dir(project) -> Path:
    """`JOB/LOG/reports` - created on demand by `write_report`."""
    return Path(project.log_dir) / REPORT_DIR_NAME


@dataclass(frozen=True)
class ReportPaths:
    """Where one report was written (JSON is the canonical one)."""

    json: Path
    txt: Path

    def format(self) -> str:
        return f"report: {self.txt.name} + {self.json.name}"

    def as_dict(self) -> dict:
        return {"json": str(self.json), "txt": str(self.txt)}


@dataclass(frozen=True)
class JobReport:
    """One finished pass, in the shape the JSON/TXT writers need."""

    job: str
    root: str
    label: str = ""
    started: str = ""
    finished: str = ""
    duration: float = 0.0
    counts: dict = field(default_factory=dict)
    total: int = 0
    enabled: int = 0
    runnable: int = 0
    run: dict = field(default_factory=dict)
    documents: tuple = ()
    errors: tuple = ()
    interrupted: tuple = ()
    objects_processed: int = 0
    retries: int = 0
    illustrator_version: str = ""
    aborted: bool = False
    stop_reason: str = ""
    session_id: str = ""
    recovered: tuple = ()
    app_version: str = ""
    version: int = REPORT_VERSION

    # ------------------------------------------------------------------ helpers

    def count_of(self, name: str) -> int:
        return int((self.counts or {}).get(name, 0))

    @property
    def duration_label(self) -> str:
        return duration_text(self.duration)

    def to_dict(self) -> dict:
        """Canonical structured report (the JSON file, and the GUI later)."""
        return {
            "version": self.version,
            "job": self.job,
            "root": self.root,
            "label": self.label,
            "started": self.started,
            "finished": self.finished,
            "duration_seconds": round(float(self.duration), 3),
            "duration": self.duration_label,
            "pdfs": len(self.documents),
            "pages": int(self.total),
            "counts": {name: self.count_of(name) for name in state.VALID_STATES},
            "total": int(self.total),
            "enabled": int(self.enabled),
            "runnable": int(self.runnable),
            "run": dict(self.run),
            "objects_processed": int(self.objects_processed),
            "retries": int(self.retries),
            "illustrator_version": self.illustrator_version,
            "aborted": bool(self.aborted),
            "stop_reason": self.stop_reason,
            "session_id": self.session_id,
            "recovered": list(self.recovered),
            "app_version": self.app_version,
            "documents": [dict(row) for row in self.documents],
            "errors": [dict(row) for row in self.errors],
            "interrupted": [dict(row) for row in self.interrupted],
        }

    def to_text(self) -> str:
        """The human readable report (the TXT file)."""
        counts = self.counts or {}
        lines = [
            "JOB REPORT",
            "",
            f"Job: {self.job}",
            f"Project: {self.root}",
        ]
        if self.label:
            lines.append(f"Run: {self.label}")
        lines.extend(
            [
                f"Started: {self.started or '-'}",
                f"Finished: {self.finished or '-'}",
                f"Duration: {self.duration_label}",
                "",
                f"PDFs:       {len(self.documents)}",
                f"Pages:      {int(self.total)}",
                "",
            ]
        )
        width = max(len(name) for name in state.VALID_STATES)
        for name in state.VALID_STATES:
            lines.append(f"{name + ':':<{width + 1}} {int(counts.get(name, 0))}")
        lines.extend(
            [
                "",
                f"Objects processed: {int(self.objects_processed)}",
                f"Retries: {int(self.retries)}",
            ]
        )
        if self.illustrator_version:
            lines.append(f"Illustrator version: {self.illustrator_version}")
        if self.run:
            lines.append(
                "This pass: "
                f"OK={int(self.run.get('ok', 0))} "
                f"SKIPPED={int(self.run.get('skipped', 0))} "
                f"ERROR={int(self.run.get('error', 0))} "
                f"objects={int(self.run.get('objects_copied', 0))}"
            )
        if self.recovered:
            lines.append("Recovered RUNNING -> INTERRUPTED: " + ", ".join(self.recovered))
        if self.aborted:
            lines.append(f"Pass aborted: {self.stop_reason or 'adapter failure'}")
        if self.documents:
            lines.append("")
            lines.append("PDFs:")
            for row in self.documents:
                per = row.get("counts") or {}
                summary = " ".join(f"{name}={per.get(name, 0)}" for name in state.VALID_STATES)
                lines.append(
                    f"  {row.get('pdf') or row.get('pdf_id') or '?'}: "
                    f"{row.get('processed', 0)}/{row.get('pages', 0)} done | {summary}"
                )
        lines.append("")
        lines.append("ERRORS:")
        if self.errors:
            for row in self.errors:
                lines.append("  " + _item_line(row))
        else:
            lines.append("  -")
        if self.interrupted:
            lines.append("")
            lines.append("INTERRUPTED:")
            for row in self.interrupted:
                lines.append("  " + _item_line(row))
        lines.append("")
        return "\n".join(lines)


def _item_line(row: dict) -> str:
    """One `pdf page N | TYPE | message` line of the report."""
    text = (
        f"{row.get('pdf', '?')} page {int(row.get('page', 0)):02d} | "
        f"{row.get('error_type') or row.get('state', 'ERROR')} | "
        f"{row.get('error_message') or '-'}"
    )
    if row.get("attempts"):
        text += f" | attempts {int(row['attempts'])}"
    return text


# ------------------------------------------------------------------------ building


def _item_rows(items: Sequence[state.QueueItem], wanted: str) -> tuple[dict, ...]:
    """Report rows of every item in one state, in queue order."""
    return tuple(
        {
            "pdf": item.pdf_name,
            "pdf_id": item.document,
            "job_id": item.job_id,
            "page": int(item.page),
            "state": item.state,
            "attempts": int(item.attempts),
            "error_type": item.error_type,
            "error_message": item.error_message,
            "last_run_id": item.last_run_id,
            "finished": item.finished,
        }
        for item in items
        if item.state == wanted
    )


def build_report(
    project,
    *,
    items: Sequence[state.QueueItem] | None = None,
    summary=None,
    label: str = "",
    illustrator_version: str = "",
    app_version: str = "",
    when: datetime | None = None,
) -> JobReport:
    """Assemble a report from the queue state and (optionally) a finished pass.

    `items` is the state model to report on (defaults to `state.json` on disk), so the
    report always matches what the queue shows. `summary` (a `BatchSummary`) adds what
    THIS pass did - outcomes, objects copied, abort reason. Nothing is written and no
    file is modified.
    """
    if items is None:
        document = state.load_state(
            Path(project.state_path), job_root=project.root
        )
        items = list(document.items)
    items = list(items)

    counts = state.counts_of(items)
    total = len(items)
    enabled = len([item for item in items if item.enabled])
    runnable = len([item for item in items if item.runnable])

    documents: list[dict] = []
    if summary is not None and getattr(summary, "documents", None):
        for row in summary.documents:
            per = dict(row.get("counts") or {})
            documents.append(
                {
                    "pdf": row.get("pdf", ""),
                    "pdf_id": row.get("pdf_id", ""),
                    "pages": int(row.get("pages", 0)),
                    "processed": int(row.get("processed", 0)),
                    "counts": {name: int(per.get(name, 0)) for name in state.VALID_STATES},
                }
            )
    else:
        by_document: dict[str, dict] = {}
        for item in items:
            row = by_document.setdefault(
                item.document,
                {
                    "pdf": item.pdf_name,
                    "pdf_id": item.document,
                    "pages": 0,
                    "processed": 0,
                    "counts": {name: 0 for name in state.VALID_STATES},
                },
            )
            row["pages"] += 1
            row["counts"][item.state] = row["counts"].get(item.state, 0) + 1
            if item.finished_state:
                row["processed"] += 1
        documents = list(by_document.values())

    started = getattr(summary, "started", "") or ""
    finished = getattr(summary, "finished", "") or ""
    if not finished:
        finished = state.now_stamp(when)
    start_epoch = _epoch(started)
    end_epoch = _epoch(finished)
    duration = 0.0
    if start_epoch is not None and end_epoch is not None:
        duration = max(0.0, end_epoch - start_epoch)

    run_stats = dict(getattr(summary, "run_stats", {}) or {}) if summary is not None else {}
    objects = int(run_stats.get("objects_copied", 0) or 0)
    retries = sum(max(0, int(item.attempts) - 1) for item in items)

    return JobReport(
        job=Path(project.root).name,
        root=str(Path(project.root)),
        label=str(label or getattr(summary, "label", "") or ""),
        started=started,
        finished=finished,
        duration=duration,
        counts={name: int(counts.get(name, 0)) for name in state.VALID_STATES},
        total=total,
        enabled=enabled,
        runnable=runnable,
        run=run_stats,
        documents=tuple(documents),
        errors=_item_rows(items, state.ERROR),
        interrupted=_item_rows(items, state.INTERRUPTED),
        objects_processed=objects,
        retries=retries,
        illustrator_version=str(illustrator_version or ""),
        aborted=bool(getattr(summary, "aborted", False)),
        stop_reason=str(getattr(summary, "stop_reason", "") or ""),
        session_id=str(getattr(summary, "session_id", "") or ""),
        recovered=tuple(getattr(summary, "recovered", ()) or ()),
        app_version=str(app_version or ""),
    )


# ------------------------------------------------------------------------ writing


def report_paths(project, *, when: datetime | None = None) -> ReportPaths:
    """A free report name pair for this moment (never an existing file)."""
    folder = reports_dir(project)
    stamp = (when or datetime.now()).strftime(FILE_STAMP_FORMAT)
    base = f"{REPORT_PREFIX}{stamp}"
    for attempt in range(1, MAX_NAME_ATTEMPTS + 1):
        name = base if attempt == 1 else f"{base}-{attempt}"
        json_path = folder / f"{name}.json"
        txt_path = folder / f"{name}.txt"
        if not json_path.exists() and not txt_path.exists():
            return ReportPaths(json=json_path, txt=txt_path)
    raise RuntimeError(f"Nevar atrast brīvu report nosaukumu mapē {folder}")


def write_report(project, report: JobReport, *, when: datetime | None = None) -> ReportPaths:
    """Write the immutable JSON + TXT pair of one report and return the paths."""
    paths = report_paths(project, when=when)
    jsonio.write_json_atomic(paths.json, report.to_dict())
    jsonio.write_text_atomic(paths.txt, report.to_text())
    return paths


def list_reports(project) -> list[Path]:
    """The report JSON files of a JOB, newest first.

    Ordered by modification time (a second report within the same second gets a `-2`
    suffix, and that one is newer), then by name for a stable order.
    """
    folder = reports_dir(project)
    if not folder.is_dir():
        return []
    files = list(folder.glob(f"{REPORT_PREFIX}*.json"))
    return sorted(files, key=lambda path: (path.stat().st_mtime, path.name), reverse=True)


def read_report(path: str | Path) -> dict:
    """Read one report JSON (empty dict when it is missing or unreadable)."""
    data = jsonio.read_json(path, default={})
    return data if isinstance(data, dict) else {}




