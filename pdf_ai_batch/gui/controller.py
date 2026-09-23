"""All GUI logic in one place: NO Tk, NO COM, NO direct state.json writes.

The GUI is a thin presentation layer, so every action a button performs lives here
as a plain method that can be unit tested without a display:

    PROJECT tab  new_project / open_project / project_folders / add_pdf / add_templates
    PDF tab      list_pdfs / select_pdf / pdf_entry
    MAPPING tab  mapping_rows / set_enabled / assign_template / use_default_template /
                 auto_assign_templates / reset_pages / validate / template_choices
    RUN tab      run_selected / run_all_enabled / continue_queue / retry_errors /
                 retry_interrupted / progress / queue_summary / has_running_items

Everything below it is the proven core: `core/project.py` (folders),
`core/pdf_info.py` (page count), `core/template_mapper.py` (natural sort, master
exclusion), `core/naming.py` (output names), `core/config.py` (config.json),
`core/validation.py` (preflight), `core/pagejob.py` (the page plan),
`core/queue.py` + `core/state.py` (queue, transitions), and - only for an explicit
health check or a run - `adapters/illustrator.py`.

Plan edits go to `CONFIG/config.json` (the plan source of truth) and are then
merged into `state.json` by `BatchQueue.build_queue`, which preserves the run
history. The GUI never edits state.json itself.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .. import paths
from ..adapters.illustrator import IllustratorAdapter
from ..core import config as cfg
from ..core import pagejob, state, validation
from ..core.pdf_info import PdfPageCountError, count_pages
from ..core.project import JobProject, ProjectError
from ..core.queue import BatchQueue, BatchSummary, QueueError
from ..core.template_mapper import build_page_plan, default_template, list_templates

LOGGER_NAME = "pdf_ai_batch.gui"


@dataclass(frozen=True)
class MappingRow:
    """One row of the MAPPING table (plan fields + queue state)."""

    page: int
    job_id: str
    enabled: bool
    template: str
    template_path: Path
    layer: str
    output: str
    output_path: Path
    state: str = state.WAITING
    attempts: int = 0
    error_type: str = ""
    error_message: str = ""

    @property
    def page_label(self) -> str:
        """Zero padded page number, exactly as the naming rules use it."""
        width = 3 if self.page < 1000 else 4
        return f"{self.page:0{width}d}"

    @property
    def use_label(self) -> str:
        return "[x]" if self.enabled else "[ ]"

    @property
    def detail(self) -> str:
        if self.error_message:
            return f"{self.error_type or 'ERROR'}: {self.error_message}"
        return ""


@dataclass(frozen=True)
class PdfEntry:
    """What the PDF tab shows for the selected PDF."""

    path: Path
    page_count: int
    count_method: str
    size_bytes: int
    config_status: str
    active: bool = False

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 1)


@dataclass(frozen=True)
class ProgressSnapshot:
    """Everything the RUN tab displays, derived from the queue state only."""

    total: int = 0
    processed: int = 0
    current_page: int = 0
    running_page: int = 0
    counts: dict[str, int] | None = None

    @property
    def fraction(self) -> float:
        if not self.total:
            return 0.0
        return min(1.0, self.processed / self.total)

    def current_label(self) -> str:
        if not self.total:
            return "Page --- / ---"
        page = self.running_page or self.current_page
        page_label = f"{page:03d}" if page else "---"
        return f"Page {page_label} / {self.total:03d}"

    def summary_lines(self) -> list[str]:
        counts = self.counts or {}
        return [
            f"DONE: {counts.get(state.DONE, 0)}",
            f"WAITING: {counts.get(state.WAITING, 0)}",
            f"RUNNING: {counts.get(state.RUNNING, 0)}",
            f"ERROR: {counts.get(state.ERROR, 0)}",
            f"SKIPPED: {counts.get(state.SKIPPED, 0)}",
            f"INTERRUPTED: {counts.get(state.INTERRUPTED, 0)}",
        ]


class ControllerError(RuntimeError):
    """Raised for GUI level misuse (no project, no PDF, unknown page)."""


class AppController:
    """Stateful façade between the GUI widgets and the core."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        adapter_factory: Callable[[], object] | None = None,
        timeout: float = 900.0,
        poll: float = 0.5,
    ) -> None:
        self.log = logger or logging.getLogger(LOGGER_NAME)
        self.timeout = float(timeout)
        self.poll = float(poll)
        #: RUN tab checkbox: replace existing output AIs (the CLI's --overwrite)
        self.overwrite_outputs = False
        self._project: JobProject | None = None
        self._active_pdf: Path | None = None
        self._queue: BatchQueue | None = None
        self._adapter: object | None = None
        self._adapter_factory = adapter_factory or self._default_adapter
        self._illustrator_state: bool | None = None
        self._last_checks: list[validation.CheckResult] = []

    # ------------------------------------------------------------------ project

    @property
    def project(self) -> JobProject | None:
        return self._project

    def new_project(self, root: str | Path) -> JobProject:
        """Create a JOB folder (structure included) and open it."""
        try:
            project = JobProject.open(root, create=True)
        except (ProjectError, OSError) as exc:
            raise ControllerError(str(exc)) from exc
        self.log.info("Jauns JOB: %s", project.root)
        return self._adopt(project)

    def open_project(self, root: str | Path) -> JobProject:
        """Open an existing JOB folder (created when missing, like the CLI)."""
        try:
            project = JobProject.open(root, create=True)
        except (ProjectError, OSError) as exc:
            raise ControllerError(str(exc)) from exc
        self.log.info("Atvēru JOB: %s", project.root)
        return self._adopt(project)

    def _adopt(self, project: JobProject) -> JobProject:
        self._project = project
        self._queue = None          # a new JOB means a new state file
        self._active_pdf = None
        self._illustrator_state = None
        self._last_checks = []
        pdfs = project.find_pdfs()
        if pdfs:
            self._active_pdf = pdfs[0]
        return project

    def project_folders(self) -> list[tuple[str, str, bool]]:
        """(label, absolute path, exists) for the six JOB folders."""
        project = self._require_project()
        folders = [
            ("PDF", project.pdf_dir),
            ("TEMPLATE", project.template_dir),
            ("CONFIG", project.config_dir),
            ("AI_OUT", project.output_dir),
            ("LOG", project.log_dir),
            ("ERROR", project.error_dir),
        ]
        return [(name, str(path), path.is_dir()) for name, path in folders]

    def add_pdf(self, sources: Sequence[str | Path]) -> tuple[list[str], list[str]]:
        """Copy PDFs into JOB/PDF. Returns (added, skipped)."""
        project = self._require_project()
        return self._copy_into(sources, project.pdf_dir, ".pdf")

    def add_templates(self, sources: Sequence[str | Path]) -> tuple[list[str], list[str]]:
        """Copy templates into JOB/TEMPLATE. Returns (added, skipped)."""
        project = self._require_project()
        added, skipped = self._copy_into(sources, project.template_dir, None)
        if added:  # a new template changes the plan; refresh the queue view
            try:
                self.queue.build_queue(pdf=self._active_name())
            except Exception as exc:  # noqa: BLE001 - an incomplete job must not crash the GUI
                self.log.warning("Nevar pārbūvēt rindu pēc template pievienošanas: %s", exc)
        return added, skipped

    def _copy_into(
        self, sources: Sequence[str | Path], folder: Path, suffix: str | None
    ) -> tuple[list[str], list[str]]:
        added: list[str] = []
        skipped: list[str] = []
        folder.mkdir(parents=True, exist_ok=True)
        for source in sources:
            path = Path(source)
            if not path.is_file() or (suffix and path.suffix.lower() != suffix):
                skipped.append(path.name)
                continue
            target = folder / path.name
            if target.exists():
                skipped.append(path.name)
                continue
            try:
                shutil.copy2(path, target)
            except OSError as exc:
                self.log.warning("Nevar nokopēt %s: %s", path.name, exc)
                skipped.append(path.name)
                continue
            added.append(target.name)
        if added:
            self.log.info("Pievienoju %s -> %s", ", ".join(added), folder.name)
        return added, skipped

    # ---------------------------------------------------------------------- pdf

    def list_pdfs(self) -> list[Path]:
        return self._require_project().find_pdfs()

    def select_pdf(self, name_or_path: str | Path) -> PdfEntry:
        """Make one PDF the active PDF of the GUI (MAPPING/RUN work on it)."""
        project = self._require_project()
        try:
            self._active_pdf = project.resolve_pdf(name_or_path)
        except ProjectError as exc:
            raise ControllerError(str(exc)) from exc
        entry = self.pdf_entry()
        self.log.info("Aktīvais PDF: %s (%s lapas)", entry.name, entry.page_count)
        return entry

    @property
    def active_pdf(self) -> Path | None:
        return self._active_pdf

    def pdf_entry(self) -> PdfEntry:
        """Page count (PyMuPDF, pypdf fallback), size and config status."""
        pdf = self._require_pdf()
        try:
            page_count, method = count_pages(pdf)
        except PdfPageCountError as exc:
            raise ControllerError(str(exc)) from exc
        return PdfEntry(
            path=pdf,
            page_count=page_count,
            count_method=method,
            size_bytes=pdf.stat().st_size,
            config_status=self._config_status(pdf),
            active=True,
        )

    def _config_status(self, pdf: Path) -> str:
        config = cfg.load_config(self._require_project().config_path)
        if not config:
            return "nav config.json (automātiskais plāns)"
        problems = cfg.validate_config(config)
        if problems:
            return "config.json nav derīgs: " + "; ".join(problems[:3])
        if str(config.get("pdf") or "") != pdf.name:
            return f"config.json apraksta citu PDF ({config.get('pdf')})"
        pages = len(cfg.page_entries(config))
        enabled = len(cfg.enabled_page_entries(config))
        return f"config.json: {pages} lapas, iespējotas {enabled}"

    def _active_name(self) -> str | None:
        return self._active_pdf.name if self._active_pdf else None

    # ------------------------------------------------------------------ helpers

    def _require_project(self) -> JobProject:
        if self._project is None:
            raise ControllerError("Nav atvērts neviens JOB")
        return self._project

    def _require_pdf(self) -> Path:
        if self._active_pdf is None:
            raise ControllerError("Nav izvēlēts PDF")
        if not self._active_pdf.is_file():
            raise ControllerError(f"PDF nav atrasts: {self._active_pdf}")
        return self._active_pdf

    # -------------------------------------------------------------------- queue

    @property
    def queue(self) -> BatchQueue:
        """The persistent queue of the active JOB (opened once per JOB).

        `BatchQueue.open` recovers a stale RUNNING item as INTERRUPTED - the GUI
        does not implement recovery, it only shows the result.
        """
        project = self._require_project()
        if self._queue is None:
            self._queue = BatchQueue.open(project, adapter=self._adapter, logger=self.log)
            for problem in self._queue.problems():
                self.log.warning("state.json: %s", problem)
        return self._queue

    def refresh(self) -> list[str]:
        """Re-read state.json (another process may have written it)."""
        recovered: list[str] = []
        if self._queue is not None:
            recovered = self._queue.reload()
        self._last_checks = []
        return recovered

    def queue_summary(self) -> dict[str, int]:
        if self._queue is None:
            empty = {name: 0 for name in state.VALID_STATES}
            return {**empty, "total": 0, "enabled": 0, "runnable": 0}
        return self._queue.counts()

    # ------------------------------------------------------------------ mapping

    def mapping_rows(self) -> list[MappingRow]:
        """The MAPPING table: the page plan (config.json wins) plus queue state."""
        project = self._require_project()
        try:
            plan = pagejob.plan_pages(project, pdf=self._active_name(), pages=None)
        except Exception as exc:  # noqa: BLE001 - an incomplete job shows a message
            raise ControllerError(str(exc)) from exc

        rows: list[MappingRow] = []
        queue = self.queue
        for job in plan.pages:
            item = queue.find_or_none(job.job_id)
            rows.append(
                MappingRow(
                    page=job.page,
                    job_id=job.job_id,
                    enabled=job.enabled,
                    template=job.template.name if job.template else "",
                    template_path=job.template,
                    layer=job.layer,
                    output=job.output_name,
                    output_path=job.output,
                    state=item.state if item is not None else state.WAITING,
                    attempts=item.attempts if item is not None else 0,
                    error_type=item.error_type if item is not None else "",
                    error_message=item.error_message if item is not None else "",
                )
            )
        return rows

    def template_choices(self) -> list[str]:
        """Template files already inside JOB/TEMPLATE (natural sort)."""
        project = self._require_project()
        return [path.name for path in list_templates(project.template_dir)]

    def default_template_name(self) -> str:
        fallback = default_template(self._require_project().template_dir)
        return fallback.name if fallback else ""

    def set_enabled(self, pages: Iterable[int], enabled: bool) -> list[MappingRow]:
        """USE column of the MAPPING table (persisted in config.json)."""
        self._set_pages(pages, {"enabled": bool(enabled)})
        return self.mapping_rows()

    def assign_template(self, pages: Iterable[int], template: str | None) -> list[MappingRow]:
        """Set the per page template assignment without editing JSON by hand."""
        value = (template or "").strip() or None
        self._set_pages(pages, {"template": value})
        return self.mapping_rows()

    def use_default_template(self, pages: Iterable[int]) -> list[MappingRow]:
        """Back to the default template (entry template None -> defaults.template)."""
        return self.assign_template(pages, None)

    def auto_assign_templates(self) -> list[MappingRow]:
        """Positional auto mapping again (natural sort, MASTER excluded)."""
        project = self._require_project()
        pdf = self._require_pdf()
        page_count, _method = count_pages(pdf)
        planned, defaults, _fallback = build_page_plan(pdf, page_count, project.template_dir)

        previous = cfg.load_config(project.config_path)
        by_page = {int(entry.get("page", 0)): entry for entry in cfg.page_entries(previous)}
        for entry in planned:
            old = by_page.get(int(entry["page"]))
            if not old:
                continue
            entry["layer"] = old.get("layer") or entry["layer"]
            entry["enabled"] = bool(old.get("enabled", True))
            entry["output"] = old.get("output") or entry["output"]

        document = cfg.new_config(pdf.name, page_count, planned, defaults)
        if (previous.get("defaults") or {}).get("template"):
            document["defaults"]["template"] = previous["defaults"]["template"]
        self._write_config(document)
        self.log.info("Automātiskā template piešķire: %s lapas", page_count)
        return self.mapping_rows()

    def reset_pages(self, item_ids: Iterable[str | int]) -> list[str]:
        """RESET SELECTED: a core state transition, no config change."""
        queue = self.queue
        try:
            return [queue.reset_item(item_id).job_id for item_id in item_ids]
        except QueueError as exc:
            raise ControllerError(str(exc)) from exc

    # ----------------------------------------------------------- config writing

    def _ensure_config(self) -> dict:
        """Load config.json for the active PDF, or create it from the plan."""
        project = self._require_project()
        pdf = self._require_pdf()
        config = cfg.load_config(project.config_path)
        if config and not cfg.validate_config(config) and str(config.get("pdf") or "") == pdf.name:
            return config

        try:
            page_count, _method = count_pages(pdf)
        except PdfPageCountError as exc:
            raise ControllerError(str(exc)) from exc
        pages, defaults, _fallback = build_page_plan(pdf, page_count, project.template_dir)
        self.log.info("Izveidoju config.json priekš %s (%s lapas)", pdf.name, page_count)
        return cfg.new_config(pdf.name, page_count, pages, defaults)

    def _set_pages(self, pages: Iterable[int], changes: dict) -> dict:
        wanted = {int(page) for page in pages}
        if not wanted:
            raise ControllerError("Nav atlasīta neviena lapa")
        config = self._ensure_config()
        for entry in cfg.page_entries(config):
            if int(entry.get("page", 0)) in wanted:
                entry.update(changes)
        self._write_config(config)
        return config

    def _write_config(self, config: dict) -> None:
        """Validate, save atomically, then merge the plan into state.json."""
        problems = cfg.validate_config(config)
        if problems:
            raise ControllerError("Nederīgs config.json: " + "; ".join(problems[:5]))
        cfg.save_config(self._require_project().config_path, config)
        self.queue.build_queue(pdf=self._active_name())

    # --------------------------------------------------------------- validation

    def validate(self) -> list[validation.CheckResult]:
        """Validation report built ONLY from the core helpers.

        `core/validation.preflight` covers the JOB folders, the PDF, the template,
        the output name/folder, worker.jsx/cleanup.jsx/runtime and - when known -
        Illustrator. `core/config.validate_config` covers duplicate outputs, page
        ranges, layer and template extensions. Nothing is re-implemented here.
        """
        self._last_checks = self._build_checks()
        return self._last_checks

    def validation_report(self) -> str:
        checks = self._last_checks or self.validate()
        return validation.format_report(checks)

    def can_run(self) -> bool:
        """RUN is enabled only when the existing validation has no hard failure."""
        if self._project is None or self._active_pdf is None:
            return False
        checks = self._last_checks or self.validate()
        return not validation.has_failures(checks)

    def validation_failures(self) -> list[str]:
        """Human readable problems, for the status bar and the run tab."""
        checks = self._last_checks or self.validate()
        return [
            f"{check.name}: {check.detail}"
            for check in checks
            if not check.ok and not check.warning
        ]

    def _build_checks(self) -> list[validation.CheckResult]:
        project = self._project
        if project is None:
            return [validation.CheckResult("JOB mape", False, "nav atvērts neviens JOB")]

        checks = [validation.CheckResult("JOB mape", project.root.is_dir(), str(project.root))]
        if self._active_pdf is None:
            checks.append(validation.CheckResult("PDF fails", False, "nav izvēlēts PDF"))
            return checks
        if not self._active_pdf.is_file():
            checks.append(validation.CheckResult("PDF fails", False, f"nav atrasts: {self._active_pdf}"))
            return checks

        try:
            entry = self.pdf_entry()
        except ControllerError as exc:
            checks.append(validation.CheckResult("PDF lapas", False, str(exc)))
            return checks
        checks.append(validation.CheckResult("PDF fails", True, str(self._active_pdf)))
        checks.append(
            validation.CheckResult("PDF lapas", entry.page_count > 0, f"{entry.page_count} ({entry.count_method})")
        )

        try:
            rows = self.mapping_rows()
        except ControllerError as exc:
            checks.append(validation.CheckResult("Plāns", False, str(exc)))
            return checks
        checks.append(validation.CheckResult("Plāns", bool(rows), f"{len(rows)} lapas"))

        first = rows[0] if rows else None
        checks.extend(
            validation.preflight(
                project,
                pdf=self._active_pdf,
                page=first.page if first else 1,
                page_count=entry.page_count,
                template=first.template_path if first else None,
                output=first.output_path if first else None,
                worker_jsx=paths.worker_jsx(),
                cleanup_jsx=paths.cleanup_jsx(),
                runtime_dir=paths.runtime_dir(),
                illustrator_available=self._illustrator_state,
            )
        )

        distinct_templates: dict[str, Path] = {}
        for row in rows:
            distinct_templates[str(row.template_path)] = row.template_path
        for path in distinct_templates.values():
            checks.append(validation.check_file(f"Template {path.name}", path))

        config = cfg.load_config(project.config_path)
        if config:
            problems = cfg.validate_config(config)
            checks.append(
                validation.CheckResult("config.json", not problems, "; ".join(problems[:4]) if problems else "derīgs")
            )
        else:
            checks.append(
                validation.CheckResult("config.json", True, "nav (izmanto automātisko plānu)", warning=True)
            )
        return checks

    # -------------------------------------------------------------- illustrator

    @property
    def adapter(self):
        """The Illustrator adapter - created only for a health check or a run."""
        if self._adapter is None:
            self._adapter = self._adapter_factory()
        return self._adapter

    def _default_adapter(self) -> IllustratorAdapter:
        return IllustratorAdapter(
            worker_jsx=paths.worker_jsx(),
            runtime_dir=paths.runtime_dir(),
            timeout=self.timeout,
            poll_interval=self.poll,
            logger=self.log,
        )

    @property
    def illustrator_state(self) -> bool | None:
        """None = not checked yet, True/False = the result of the last health check."""
        return self._illustrator_state

    def check_illustrator(self) -> tuple[bool, str]:
        """Explicit health check: attach to Illustrator, launch only when needed."""
        try:
            adapter = self.adapter
            attached = bool(adapter.ensure_app())
            report = adapter.health_check() if hasattr(adapter, "health_check") else {"ok": attached}
            ok = bool(report.get("ok", attached))
            version = ""
            if hasattr(adapter, "app_info"):
                version = str(getattr(adapter.app_info(), "version", "") or "")
        except Exception as exc:  # noqa: BLE001 - a broken COM environment is a status
            self._illustrator_state = False
            message = f"Illustrator nav sasniedzams: {exc}"
            self.log.error(message)
            return False, message

        self._illustrator_state = ok
        if ok:
            message = f"Illustrator pieejams (versija {version})" if version else "Illustrator pieejams"
            self.log.info("Health check: %s", message)
        else:
            message = "Illustrator nav sasniedzams (COM)"
            self.log.warning("Health check: %s", message)
        return ok, message

    # ------------------------------------------------------------------ running

    def _run_action(self, action: Callable[..., BatchSummary], *, progress=None) -> BatchSummary:
        """Every run goes through the proven queue + adapter path."""
        self._require_project()
        self._require_pdf()
        queue = self.queue
        queue.adapter = self.adapter
        if not self.adapter.ensure_app():
            raise ControllerError("Illustrator nav sasniedzams (COM)")
        summary = action(progress=progress)
        self._last_checks = []  # state changed, validation is stale now
        return summary

    def _plan_kwargs(self) -> dict:
        """The plan arguments every run uses (active PDF + overwrite choice)."""
        return {"pdf": self._active_name(), "overwrite": self.overwrite_outputs}

    def run_selected(self, item_ids: Iterable[str | int], *, progress=None) -> BatchSummary:
        """RUN SELECTED: only WAITING/INTERRUPTED rows of the selection are run."""
        ids = list(item_ids)
        if not ids:
            raise ControllerError("Nav atlasīta neviena lapa")
        queue = self.queue
        queue.build_queue(**self._plan_kwargs())  # the items must exist
        try:
            return self._run_action(lambda progress: queue.run_items(ids, progress=progress), progress=progress)
        except QueueError as exc:
            raise ControllerError(str(exc)) from exc

    def run_all_enabled(self, *, progress=None) -> BatchSummary:
        """RUN ALL ENABLED: refresh the plan, then run the whole backlog."""
        queue = self.queue
        return self._run_action(
            lambda progress: queue.run_all_enabled(
                progress=progress, build_kwargs=self._plan_kwargs()
            ),
            progress=progress,
        )

    def continue_queue(self, *, progress=None) -> BatchSummary:
        """CONTINUE: WAITING + INTERRUPTED (a recovered RUNNING item included)."""
        queue = self.queue
        return self._run_action(
            lambda progress: queue.continue_queue(
                progress=progress, build_kwargs=self._plan_kwargs()
            ),
            progress=progress,
        )

    def retry_errors(self, *, progress=None) -> BatchSummary:
        queue = self.queue
        return self._run_action(
            lambda progress: (queue.retry_errors(run=True, progress=progress).summary or queue.summary()),
            progress=progress,
        )

    def retry_interrupted(self, *, progress=None) -> BatchSummary:
        queue = self.queue
        return self._run_action(
            lambda progress: (queue.retry_interrupted(run=True, progress=progress).summary or queue.summary()),
            progress=progress,
        )

    # ------------------------------------------------------------------ progress

    def progress(self) -> ProgressSnapshot:
        """Everything the RUN tab shows, derived from the queue state only."""
        counts = self.queue_summary()
        items = self._queue.document.items if self._queue is not None else []
        total = len(items)
        if total == 0:
            # nothing queued yet: fall back to the plan so the bar is not empty
            try:
                total = len(self.mapping_rows())
            except ControllerError:
                total = 0

        running = next((item for item in items if item.state == state.RUNNING), None)
        processed_pages = [
            item.page for item in items if item.state in (state.DONE, state.SKIPPED, state.ERROR)
        ]
        return ProgressSnapshot(
            total=total,
            processed=counts[state.DONE] + counts[state.SKIPPED] + counts[state.ERROR],
            current_page=max(processed_pages) if processed_pages else 0,
            running_page=running.page if running else 0,
            counts=counts,
        )

    def has_running_items(self) -> bool:
        """Used by the window close handler (recovery stays authoritative)."""
        if self._queue is None:
            return False
        return any(item.state == state.RUNNING for item in self._queue.document.items)
