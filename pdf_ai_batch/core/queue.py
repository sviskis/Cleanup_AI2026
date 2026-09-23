"""The persistent batch queue: one JOB folder, one queue, one state.json.

Milestone 2 API (all of it lives here):

    build_queue()          plan the pages of a PDF and turn them into items
    run_next()             run the first runnable item
    run_all_enabled()      rebuild the plan, then run every enabled runnable item
    continue_queue()       resume: WAITING + INTERRUPTED, never DONE/SKIPPED/ERROR
    retry_errors()         ERROR -> WAITING (and optionally run them)
    retry_interrupted()    INTERRUPTED -> WAITING (and optionally run them)
    skip_item()            deliberately skip one item
    reset_item()           back to WAITING (works on DONE too)

Rules the queue enforces:

* **DONE needs both**: the worker returned `OK` AND the expected output AI exists
  (`pagejob.output_ready`). "OK but no output" becomes `ERROR` (`OUTPUT_MISSING`).
* **One bad page never stops the batch.** Every item runs in its own try/except; a
  page level failure is recorded and the next item runs. Only an adapter/COM level
  failure aborts the pass (the environment is broken, not the page) and the
  remaining items stay runnable.
* **state.json is written before and after every item**, so a crash leaves at most
  one page as `RUNNING`, which the next session recovers as `INTERRUPTED`.
* **The COM rule**: this module never imports COM. It uses the adapter object it
  was given (`adapters/illustrator.py` in production, a fake in the tests) and only
  the proven `run_job()` path.
* An item is only ever re-run when it is `WAITING` or `INTERRUPTED`; `DONE` and
  `SKIPPED` need an explicit `reset_item()` (or `build_queue(reset=True)`).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

from . import pagejob, state
from .contract import (
    STATUS_OK,
    STATUS_SKIP,
    TEMPLATE_MODE_COPY,
    JobResult,
    contract_path,
    summarise_results,
)
from .naming import new_run_id, pdf_id_for
from .pagejob import PagePlan, PagePlanError, output_ready
from .project import JobProject

CLOSE_LEFTOVERS_NOTE = "Aizvēru %s dokumentu, kas palika no iepriekšējā piegājiena"
DEFAULT_ABORT_TYPES = ("IllustratorError", "COM")

# how a queue state maps onto a worker status (used for the pass statistics)
STATE_TO_STATUS = {
    state.DONE: STATUS_OK,
    state.SKIPPED: STATUS_SKIP,
    state.ERROR: state.ERROR,
    state.INTERRUPTED: state.INTERRUPTED,
    state.WAITING: state.WAITING,
    state.RUNNING: state.RUNNING,
}

ProgressCallback = Callable[["RunOutcome"], None]


class QueueError(RuntimeError):
    """Raised for queue misuse: unknown item, illegal transition."""


def _stamp_to_epoch(stamp: str) -> float | None:
    """Parse a state.json timestamp ("2026-09-23 18:00:47") into epoch seconds."""
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp, state.TIMESTAMP_FORMAT).timestamp()
    except (TypeError, ValueError):
        return None


@dataclass
class RunOutcome:
    """What happened to ONE item during a pass."""

    job_id: str
    page: int
    state_name: str
    output: str = ""
    pdf_id: str = ""
    pdf: str = ""
    error_type: str = ""
    message: str = ""
    objects_copied: int = 0
    stats: dict = field(default_factory=dict)
    attempts: int = 0
    run_id: str = ""
    seconds: float = 0.0
    abort: bool = False

    @property
    def ok(self) -> bool:
        return self.state_name == state.DONE

    @property
    def failed(self) -> bool:
        return self.state_name == state.ERROR

    @property
    def document(self) -> str:
        """Document label of this outcome (file name when known, else pdf_id)."""
        return self.pdf or self.pdf_id

    def line(self) -> str:
        """One compact console line for the batch progress output."""
        prefix = f"{self.pdf_id} " if self.pdf_id else ""
        text = f"{prefix}{self.page:03d} {self.state_name:<11} {self.output}"
        if self.state_name == state.DONE and self.objects_copied:
            text += f"  ({self.objects_copied} objekti)"
        if self.state_name == state.ERROR:
            text += f"  [{self.error_type}] {self.message}"
        elif self.message:
            text += f"  ({self.message})"
        return text


@dataclass
class BatchSummary:
    """Counts of the whole queue plus what this pass did."""

    counts: dict[str, int] = field(default_factory=dict)
    total: int = 0
    enabled: int = 0
    runnable: int = 0
    outcomes: list[RunOutcome] = field(default_factory=list)
    session_id: str = ""
    started: str = ""
    finished: str = ""
    aborted: bool = False
    stop_reason: str = ""
    recovered: list[str] = field(default_factory=list)
    documents: list[dict] = field(default_factory=list)

    @property
    def pdfs(self) -> int:
        """Number of documents in the queue."""
        return int(self.counts.get("pdfs", len(self.documents)))

    @property
    def pages_total(self) -> int:
        return int(self.counts.get("total", self.total))

    def document_lines(self) -> list[str]:
        """One line per document: progress and counts of that PDF."""
        lines: list[str] = []
        for row in self.documents:
            counts = row.get("counts") or {}
            lines.append(
                f"  {row.get('pdf', row.get('pdf_id', '?')):<24} "
                f"{row.get('processed', 0)}/{row.get('pages', 0)} apstrādātas | "
                + " ".join(f"{name}={counts.get(name, 0)}" for name in state.VALID_STATES)
            )
        return lines

    @property
    def run_stats(self) -> dict:
        """Aggregated worker results of THIS pass (contract.summarise_results)."""
        results = [
            JobResult(
                status=STATE_TO_STATUS.get(outcome.state_name, outcome.state_name),
                job_id=outcome.job_id,
                page=outcome.page,
                output=outcome.output,
                objects_copied=outcome.objects_copied,
                stats=outcome.stats,
                message=outcome.message,
                error_type=outcome.error_type,
            )
            for outcome in self.outcomes
        ]
        return summarise_results(results)

    def as_dict(self) -> dict:
        return {
            "counts": dict(self.counts),
            "total": self.total,
            "enabled": self.enabled,
            "runnable": self.runnable,
            "pdfs": self.pdfs,
            "started": self.started,
            "finished": self.finished,
            "aborted": self.aborted,
            "stop_reason": self.stop_reason,
            "recovered": list(self.recovered),
            "documents": [
                {
                    "pdf_id": row.get("pdf_id", ""),
                    "pdf": row.get("pdf", ""),
                    "pages": row.get("pages", 0),
                    "processed": row.get("processed", 0),
                    "current_page": row.get("current_page", 0),
                    "counts": dict(row.get("counts") or {}),
                }
                for row in self.documents
            ],
            "run": self.run_stats,
            "items": [
                {
                    "job_id": outcome.job_id,
                    "pdf_id": outcome.pdf_id,
                    "page": outcome.page,
                    "state": outcome.state_name,
                    "output": outcome.output,
                    "error_type": outcome.error_type,
                    "message": outcome.message,
                    "objects_copied": outcome.objects_copied,
                    "attempts": outcome.attempts,
                    "run_id": outcome.run_id,
                }
                for outcome in self.outcomes
            ],
        }

    def format(self) -> str:
        """The end of batch report: project view, then every document."""
        counts = self.counts
        lines = [
            f"PDFs: {self.pdfs} | Lapas kopā: {self.pages_total}",
            "Kopsavilkums: "
            + " ".join(f"{name}={counts.get(name, 0)}" for name in state.VALID_STATES)
            + f" (kopā {self.total}, iespējoti {self.enabled})",
        ]
        lines.extend(self.document_lines())
        run = self.run_stats
        lines.append(
            "Šajā piegājienā: "
            f"DONE={run['ok']} SKIPPED={run['skipped']} ERROR={run['error']} "
            f"objekti={run['objects_copied']}"
        )
        if self.recovered:
            lines.append("Atjaunoti pēc pārtraukuma: " + ", ".join(self.recovered))
        if self.aborted:
            lines.append(f"Piegājiens pārtraukts: {self.stop_reason}")
        if self.started:
            lines.append(f"Sākums: {self.started} | Beigas: {self.finished}")
        return "\n".join(lines)


@dataclass
class RetryResult:
    """What retry_errors() / retry_interrupted() did."""

    touched: list[str] = field(default_factory=list)
    summary: BatchSummary | None = None

    def format(self) -> str:
        text = f"Pārlikti uz WAITING: {len(self.touched)}"
        if self.touched:
            text += ": " + ", ".join(self.touched)
        lines = [text]
        if self.summary is not None:
            lines.append(self.summary.format())
        return "\n".join(lines)


class BatchQueue:
    """The persistent queue of one JOB folder.

    `adapter` is duck typed and must offer `run_job(request) -> JobResult`; the
    optional `close_documents(under_dir=...)` is used to clean up after a crash.
    Nothing here imports COM, so the whole class is testable without Illustrator.
    """

    def __init__(
        self,
        project: JobProject,
        *,
        adapter=None,
        logger: logging.Logger | None = None,
        state_path: str | Path | None = None,
        session_id: str = "",
    ) -> None:
        self.project = project
        self.adapter = adapter
        self.log = logger or logging.getLogger("pdf_ai_batch.queue")
        self.state_path = Path(state_path) if state_path else project.state_path
        self.document = state.load_state(
            self.state_path,
            job_root=project.root,
            session_id=session_id or new_run_id(),
        )

    # ------------------------------------------------------------------- opening

    @classmethod
    def open(
        cls,
        project: JobProject,
        *,
        adapter=None,
        logger: logging.Logger | None = None,
        session_id: str = "",
        recover: bool = True,
    ) -> "BatchQueue":
        """Open the queue: quarantine a broken state.json, then recover RUNNING."""
        queue = cls(project, adapter=adapter, logger=logger, session_id=session_id)
        queue.quarantine_state()
        if recover:
            queue.recover_running()
        return queue

    def quarantine_state(self) -> Path | None:
        """Keep a copy of a broken state.json and report why it was not trusted.

        Items that could still be read are kept; a fully unreadable file is copied
        aside (never silently deleted) so the caller can rebuild the queue.
        """
        problems = list(self.document.problems)
        if not problems:
            return None

        for problem in problems:
            self.log.warning("state.json problēma: %s", problem)

        if not self.state_path.is_file():
            return None

        stamp = state.now_stamp().replace("-", "").replace(":", "").replace(" ", "-")
        backup = self.state_path.with_name(f"{self.state_path.stem}.corrupt-{stamp}.json")
        try:
            backup.write_bytes(self.state_path.read_bytes())
            self.log.warning("Saglabāju bojāto state.json kā %s", backup.name)
        except OSError as exc:  # noqa: BLE001 - reporting must not fail the run
            self.log.warning("Nevar nokopēt bojāto state.json: %s", exc)
            return None
        return backup

    def recover_running(self) -> list[str]:
        """Stale RUNNING items become INTERRUPTED (never DONE, never stuck).

        A killed attempt may have left a partial output AI behind. It is removed when
        it was written during that attempt, otherwise the next RETRY/CONTINUE would
        report SKIP ("output jau eksistē") instead of processing the page.
        """
        recovered = state.recover_running(self.document)
        if recovered:
            for job_id in recovered:
                item = self.document.find(job_id)
                if item is not None:
                    self._discard_interrupted_output(item)
            self.save()
            self.log.warning(
                "Atjaunoju pārtrauktos elementus (%s) -> INTERRUPTED", ", ".join(recovered)
            )
        return recovered

    def _discard_interrupted_output(self, item: state.QueueItem) -> None:
        """Remove an output file that the interrupted attempt was still writing."""
        target = Path(item.output)
        try:
            if not target.exists():
                return
            started = _stamp_to_epoch(item.started)
            if started is not None and target.stat().st_mtime + 1.0 < started:
                # older than the interrupted attempt: not ours, keep it
                return
            target.unlink()
            self.log.warning("Izdzēsu pārtrauktā mēģinājuma output failu %s", target.name)
        except OSError as exc:  # noqa: BLE001 - recovery must not fail the queue
            self.log.warning("Nevar izdzēst pārtraukto output failu %s: %s", target, exc)

    # --------------------------------------------------------------------- basics

    def items(self) -> list[state.QueueItem]:
        return list(self.document.items)

    def save(self) -> Path:
        """Persist state.json atomically."""
        return state.save_state(self.state_path, self.document)

    def counts(self) -> dict[str, int]:
        return state.summary(self.document)

    def document_progress(self) -> list[dict]:
        """Per document progress rows (documents in queue order)."""
        return state.document_summaries(self.document)

    def documents(self) -> list[str]:
        """Document ids present in the queue, in queue order."""
        return self.document.document_ids()

    def items_of(self, pdf: str | Path) -> list[state.QueueItem]:
        """Items of one document (only that PDF)."""
        return self.document.items_of(pdf)

    def find(self, item_id: str | int, *, pdf: str | Path | None = None) -> state.QueueItem:
        item = self.document.find(item_id, pdf=pdf)
        if item is None:
            matches = self.document.candidates(item_id)
            if len(matches) > 1:
                documents = ", ".join(sorted({match.document for match in matches}))
                raise QueueError(
                    f"elements '{item_id}' ir vairākos dokumentos ({documents}) - "
                    "norādi job_id (piem. manualis_p001) vai izvēlies dokumentu"
                )
            raise QueueError(f"elements nav atrasts: {item_id}")
        return item

    def find_or_none(self, item_id: str | int, *, pdf: str | Path | None = None) -> state.QueueItem | None:
        return self.document.find(item_id, pdf=pdf)

    def problems(self) -> list[str]:
        return list(self.document.problems)

    # -------------------------------------------------------------------- status

    def status_rows(self) -> list[tuple[str, str, str, str]]:
        """(pdf_id, page, state, output) rows for the CLI table, in queue order."""
        rows: list[tuple[str, str, str, str]] = []
        for item in self.document.items:
            label = item.state if item.enabled else f"{item.state} (off)"
            rows.append((item.document, f"{item.page:03d}", label, item.output))
        return rows

    def status_table(self) -> str:
        """Compact PDF / PAGE / STATE / OUTPUT table plus the project summary."""
        counts = self.counts()
        rows = self.status_rows()
        width = max(3, min(24, max((len(row[0]) for row in rows), default=3)))
        lines = [f"{'PDF':<{width}} PAGE  STATE         OUTPUT"]
        for pdf_id, page, label, output in rows:
            lines.append(f"{pdf_id:<{width}} {page}   {label:<13} {output}")
        lines.append("")
        lines.append(f"PDFs: {counts.get('pdfs', 0)} | Lapas kopā: {counts['total']}")
        for row in self.document_progress():
            per_pdf = row.get("counts") or {}
            lines.append(
                f"  {row.get('pdf', row.get('pdf_id', '?'))}: "
                f"{row.get('processed', 0)}/{row.get('pages', 0)} apstrādātas | "
                + " ".join(f"{name}={per_pdf.get(name, 0)}" for name in state.VALID_STATES)
            )
        lines.append(
            "Kopā: "
            + " ".join(f"{name}={counts.get(name, 0)}" for name in state.VALID_STATES)
            + f" (kopā {counts['total']}, iespējoti {counts['enabled']}, rindā {counts['runnable']})"
        )
        details = [item for item in self.document.items if item.state in (state.ERROR, state.INTERRUPTED)]
        if details:
            lines.append("")
            for item in details:
                lines.append(
                    f"{item.job_id}: {item.state} | {item.error_type or '-'} | {item.error_message or '-'}"
                )
        return "\n".join(lines)

    def summary(
        self,
        *,
        outcomes: Sequence[RunOutcome] | None = None,
        recovered: Sequence[str] | None = None,
        started: str = "",
        aborted: bool = False,
        stop_reason: str = "",
    ) -> BatchSummary:
        counts = self.counts()
        return BatchSummary(
            counts=counts,
            total=counts["total"],
            enabled=counts["enabled"],
            runnable=counts["runnable"],
            outcomes=list(outcomes or []),
            session_id=self.document.session_id,
            started=started,
            finished=state.now_stamp(),
            aborted=aborted,
            stop_reason=stop_reason,
            recovered=list(recovered or []),
            documents=self.document_progress(),
        )

    # -------------------------------------------------------------------- build

    def build_queue(
        self,
        *,
        pdf: str | Path | None = None,
        pdfs: Iterable[str | Path] | None = None,
        pages: str | Iterable[int] | None = None,
        template: str | None = None,
        layer: str | None = None,
        overwrite: bool | None = None,
        template_mode: str = "auto",
        plan: "PagePlan | ProjectPlan | None" = None,
        reset: bool = False,
    ) -> list[state.QueueItem]:
        """Plan the pages of one or more PDFs and merge them into state.json.

        Scope: `pdf` = one document, `pdfs` = a list of documents, neither = the whole
        project (every configured document, then any extra PDF found in JOB/PDF).

        Merge rules (per document, unchanged since milestone 2):

        * pages that are new to the queue are added as WAITING
        * existing items keep their state/attempts/error history; only the plan
          fields (template, output, layer, mode, enabled) are refreshed
        * items that are no longer part of the plan of a **planned** document are
          disabled, never dropped
        * items of documents that were **not** planned keep their state untouched
          (a missing PDF must not lose anything)
        * a missing, disabled or unplannable document has its items disabled (never
          reset), so nothing from it can run until it is back
        * reset=True makes every planned page a fresh WAITING item

        The queue is re-ordered to the documented deterministic order: document order
        (config order) first, then page number ascending.
        """
        if plan is None:
            targets = None
            if pdf is not None:
                targets = [pdf]
            elif pdfs is not None:
                targets = list(pdfs)
            plan = pagejob.plan_project(
                self.project,
                pdfs=targets,
                pages=pages,
                template=template,
                layer=layer,
                overwrite=bool(overwrite),
                template_mode=template_mode,
            )

        if isinstance(plan, PagePlan):  # a single document plan (legacy callers, tests)
            documents = [pagejob.document_from_page_plan(plan)]
        else:
            documents = list(plan.documents)

        planned: dict[str, state.QueueItem] = {}
        planned_documents: set[str] = set()
        for document in documents:
            for warning in document.warnings:
                self.log.warning("Plāna brīdinājums: %s", warning)
            planned_documents.add(document.pdf_id)
            if document.missing or document.status == pagejob.DOC_STATUS_PLAN_ERROR:
                self._disable_document(document.pdf_id, f"dokuments nav pieejams ({document.status})")
                continue
            for job in document.pages:
                planned[job.job_id] = self._item_from_job(job, reset=reset)

        for item in planned.values():
            self.document.replace_item(item)

        for index, item in enumerate(list(self.document.items)):
            if item.job_id in planned or not item.enabled:
                continue
            if item.document not in planned_documents:
                continue  # not planned in this pass: leave its state alone
            self.document.items[index] = replace(item, enabled=False, updated=state.now_stamp())
            self.log.info("Izslēdzu %s (vairs nav plānā)", item.job_id)

        self._sort_items([document.pdf_id for document in documents])
        self.save()

        additions = [item.job_id for item in planned.values()]
        self.log.info(
            "Queue: %s dokumenti, %s lapas | %s | %s",
            len(documents),
            len(planned),
            ", ".join(document.pdf_name for document in documents) or "(neviens)",
            ", ".join(additions[:5]) + ("..." if len(additions) > 5 else ""),
        )
        return self.items()

    def _disable_document(self, pdf_id: str, reason: str) -> int:
        """Disable every item of one document without touching its state/history."""
        disabled = 0
        for index, item in enumerate(list(self.document.items)):
            if item.document != pdf_id or not item.enabled:
                continue
            self.document.items[index] = replace(item, enabled=False, updated=state.now_stamp())
            disabled += 1
        if disabled:
            self.log.info("Izslēdzu %s elementus (%s): %s", disabled, pdf_id, reason)
        return disabled

    def _sort_items(self, order: Sequence[str]) -> None:
        """Deterministic queue order: document order first, then page ascending."""
        position = {pdf_id: index for index, pdf_id in enumerate(order)}
        self.document.items.sort(
            key=lambda item: (position.get(item.document, len(position)), item.document, item.page)
        )

    def ensure_built(self, **build_kwargs) -> list[state.QueueItem]:
        """Build the queue when state.json does not hold any item yet."""
        if not self.document.items:
            return self.build_queue(**build_kwargs)
        return self.items()

    def _item_from_job(self, job: pagejob.PageJob, *, reset: bool = False) -> state.QueueItem:
        """Merge one planned page into the queue, keeping the run history."""
        values = {
            "job_id": job.job_id,
            "page": job.page,
            "pdf": contract_path(job.pdf),
            "template": contract_path(job.template),
            "output": contract_path(job.output),
            "pdf_id": job.pdf_id or pdf_id_for(job.pdf),
            "layer": job.layer,
            "template_mode": job.mode,
            "clear_layer": job.clear_layer,
            "overwrite": job.overwrite,
            "enabled": job.enabled,
        }
        existing = self.document.find(job.job_id)
        if existing is None or reset:
            return state.new_item(**values)
        return replace(existing, **values, updated=state.now_stamp())

    # ---------------------------------------------------------------------- run

    def run_next(self, *, progress: ProgressCallback | None = None) -> RunOutcome | None:
        """Run the first runnable item. None means: nothing to do."""
        candidates = self.document.runnable()
        if not candidates:
            self.log.info("Nav neviena izpildāma elementa")
            return None
        self.close_leftovers()
        return self._run_one(candidates[0], progress=progress)

    def run_all_enabled(
        self,
        *,
        progress: ProgressCallback | None = None,
        rebuild: bool = True,
        build_kwargs: dict | None = None,
    ) -> BatchSummary:
        """Full pass: refresh the plan from the project, then run the backlog.

        Runs every enabled WAITING and INTERRUPTED item; DONE and SKIPPED are never
        touched, ERROR waits for an explicit retry_errors().
        """
        recovered = self.recover_running()
        if rebuild:
            try:
                self.build_queue(**(build_kwargs or {}))
            except (PagePlanError, OSError) as exc:
                self.log.error("Nevar izveidot rindu: %s", exc)
                summary = self.summary(recovered=recovered)
                summary.aborted = True
                summary.stop_reason = str(exc)
                return summary
        goals = state.RUNNABLE_STATES
        return self._run_selection(
            self._selection(goals), progress=progress, recovered=recovered
        )

    def run_documents(
        self,
        pdfs: Sequence[str | Path],
        *,
        progress: ProgressCallback | None = None,
        limit: int | None = None,
        rebuild: bool = False,
        build_kwargs: dict | None = None,
    ) -> BatchSummary:
        """Run the backlog of specific documents (the GUI's "RUN CURRENT PDF").

        The whole project plan is refreshed first (so every document is present in the
        queue and stays WAITING), but only the pages of the given documents are run.
        Every other PDF keeps its state exactly as it is.
        """
        recovered = self.recover_running()
        if rebuild:
            try:
                self.build_queue(**(build_kwargs or {}))
            except (PagePlanError, OSError) as exc:
                self.log.error("Nevar izveidot rindu: %s", exc)
                summary = self.summary(recovered=recovered)
                summary.aborted = True
                summary.stop_reason = str(exc)
                return summary
        return self._run_selection(
            self._selection(state.RUNNABLE_STATES, limit=limit, pdfs=pdfs),
            progress=progress,
            recovered=recovered,
        )

    def continue_queue(
        self,
        *,
        progress: ProgressCallback | None = None,
        limit: int | None = None,
        ensure: bool = True,
        build_kwargs: dict | None = None,
    ) -> BatchSummary:
        """Resume after a restart: WAITING + INTERRUPTED, nothing else.

        ERROR stays ERROR (use retry_errors), DONE and SKIPPED are finished. A
        stale RUNNING item is recovered as INTERRUPTED first and then run, so
        "kill the process and continue" always finishes the interrupted page.
        """
        recovered = self.recover_running()
        if ensure and not self.document.items:
            try:
                self.build_queue(**(build_kwargs or {}))
            except (PagePlanError, OSError) as exc:
                self.log.error("Nevar izveidot rindu: %s", exc)
                summary = self.summary(recovered=recovered)
                summary.aborted = True
                summary.stop_reason = str(exc)
                return summary
        return self._run_selection(
            self._selection(state.RUNNABLE_STATES, limit=limit),
            progress=progress,
            recovered=recovered,
        )

    def retry_errors(self, *, run: bool = False, progress: ProgressCallback | None = None) -> RetryResult:
        """ERROR -> WAITING. With run=True the retried items are executed at once."""
        return self._requeue(state.RETRY_ERROR_STATES, run=run, progress=progress)

    def retry_interrupted(self, *, run: bool = False, progress: ProgressCallback | None = None) -> RetryResult:
        """INTERRUPTED -> WAITING (used after a crash or a manual stop)."""
        return self._requeue(state.RETRY_INTERRUPTED_STATES, run=run, progress=progress)

    def run_items(
        self,
        item_ids: Iterable[str | int],
        *,
        progress: ProgressCallback | None = None,
        limit: int | None = None,
    ) -> BatchSummary:
        """Run exactly these items (job_id, page number or output file name).

        Used by the GUI's "run selected": only runnable items (enabled WAITING or
        INTERRUPTED) are executed - `DONE` and `SKIPPED` need an explicit
        `reset_item()`, `ERROR` needs `retry_errors()`. An unknown id raises
        QueueError, so a selection can never be silently dropped.
        """
        wanted = {self.find(item_id).job_id for item_id in item_ids}
        selection = [item for item in self._selection(state.RUNNABLE_STATES) if item.job_id in wanted]
        if limit:
            selection = selection[:limit]
        return self._run_selection(selection, progress=progress)

    def reload(self, *, recover: bool = False) -> list[str]:
        """Re-read state.json from disk (another process may have written it).

        `recover=False` on purpose: while a worker of this process is running, the
        `RUNNING` item belongs to that worker and must not be turned into
        `INTERRUPTED`. Startup recovery stays in `open()` / the CLI.
        """
        self.document = state.load_state(
            self.state_path,
            job_root=self.project.root,
            session_id=self.document.session_id,
        )
        self.quarantine_state()
        return self.recover_running() if recover else []

    def reconcile_document(self, pdf: str | Path) -> dict:
        """Explicitly reconcile one document (page count drift). Returns the report.

        The config is rewritten as version 2 with the same order of documents, the
        stored pages keep their settings, added pages get the defaults and removed
        pages move to `removed_pages`. Nothing else in the project is touched.
        """
        _config, report = pagejob.apply_reconcile(self.project, pdf)
        self.log.info(
            "RECONCILE %s | stored %s -> current %s | added %s | removed %s | restored %s",
            report.get("pdf"),
            report.get("stored"),
            report.get("current"),
            report.get("added"),
            report.get("removed"),
            report.get("restored"),
        )
        return report

    def skip_item(
        self,
        item_id: str | int,
        message: str = "Manuāli izlaists",
        *,
        pdf: str | Path | None = None,
    ) -> state.QueueItem:
        """Mark one item SKIPPED (DONE must be reset first, RUNNING cannot be skipped)."""
        item = self.find(item_id, pdf=pdf)
        if item.state == state.RUNNING:
            raise QueueError(f"{item.job_id} pašlaik darbojas (RUNNING) - nevar izlaist")
        if item.state == state.DONE:
            raise QueueError(f"{item.job_id} ir DONE - vispirms reset_item()")
        updated = state.mark_skipped(item, message)
        self.document.replace_item(updated)
        self.save()
        self.log.info("SKIP %s | %s", item.job_id, message)
        return updated

    def reset_item(self, item_id: str | int, *, pdf: str | Path | None = None) -> state.QueueItem:
        """Back to WAITING, whatever the state was (including DONE and SKIPPED)."""
        item = self.find(item_id, pdf=pdf)
        updated = state.mark_waiting(item)
        self.document.replace_item(updated)
        self.save()
        self.log.info("RESET %s -> WAITING", item.job_id)
        return updated

    def set_enabled(
        self,
        item_id: str | int,
        enabled: bool,
        *,
        pdf: str | Path | None = None,
    ) -> state.QueueItem:
        """Enable/disable an item without changing its state history."""
        item = self.find(item_id, pdf=pdf)
        updated = replace(item, enabled=bool(enabled), updated=state.now_stamp())
        self.document.replace_item(updated)
        self.save()
        self.log.info("%s %s", "Ieslēdzu" if enabled else "Izslēdzu", item.job_id)
        return updated

    # ------------------------------------------------------------------- engine

    def duplicate_outputs(self, items: Sequence[state.QueueItem] | None = None) -> dict[str, list[str]]:
        """Output file names that more than one item would write (collision check).

        Documents are processed separately, but they all write into the same AI_OUT:
        page 1 of `manualis.pdf` and page 1 of `appendix.pdf` must never end up in the
        same file. The default output scheme is PDF aware, this catches the rest (a
        hand edited plan, two documents that resolve to one name, ...).
        """
        seen: dict[str, list[str]] = {}
        for item in self.document.items if items is None else items:
            seen.setdefault(Path(item.output).name.lower(), []).append(item.job_id)
        return {name: ids for name, ids in seen.items() if len(ids) > 1}

    def _duplicate_guard(
        self, selection: Sequence[state.QueueItem]
    ) -> tuple[dict[str, list[str]], BatchSummary | None]:
        """(collisions, summary-to-return). A collision aborts the pass, never runs."""
        collisions = self.duplicate_outputs(selection)
        if not collisions:
            return {}, None
        name, ids = next(iter(sorted(collisions.items())))
        reason = f"dublēti output ceļi {name}: {', '.join(ids)}"
        self.log.error("Pārtraucu piegājienu: %s", reason)
        summary = self.summary(aborted=True, stop_reason=reason)
        return collisions, summary

    def _selection(
        self,
        states: Sequence[str],
        *,
        limit: int | None = None,
        pdfs: Sequence[str | Path] | None = None,
    ) -> list[state.QueueItem]:
        """Enabled items in the given states, in queue order (optionally one document)."""
        wanted: set[str] | None = None
        if pdfs is not None:
            wanted = {pdf_id_for(pdf) for pdf in pdfs}
        items = [
            item
            for item in self.document.items
            if item.enabled
            and item.state in states
            and (wanted is None or item.document in wanted)
        ]
        return items[:limit] if limit else items

    def _requeue(
        self,
        states: Sequence[str],
        *,
        run: bool = False,
        progress: ProgressCallback | None = None,
    ) -> RetryResult:
        wanted = set(states)
        touched: list[str] = []
        for index, item in enumerate(list(self.document.items)):
            if item.state not in wanted:
                continue
            self.document.items[index] = state.mark_waiting(item)
            touched.append(item.job_id)
        if touched:
            self.save()
            self.log.info("Pārliku uz WAITING: %s", ", ".join(touched))

        result = RetryResult(touched=touched)
        if run and touched:
            selection = [self.document.find(job_id) for job_id in touched]
            result.summary = self._run_selection(
                [item for item in selection if item is not None and item.runnable],
                progress=progress,
            )
        return result

    def _run_selection(
        self,
        items: Sequence[state.QueueItem],
        *,
        progress: ProgressCallback | None = None,
        recovered: Sequence[str] = (),
    ) -> BatchSummary:
        """Run a selection of items; one bad page never stops the rest."""
        started = state.now_stamp()
        selection = [item for item in items if item.runnable]
        if not selection:
            self.log.info("Nav izpildāmu elementu")
            return self.summary(recovered=recovered, started=started)

        collisions, collision_summary = self._duplicate_guard(selection)
        if collision_summary is not None:
            collision_summary.recovered = list(recovered)
            collision_summary.started = started
            return collision_summary

        self.close_leftovers()
        outcomes: list[RunOutcome] = []
        aborted = False
        stop_reason = ""

        for item in selection:
            current = self.document.find(item.job_id)
            if current is None or not current.runnable:
                continue
            outcome = self._run_one(current, progress=progress)
            outcomes.append(outcome)
            if outcome.abort:
                aborted = True
                stop_reason = f"{outcome.job_id}: {outcome.message}"
                self.log.error("Pārtraucu piegājienu: %s", stop_reason)
                break

        return self.summary(
            outcomes=outcomes,
            recovered=recovered,
            started=started,
            aborted=aborted,
            stop_reason=stop_reason,
        )

    def close_leftovers(self) -> int:
        """Close documents a crashed run left open (AI_OUT only, never the rest)."""
        closer = getattr(self.adapter, "close_documents", None)
        if closer is None:
            return 0
        try:
            closed = closer(under_dir=self.project.output_dir)
        except TypeError:  # an adapter without the under_dir parameter
            try:
                closed = closer()
            except Exception as exc:  # noqa: BLE001
                self.log.warning("Nevar aizvērt dokumentus: %s", exc)
                return 0
        except Exception as exc:  # noqa: BLE001 - cleanup must never break a run
            self.log.warning("Nevar aizvērt dokumentus: %s", exc)
            return 0
        count = int(closed or 0)
        if count:
            self.log.info(CLOSE_LEFTOVERS_NOTE, count)
        return count

    def _discard_failed_output(self, item: state.QueueItem, *, copied_now: bool, since: float) -> None:
        """Remove what a FAILED attempt left behind.

        Why: the template copy (or a partially saved AI) would otherwise make the
        next attempt SKIP with "output jau eksistē", so an ERROR could never be
        fixed by RETRY/CONTINUE. `copied_now` means Python copied the file in this
        attempt; otherwise only a file touched during the attempt is removed, so a
        finished output from an earlier run is never deleted by accident.
        """
        target = Path(item.output)
        try:
            if not target.exists():
                return
            if not copied_now:
                try:
                    touched = target.stat().st_mtime >= since - 1.0
                except OSError:
                    touched = True
                if not touched:
                    return
            target.unlink()
            self.log.warning("Izdzēsu nepabeigto output failu %s", target.name)
        except OSError as exc:  # noqa: BLE001 - cleanup must never break the queue
            self.log.warning("Nevar izdzēst nepabeigto output failu %s: %s", target, exc)

    def _run_one(self, item: state.QueueItem, *, progress: ProgressCallback | None = None) -> RunOutcome:
        """Run one item: RUNNING -> (DONE | ERROR | SKIPPED), persisted on both ends."""
        if self.adapter is None:
            raise QueueError("Nav pievienots adapteris - run_job nav iespējams")
        started_clock = time.monotonic()
        started_epoch = time.time()
        run_id = new_run_id()

        item = state.mark_running(item, run_id)
        self.document.replace_item(item)
        self.save()  # RUNNING is on disk BEFORE Illustrator is asked
        self.log.info("START %s | %s lapa %s | %s", item.job_id, item.pdf_name, item.page, run_id)

        copied_now = False
        if item.template_mode == TEMPLATE_MODE_COPY:
            prep = pagejob.prepare_output_copy(
                item.template, item.output, item.overwrite, self.log
            )
            if prep.skipped:
                item = state.mark_skipped(item, prep.reason)
                self.document.replace_item(item)
                self.save()
                self.log.info("SKIP %s | %s", item.job_id, prep.reason)
                return self._report(item, run_id, started_clock, message=prep.reason, progress=progress)
            if prep.failed:
                # a missing template or an unwritable output is an ERROR, never a SKIP
                item = state.mark_error(item, run_id, "OUTPUT_PREP_FAILED", prep.reason)
                self.document.replace_item(item)
                self.save()
                self.log.error("ERROR %s | OUTPUT_PREP_FAILED | %s", item.job_id, prep.reason)
                return self._report(
                    item, run_id, started_clock, message=item.error_message, progress=progress
                )
            copied_now = prep.ok

        try:
            result = self.adapter.run_job(item.request(run_id))
        except Exception as exc:  # noqa: BLE001 - adapter/COM failure of THIS item
            error_type = "COM" if type(exc).__name__ in DEFAULT_ABORT_TYPES else "ADAPTER"
            item = state.mark_error(item, run_id, error_type, f"{type(exc).__name__}: {exc}")
            self._discard_failed_output(item, copied_now=copied_now, since=started_epoch)
            self.document.replace_item(item)
            self.save()
            self.log.error("ERROR %s | %s | %s", item.job_id, error_type, item.error_message)
            return self._report(
                item, run_id, started_clock, message=item.error_message, abort=True, progress=progress
            )

        if result.status == STATUS_OK:
            ready, reason = output_ready(item.output)
            if ready:
                item = state.mark_done(item, run_id)
                message = ""
                self.log.info(
                    "DONE %s | %s | objekti=%s", item.job_id, item.output, result.objects_copied
                )
            else:
                # the worker said OK, but there is no usable output: ERROR, never DONE
                item = state.mark_error(item, run_id, "OUTPUT_MISSING", reason)
                message = item.error_message
                self._discard_failed_output(item, copied_now=copied_now, since=started_epoch)
                self.log.error("ERROR %s | OUTPUT_MISSING | %s", item.job_id, reason)
        elif result.status == STATUS_SKIP:
            item = state.mark_skipped(item, result.message or "worker atgrieza SKIP")
            message = item.error_message
            self.log.info("SKIP %s | %s", item.job_id, message)
        else:
            item = state.mark_error(item, run_id, result.error_type or "WORKER_ERROR", result.message)
            message = item.error_message
            self._discard_failed_output(item, copied_now=copied_now, since=started_epoch)
            self.log.error("ERROR %s | %s | %s", item.job_id, item.error_type, item.error_message)

        self.document.replace_item(item)
        self.save()  # the outcome is on disk immediately after the item
        return self._report(
            item,
            run_id,
            started_clock,
            message=message,
            objects_copied=result.objects_copied,
            stats=result.stats,
            progress=progress,
        )

    @staticmethod
    def _report(
        item: state.QueueItem,
        run_id: str,
        started_clock: float,
        *,
        message: str = "",
        objects_copied: int = 0,
        stats: dict | None = None,
        abort: bool = False,
        progress: ProgressCallback | None = None,
    ) -> RunOutcome:
        outcome = RunOutcome(
            job_id=item.job_id,
            page=item.page,
            state_name=item.state,
            output=item.output,
            pdf_id=item.document,
            pdf=item.pdf_name,
            error_type=item.error_type,
            message=message or item.error_message,
            objects_copied=objects_copied,
            stats=dict(stats or {}),
            attempts=item.attempts,
            run_id=run_id,
            seconds=round(time.monotonic() - started_clock, 2),
            abort=abort,
        )
        if progress is not None:
            progress(outcome)
        return outcome
