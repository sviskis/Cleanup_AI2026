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
import tempfile
from dataclasses import dataclass, field
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
from ..preview.cache import PreviewCache

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
    pdf_id: str = ""

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
class DocumentProgress:
    """Cheap per document progress row (built from the queue state, no file reads)."""

    pdf_id: str
    name: str
    page_count: int = 0
    processed: int = 0
    current_page: int = 0
    counts: dict = field(default_factory=dict)

    @property
    def state_counts(self) -> dict:
        return {name: int((self.counts or {}).get(name, 0)) for name in state.VALID_STATES}


@dataclass(frozen=True)
class PdfEntry:
    """What the PDF tab shows for the selected PDF."""

    path: Path
    page_count: int
    count_method: str
    size_bytes: int
    config_status: str
    active: bool = False
    pdf_id: str = ""
    status: str = pagejob.DOC_STATUS_NEW
    missing: bool = False

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 1)


@dataclass(frozen=True)
class DocumentRow:
    """One row of the PDF tab: USE / PDF / PAGES / CONFIG STATUS / QUEUE STATUS.

    `status` is the document level state from `core/pagejob.py` (`OK`, `NEW`,
    `CONFIG STALE`, `MISSING PDF`, `PLAN ERROR`) and is never a silent change: a
    stale or missing document must be reconciled or restored explicitly.
    """

    pdf_id: str
    name: str
    path: Path
    page_count: int = 0
    stored_page_count: int = 0
    count_method: str = ""
    enabled: bool = True
    status: str = pagejob.DOC_STATUS_NEW
    missing: bool = False
    source: str = pagejob.PLAN_SOURCE_AUTO
    config_status: str = ""
    queue_status: str = ""
    counts: dict = field(default_factory=dict)
    active: bool = False

    @property
    def use_label(self) -> str:
        return "[x]" if self.enabled else "[ ]"

    @property
    def pages_label(self) -> str:
        if self.missing:
            return "---"
        if self.stored_page_count and self.stored_page_count != self.page_count:
            return f"{self.page_count} (stored {self.stored_page_count})"
        return str(self.page_count)

    @property
    def status_text(self) -> str:
        """CONFIG STATUS column: status plus where the plan comes from."""
        if self.missing:
            return pagejob.DOC_STATUS_MISSING
        if self.status == pagejob.DOC_STATUS_STALE:
            return (
                f"{pagejob.DOC_STATUS_STALE} (stored: {self.stored_page_count}, "
                f"current: {self.page_count})"
            )
        if self.status == pagejob.DOC_STATUS_OK:
            return f"OK ({self.source})"
        if self.status == pagejob.DOC_STATUS_PLAN_ERROR:
            return "PLAN ERROR"
        return f"nav config.json ({self.source})"

    @property
    def state_counts(self) -> dict:
        return {name: int((self.counts or {}).get(name, 0)) for name in state.VALID_STATES}


@dataclass(frozen=True)
class ProgressSnapshot:
    """Everything the RUN tab displays, derived from the queue state only."""

    total: int = 0
    processed: int = 0
    current_page: int = 0
    running_page: int = 0
    counts: dict[str, int] | None = None
    pdfs: int = 0
    document: str = ""
    document_total: int = 0
    documents: tuple = ()

    @property
    def fraction(self) -> float:
        if not self.total:
            return 0.0
        return min(1.0, self.processed / self.total)

    def current_label(self) -> str:
        """Project AND document progress, e.g. "appendix.pdf - lapa 014 / 018"."""
        page = self.running_page or self.current_page
        if not self.document:
            return f"Lapas --- / {self.total:03d}" if self.total else "Lapas --- / ---"
        page_label = f"{page:03d}" if page else "---"
        document_total = self.document_total or self.total
        return f"{self.document} - lapa {page_label} / {document_total:03d}"

    def summary_lines(self) -> list[str]:
        counts = self.counts or {}
        lines = [
            f"PDFs: {self.pdfs}",
            f"Lapas kopā: {self.total} (apstrādātas {self.processed})",
            f"DONE: {counts.get(state.DONE, 0)}",
            f"WAITING: {counts.get(state.WAITING, 0)}",
            f"RUNNING: {counts.get(state.RUNNING, 0)}",
            f"ERROR: {counts.get(state.ERROR, 0)}",
            f"SKIPPED: {counts.get(state.SKIPPED, 0)}",
            f"INTERRUPTED: {counts.get(state.INTERRUPTED, 0)}",
        ]
        return lines

    def document_lines(self) -> list[str]:
        """One line per document (used by the RUN tab's project view)."""
        lines: list[str] = []
        for row in self.documents:
            counts = getattr(row, "state_counts", {})
            lines.append(
                f"{row.name}: {counts.get(state.DONE, 0)}/{row.page_count} DONE"
                f" | WAITING {counts.get(state.WAITING, 0)}"
                f" | ERROR {counts.get(state.ERROR, 0)}"
                f" | SKIPPED {counts.get(state.SKIPPED, 0)}"
            )
        return lines


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
        self._preview_cache: PreviewCache | None = None

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

    # ----------------------------------------------------------------- documents

    def set_document_enabled(self, pdf: str | Path, enabled: bool) -> list[DocumentRow]:
        """USE column of the PDF tab: the document switch in config.json.

        A disabled document keeps its plan and its queue state; it is simply neither
        planned for a run nor run (the queue disables its items, never resets them).
        """
        project = self._require_project()
        name = Path(str(pdf)).name
        config = cfg.load_config(project.config_path)
        document = cfg.document_for(config, name)
        if document is None:
            document = cfg.new_document(name, 1, [], enabled=bool(enabled))
        else:
            document = dict(document)
            document["enabled"] = bool(enabled)
        cfg.save_config(project.config_path, cfg.replace_document(config, document))
        self.log.info("%s dokumentu %s", "Ieslēdzu" if enabled else "Izslēdzu", name)
        self._rebuild_queue()
        return self.documents()

    def reconcile_document(self, pdf: str | Path | None = None) -> dict:
        """RECONCILE a document after its PDF page count changed.

        Reaches `core.pagejob.apply_reconcile`: pages that are still there keep their
        settings, new pages become WAITING with the defaults, removed pages are
        archived in `removed_pages` (never silently deleted). Explicit only.
        """
        target = Path(str(pdf)).name if pdf else (self._active_pdf.name if self._active_pdf else None)
        if not target:
            raise ControllerError("Nav izvēlēts PDF")
        try:
            report = self.queue.reconcile_document(target)
        except (ProjectError, PdfPageCountError, OSError) as exc:
            raise ControllerError(str(exc)) from exc
        self._rebuild_queue()
        self.log.info(
            "RECONCILE %s: %s -> %s | +%s | -%s",
            target,
            report.get("stored"),
            report.get("current"),
            report.get("added"),
            report.get("removed"),
        )
        return report

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

    def documents(self) -> list[DocumentRow]:
        """Every document of the JOB: config order first, then unconfigured PDFs.

        The list comes from `core.pagejob.plan_project`, so it shows the same status
        the queue will use: `OK`, `NEW`, `CONFIG STALE`, `MISSING PDF`, `PLAN ERROR`.
        """
        project = self._require_project()
        config = cfg.load_config(project.config_path)
        try:
            plan = pagejob.plan_project(project)
        except (ProjectError, OSError) as exc:
            raise ControllerError(str(exc)) from exc

        counts_by_document = self._queue_counts()
        rows: list[DocumentRow] = []
        for document in plan.documents:
            counts = counts_by_document.get(
                document.pdf_id, {name: 0 for name in state.VALID_STATES}
            )
            rows.append(
                DocumentRow(
                    pdf_id=document.pdf_id,
                    name=document.pdf_name,
                    path=document.pdf,
                    page_count=document.current_page_count or document.page_count,
                    stored_page_count=document.stored_page_count,
                    count_method=document.count_method,
                    enabled=document.enabled,
                    status=document.status,
                    missing=document.missing,
                    source=document.source,
                    config_status=self._document_config_status(config, document),
                    queue_status=self._queue_status_text(counts),
                    counts=counts,
                    active=self._is_active(document.pdf_name),
                )
            )

        # A document that only survives in state.json (its PDF was deleted and it was
        # never configured) must stay visible: MISSING PDF with its queue status.
        known = {row.pdf_id for row in rows}
        for item in self._queue.document.items if self._queue is not None else []:
            if item.document in known:
                continue
            known.add(item.document)
            counts = counts_by_document.get(item.document, {name: 0 for name in state.VALID_STATES})
            rows.append(
                DocumentRow(
                    pdf_id=item.document,
                    name=item.pdf_name,
                    path=project.pdf_dir / item.pdf_name,
                    page_count=0,
                    stored_page_count=0,
                    count_method="",
                    enabled=False,
                    status=pagejob.DOC_STATUS_MISSING,
                    missing=True,
                    source="",
                    config_status="PDF nav atrasts - plāns saglabāts",
                    queue_status=self._queue_status_text(counts),
                    counts=counts,
                    active=self._is_active(item.pdf_name),
                )
            )
        return rows

    def document_row(self, pdf: str | Path) -> DocumentRow | None:
        """The PDF tab row of one document (by name, path or pdf_id)."""
        wanted_name = Path(str(pdf)).name.lower()
        wanted_id = str(pdf)
        for row in self.documents():
            if row.name.lower() == wanted_name or row.pdf_id == wanted_id:
                return row
        return None

    def active_document(self) -> DocumentRow | None:
        """The row of the active document (what MAPPING shows)."""
        if self._active_pdf is None:
            return None
        return self.document_row(self._active_pdf.name)

    @property
    def active_pdf_id(self) -> str:
        return self._active_pdf.stem if self._active_pdf else ""

    def select_document(self, name_or_id: str | Path) -> DocumentRow:
        """Make one document active (MAPPING edits, RUN CURRENT PDF)."""
        project = self._require_project()
        candidate = project.pdf_dir / Path(str(name_or_id)).name
        if not candidate.is_file():
            for row in self.documents():
                if row.pdf_id == str(name_or_id) or row.name.lower() == Path(str(name_or_id)).name.lower():
                    candidate = row.path
                    break
        if not candidate.is_file():
            raise ControllerError(f"PDF nav atrasts: {name_or_id}")
        self._active_pdf = candidate
        row = self.document_row(candidate.name)
        assert row is not None  # just resolved from the same folder
        self.log.info("Aktīvais dokuments: %s (%s lapas, %s)", row.name, row.page_count, row.status)
        return row

    def select_pdf(self, name_or_path: str | Path) -> PdfEntry:
        """Backwards compatible alias: select the document, return its plan entry."""
        self.select_document(name_or_path)
        return self.pdf_entry()

    @property
    def active_pdf(self) -> Path | None:
        return self._active_pdf

    def pdf_entry(self) -> PdfEntry:
        """Planning info of the ACTIVE document (page count, size, config status)."""
        pdf = self._require_pdf()
        row = self.document_row(pdf.name)
        page_count = row.page_count if row else 0
        method = row.count_method if row else ""
        if not page_count:
            try:
                page_count, method = count_pages(pdf)
            except PdfPageCountError as exc:
                raise ControllerError(str(exc)) from exc
        return PdfEntry(
            path=pdf,
            page_count=page_count,
            count_method=method,
            size_bytes=pdf.stat().st_size,
            config_status=row.config_status if row else "",
            active=True,
            pdf_id=row.pdf_id if row else pdf.stem,
            status=row.status if row else pagejob.DOC_STATUS_NEW,
            missing=row.missing if row else False,
        )

    def _is_active(self, name: str) -> bool:
        return self._active_pdf is not None and name.lower() == self._active_pdf.name.lower()

    def _queue_counts(self) -> dict[str, dict]:
        """Per document state counts of the queue (empty when nothing is built)."""
        counts: dict[str, dict] = {}
        for item in self._queue.document.items if self._queue is not None else []:
            per_document = counts.setdefault(item.document, {name: 0 for name in state.VALID_STATES})
            per_document[item.state] = per_document.get(item.state, 0) + 1
        return counts

    @staticmethod
    def _queue_status_text(counts: dict) -> str:
        """QUEUE STATUS column: what the queue did with this document so far."""
        total = sum(int(value) for value in (counts or {}).values())
        if not total:
            return "nav rindā"
        parts = [
            f"{name} {int((counts or {}).get(name, 0))}"
            for name in state.VALID_STATES
            if int((counts or {}).get(name, 0))
        ]
        return " | ".join(parts)

    def _document_config_status(self, config: dict, document: pagejob.DocumentPlan) -> str:
        """CONFIG STATUS column: config validity plus drift, per document."""
        if document.missing:
            return "PDF nav atrasts - plāns saglabāts"
        if not config:
            return "nav config.json (automātiskais plāns)"
        problems = cfg.validate_config(config)
        if problems:
            return "config.json nav derīgs: " + "; ".join(problems[:3])
        block = cfg.document_for(config, document.pdf_name)
        if block is None:
            return "dokumenta nav config.json (automātiskais plāns)"
        if document.stale:
            return (
                f"CONFIG STALE: stored {document.stored_page_count}, "
                f"current {document.current_page_count}"
            )
        pages = len(cfg.page_entries(config, document.pdf_name))
        enabled = len(cfg.enabled_page_entries(config, document.pdf_name))
        return f"config.json: {pages} lapas, iespējotas {enabled}"

    def _active_name(self) -> str | None:
        return self._active_pdf.name if self._active_pdf else None

    def _rebuild_queue(self) -> None:
        """Refresh the queue plan of the whole project (states are preserved)."""
        try:
            self.queue.build_queue()
        except Exception as exc:  # noqa: BLE001 - an incomplete job must not crash the GUI
            self.log.warning("Nevar pārbūvēt rindu: %s", exc)

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

    def ensure_queue_built(self) -> list[state.QueueItem]:
        """Make sure the JOB's queue exists (the GUI calls this on open / refresh).

        `BatchQueue.ensure_built` only builds when state.json holds no item yet, so
        this never disturbs a queue that already has states. Without it the PDF tab
        could not show a QUEUE STATUS and the run label would not know the document.
        """
        if self._project is None:
            return []
        try:
            return self.queue.ensure_built()
        except Exception as exc:  # noqa: BLE001 - an incomplete job must not crash the GUI
            self.log.warning("Nevar izveidot rindu: %s", exc)
            return []

    def preview_cache(self) -> PreviewCache:
        """The disposable preview cache of the active JOB (`JOB/.cache/preview`).

        Before a JOB is open (or without one) the cache lives in the system temp
        folder, so nothing is ever written next to the repository by accident.
        """
        project = self._project
        root = (
            project.root
            if project is not None
            else Path(tempfile.gettempdir()) / "cleanup_ai_preview"
        )
        if self._preview_cache is None or self._preview_cache.root != root:
            self._preview_cache = PreviewCache(root)
        return self._preview_cache

    def preview_target(self) -> tuple[Path, int] | None:
        """(pdf, page_count) of the active document, or None when there is none."""
        if self._active_pdf is None or not self._active_pdf.is_file():
            return None
        try:
            row = self.active_document()
        except ControllerError:
            return None
        if row is None or row.missing:
            return None
        return (self._active_pdf, int(row.page_count))

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
        """The MAPPING table of the ACTIVE document: plan + queue state.

        Edits always affect that one PDF; other documents are not touched.
        """
        project = self._require_project()
        try:
            plan = pagejob.plan_document(project, self._require_pdf())
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
                    pdf_id=job.pdf_id or self.active_pdf_id,
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
        by_page = {
            int(entry.get("page", 0)): entry
            for entry in cfg.page_entries(previous, pdf.name)
        }
        for entry in planned:
            old = by_page.get(int(entry["page"]))
            if not old:
                continue
            entry["layer"] = old.get("layer") or entry["layer"]
            entry["enabled"] = bool(old.get("enabled", True))
            entry["output"] = old.get("output") or entry["output"]

        defaults = dict(defaults)
        if (previous.get("defaults") or {}).get("template"):
            defaults["template"] = previous["defaults"]["template"]
        document = cfg.new_document(pdf.name, page_count, planned)
        self._write_config(cfg.replace_document(previous, document))
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
        """The project config with a valid plan for the ACTIVE document.

        Other documents are carried over untouched (`documents[]` keeps its order), so
        editing one PDF's mapping can never drop another PDF's plan.
        """
        project = self._require_project()
        pdf = self._require_pdf()
        config = cfg.load_config(project.config_path)
        problems = cfg.validate_config(config) if config else ["nav config.json"]
        document = cfg.document_for(config, pdf.name)
        if (
            config
            and not problems
            and document is not None
            and cfg.page_entries(config, pdf.name)
        ):
            return config

        try:
            page_count, _method = count_pages(pdf)
        except PdfPageCountError as exc:
            raise ControllerError(str(exc)) from exc
        pages, plan_defaults, _fallback = build_page_plan(pdf, page_count, project.template_dir)
        if document is not None and cfg.page_entries(config, pdf.name):
            current = {
                int(entry.get("page", 0)): entry
                for entry in cfg.page_entries(config, pdf.name)
            }
            for entry in pages:
                old = current.get(int(entry["page"]))
                if not old:
                    continue
                entry["layer"] = old.get("layer") or entry["layer"]
                entry["enabled"] = bool(old.get("enabled", True))
                entry["output"] = old.get("output") or entry["output"]
                entry["template"] = old.get("template")
        self.log.info("Izveidoju config.json priekš %s (%s lapas)", pdf.name, page_count)
        fresh = cfg.new_document(
            pdf.name,
            page_count,
            pages,
            enabled=bool((document or {}).get("enabled", True)),
        )
        defaults = dict(plan_defaults)
        if (config.get("defaults") or {}).get("template"):
            defaults["template"] = config["defaults"]["template"]
        merged = cfg.replace_document(config, fresh)
        merged["defaults"] = cfg.normalize_defaults(defaults)
        return merged

    def _set_pages(self, pages: Iterable[int], changes: dict) -> dict:
        wanted = {int(page) for page in pages}
        if not wanted:
            raise ControllerError("Nav atlasīta neviena lapa")
        config = self._ensure_config()
        for entry in cfg.page_entries(config, self._active_name()):
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
        self.queue.build_queue()

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
        # A problem with the ACTIVE document is only a hard failure when no other
        # document could run: one broken PDF must never block the rest of the JOB.
        alternatives = [
            path for path in project.find_pdfs() if self._active_pdf is None or path != self._active_pdf
        ]
        soft = bool(alternatives)
        if self._active_pdf is None:
            checks.append(validation.CheckResult("PDF fails", False, "nav izvēlēts PDF"))
            checks.extend(self._document_checks())
            return checks
        if not self._active_pdf.is_file():
            checks.append(
                validation.CheckResult(
                    "PDF fails",
                    not soft,
                    f"nav atrasts: {self._active_pdf.name}",
                    warning=soft,
                )
            )
            checks.extend(self._document_checks())
            return checks

        try:
            entry = self.pdf_entry()
        except ControllerError as exc:
            checks.append(validation.CheckResult("PDF lapas", not soft, str(exc), warning=soft))
            checks.extend(self._document_checks())
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

        checks.extend(self._document_checks())
        return checks

    def _document_checks(self) -> list[validation.CheckResult]:
        """Project level checks: one per document plus the queue collision guard.

        A missing or drifted document is a **warning**, never a hard failure: the spec
        is explicit that one broken PDF must not block the others (RUN ALL skips it,
        RUN CURRENT PDF still works). Only a real output collision fails, because the
        queue would refuse the pass anyway.
        """
        checks: list[validation.CheckResult] = []
        try:
            rows = self.documents()
        except ControllerError as exc:
            return [validation.CheckResult("Dokumenti", False, str(exc))]

        missing = [row.name for row in rows if row.missing]
        stale = [row.name for row in rows if row.status == pagejob.DOC_STATUS_STALE]
        failed = [row.name for row in rows if row.status == pagejob.DOC_STATUS_PLAN_ERROR]
        active = next((row for row in rows if row.active), None)

        detail = f"{len(rows)} PDF"
        if active is not None:
            detail += f" | aktīvais: {active.name} - {active.status_text}"
        if stale:
            detail += " | CONFIG STALE: " + ", ".join(stale)
        if missing:
            detail += " | MISSING PDF: " + ", ".join(missing)
        checks.append(
            validation.CheckResult(
                "Dokumenti",
                not failed,
                detail,
                warning=bool(stale or missing) and not failed,
            )
        )

        if self._queue is not None:
            collisions = self._queue.duplicate_outputs()
            if collisions:
                name, ids = next(iter(sorted(collisions.items())))
                checks.append(
                    validation.CheckResult(
                        "Output dublikāti",
                        False,
                        f"{name}: {', '.join(ids)} (divi dokumenti rakstītu vienu failu)",
                    )
                )
            else:
                checks.append(validation.CheckResult("Output dublikāti", True, "nav"))
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

    def _run_action(
        self,
        action: Callable[..., BatchSummary],
        *,
        progress=None,
        require_pdf: bool = True,
    ) -> BatchSummary:
        """Every run goes through the proven queue + adapter path.

        `require_pdf=False` is for the PROJECT level actions: a deleted or unreadable
        active PDF must never stop `RUN ALL ENABLED PDFs`, `CONTINUE PROJECT` or the
        retries - the queue skips exactly that document and runs the rest.
        """
        self._require_project()
        if require_pdf:
            self._require_pdf()
        queue = self.queue
        queue.adapter = self.adapter
        if not self.adapter.ensure_app():
            raise ControllerError("Illustrator nav sasniedzams (COM)")
        summary = action(progress=progress)
        self._last_checks = []  # state changed, validation is stale now
        return summary

    def _plan_kwargs(self) -> dict:
        """The plan arguments every run uses.

        No `pdf` key on purpose: a run refreshes the plan of the WHOLE project, so
        every document of the JOB is present in the queue (and stays WAITING when the
        run only covers one PDF). `overwrite` comes from the RUN tab checkbox.
        """
        return {"overwrite": self.overwrite_outputs}

    def run_document(self, pdf: str | Path | None = None, *, progress=None) -> BatchSummary:
        """RUN CURRENT PDF: only the pages of that document are run."""
        target = pdf or self._require_pdf().name
        queue = self.queue
        return self._run_action(
            lambda progress: queue.run_documents(
                [target], progress=progress, rebuild=True, build_kwargs=self._plan_kwargs()
            ),
            progress=progress,
        )

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
        """RUN ALL ENABLED PDFs: refresh the plan, then run the whole project backlog.

        Documents that are disabled, missing or unplannable are skipped by the queue
        (`enabled=False` on their items); a failure in one document never stops
        another one unless it is a global Illustrator/COM failure.
        """
        queue = self.queue
        return self._run_action(
            lambda progress: queue.run_all_enabled(
                progress=progress, build_kwargs=self._plan_kwargs()
            ),
            progress=progress,
            require_pdf=False,
        )

    def continue_queue(self, *, progress=None) -> BatchSummary:
        """CONTINUE PROJECT: WAITING + INTERRUPTED (a recovered RUNNING item included)."""
        queue = self.queue
        return self._run_action(
            lambda progress: queue.continue_queue(
                progress=progress, build_kwargs=self._plan_kwargs()
            ),
            progress=progress,
            require_pdf=False,
        )

    def retry_errors(self, *, progress=None) -> BatchSummary:
        """RETRY PROJECT ERRORS: ERROR -> WAITING in every document of the JOB."""
        queue = self.queue
        return self._run_action(
            lambda progress: (queue.retry_errors(run=True, progress=progress).summary or queue.summary()),
            progress=progress,
            require_pdf=False,
        )

    def retry_interrupted(self, *, progress=None) -> BatchSummary:
        """RETRY INTERRUPTED: INTERRUPTED -> WAITING in every document, then run."""
        queue = self.queue
        return self._run_action(
            lambda progress: (queue.retry_interrupted(run=True, progress=progress).summary or queue.summary()),
            progress=progress,
            require_pdf=False,
        )

    # ------------------------------------------------------------------ progress

    def progress(self) -> ProgressSnapshot:
        """Everything the RUN tab shows, derived from the queue state only (cheap).

        No PDF or config reads here: the RUN tab is polled while a batch runs, so it
        only reads `state.json` (through the open queue) and groups it per document.
        """
        counts = self.queue_summary()
        items = self._queue.document.items if self._queue is not None else []
        total = len(items)
        if total == 0:
            # nothing queued yet: fall back to the plan so the bar is not empty
            try:
                total = len(self.mapping_rows())
            except ControllerError:
                total = 0

        rows = self._queue.document_progress() if self._queue is not None else []
        documents = tuple(
            DocumentProgress(
                pdf_id=row.get("pdf_id", ""),
                name=row.get("pdf", ""),
                page_count=row.get("pages", 0),
                processed=row.get("processed", 0),
                current_page=row.get("current_page", 0),
                counts=row.get("counts") or {},
            )
            for row in rows
        )

        running = next((item for item in items if item.state == state.RUNNING), None)
        current = None
        if running is not None:
            current = next((doc for doc in documents if doc.pdf_id == running.document), None)
        if current is None:
            current = next((doc for doc in documents if doc.pdf_id == self.active_pdf_id), None)
        if current is None:
            current = next(
                (doc for doc in documents if doc.processed),
                documents[0] if documents else None,
            )

        return ProgressSnapshot(
            total=total,
            processed=counts[state.DONE] + counts[state.SKIPPED] + counts[state.ERROR],
            current_page=current.current_page if current else 0,
            running_page=running.page if running else 0,
            counts=counts,
            pdfs=counts.get("pdfs", len(documents)),
            document=current.name if current else "",
            document_total=current.page_count if current else 0,
            documents=documents,
        )

    def has_running_items(self) -> bool:
        """Used by the window close handler (recovery stays authoritative)."""
        if self._queue is None:
            return False
        return any(item.state == state.RUNNING for item in self._queue.document.items)
