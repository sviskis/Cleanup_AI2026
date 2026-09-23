"""One page of work: the plan Python builds for the worker.

Both entry points use this module, so the mapping
"page -> template / output / layer / template_mode" exists exactly once:

    pdf_ai_batch/run_one.py      one page, end to end (milestone 1)
    pdf_ai_batch/core/queue.py   the persistent batch queue (milestone 2)

Python owns every path here: the JOB root is absolute (`JobProject.open`) and the
request paths go through `contract.build_request`, which resolves them and uses
forward slashes. The worker never resolves anything.

Order of truth for one page:

    1. explicit CLI/GUI value   (--template, --layer, --no-clear, --template-mode)
    2. config.json              (pages[i].template / layer / output, defaults block)
    3. automatic positional map (template_mapper.build_page_plan)

config.json is used only when it validates AND belongs to the same PDF; otherwise
the automatic plan is used and a warning is reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable

from . import config as config_module
from .contract import LAYER_DEFAULT, build_request
from .naming import job_id_for, output_name_for, pdf_id_for, pdf_key_for
from .pdf_info import PdfPageCountError, count_pages
from .project import JobProject, ProjectError
from .template_mapper import build_page_plan, default_template, resolve_template

PLAN_SOURCE_AUTO = "auto"
PLAN_SOURCE_CONFIG = "config"
PLAN_SOURCE_EXPLICIT = "explicit"
PLAN_SOURCE_MISSING = "missing"

#: Document level states (config vs the PDF on disk) - shown by the GUI/CLI as-is.
DOC_STATUS_OK = "OK"
DOC_STATUS_NEW = "NEW"
DOC_STATUS_STALE = "CONFIG STALE"
DOC_STATUS_MISSING = "MISSING PDF"
DOC_STATUS_PLAN_ERROR = "PLAN ERROR"


class PagePlanError(RuntimeError):
    """Raised when a page cannot be planned (missing PDF, page or template)."""


@dataclass(frozen=True)
class PageJob:
    """Everything needed to run ONE page (one worker invocation)."""

    pdf: Path
    pdf_name: str
    page: int
    page_count: int
    count_method: str
    template: Path
    output: Path
    output_name: str
    job_id: str
    mode: str
    pdf_id: str = ""
    layer: str = LAYER_DEFAULT
    clear_layer: bool = True
    overwrite: bool = False
    enabled: bool = True
    template_source: str = PLAN_SOURCE_AUTO

    def request(self, run_id: str) -> dict:
        """The contract request for this page (absolute, forward slashed)."""
        return build_request(
            run_id=run_id,
            job_id=self.job_id,
            pdf=self.pdf,
            page=self.page,
            template=self.template,
            output=self.output,
            layer=self.layer,
            clear_layer=self.clear_layer,
            overwrite=self.overwrite,
            template_mode=self.mode,
        )


@dataclass(frozen=True)
class PagePlan:
    """The plan of one PDF: file information plus one PageJob per page."""

    pdf: Path
    page_count: int
    count_method: str
    pages: tuple[PageJob, ...] = ()
    pool: tuple[Path, ...] = ()
    fallback: Path | None = None
    source: str = PLAN_SOURCE_AUTO
    warnings: tuple[str, ...] = ()

    def by_page(self, page: int) -> PageJob | None:
        for job in self.pages:
            if job.page == int(page):
                return job
        return None

    def page_numbers(self) -> list[int]:
        return [job.page for job in self.pages]

    def enabled_pages(self) -> list[PageJob]:
        return [job for job in self.pages if job.enabled]


@dataclass(frozen=True)
class DocumentPlan:
    """The plan of ONE configured document of a JOB.

    `page_count` is the count the plan was built for (the stored one when the PDF
    drifted, so output names stay stable); `current_page_count` is what the file has
    right now. `status` is one of the DOC_STATUS_* values and is never applied
    silently - a stale or missing document is reported and reconciled on request.
    """

    pdf_id: str
    pdf: Path
    pdf_name: str
    enabled: bool
    status: str
    page_count: int
    current_page_count: int
    count_method: str
    pages: tuple[PageJob, ...] = ()
    source: str = PLAN_SOURCE_AUTO
    warnings: tuple[str, ...] = ()
    stored_page_count: int = 0
    missing: bool = False

    @property
    def stale(self) -> bool:
        """The PDF page count differs from the stored config page count."""
        return self.status == DOC_STATUS_STALE

    @property
    def planned_pages(self) -> tuple[PageJob, ...]:
        return self.pages

    def by_page(self, page: int) -> PageJob | None:
        for job in self.pages:
            if job.page == int(page):
                return job
        return None

    def status_text(self) -> str:
        """Human readable document status, including the drift numbers."""
        if self.missing:
            return f"{DOC_STATUS_MISSING}"
        if self.stale:
            return f"{DOC_STATUS_STALE} (stored: {self.stored_page_count}, current: {self.current_page_count})"
        return self.status


@dataclass(frozen=True)
class ProjectPlan:
    """Every document of a JOB, in the deterministic queue order."""

    documents: tuple[DocumentPlan, ...] = ()
    warnings: tuple[str, ...] = ()

    def document(self, pdf: str | Path) -> DocumentPlan | None:
        wanted_id = pdf_id_for(pdf)
        wanted_name = Path(str(pdf)).name.lower()
        for document in self.documents:
            if document.pdf_id == wanted_id or document.pdf_name.lower() == wanted_name:
                return document
        return None

    def pages(self) -> tuple[PageJob, ...]:
        """All planned pages: document order first, then page ascending."""
        return tuple(job for document in self.documents for job in document.pages)

    def enabled_pages(self) -> tuple[PageJob, ...]:
        return tuple(job for job in self.pages() if job.enabled)

    def total_pages(self) -> int:
        return len(self.pages())

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for document in self.documents:
            counts[document.status] = counts.get(document.status, 0) + 1
        return counts


@dataclass(frozen=True)
class DocumentPlanInputs:
    """Where the plan of one document comes from (config.json or the automatic map)."""

    entries: dict[int, dict] = field(default_factory=dict)
    source: str = PLAN_SOURCE_AUTO
    defaults: dict = field(default_factory=dict)
    fallback: Path | None = None
    warnings: tuple[str, ...] = ()


def document_plan_inputs(
    project: JobProject,
    pdf_path: str | Path,
    *,
    page_count: int,
    config: dict | None = None,
) -> DocumentPlanInputs:
    """Resolve the plan entries of ONE document.

    Order of truth for a document: its own block in `config.json` (version 2, a
    migrated version 1 file counts as the single document it was), otherwise the
    automatic positional map. The function never raises for a missing document block:
    a plan that cannot use the config reports a warning and falls back to `auto`.
    """
    warnings: list[str] = []
    pdf = Path(pdf_path)
    configured = config if config is not None else config_module.load_config(project.config_path)
    defaults = config_module.normalize_defaults((configured or {}).get("defaults"))

    if configured and not config_module.validate_config(configured):
        block = config_module.document_for(configured, pdf.name)
        if block is None:
            warnings.append(
                f"config.json nesatur dokumentu {pdf.name} - izmantoju automātisko plānu"
            )
        else:
            entries = {
                int(entry["page"]): entry
                for entry in config_module.page_entries(configured, pdf.name)
                if isinstance(entry, dict) and isinstance(entry.get("page"), int)
            }
            if entries:
                return DocumentPlanInputs(entries, PLAN_SOURCE_CONFIG, defaults, None, ())
            warnings.append(
                f"{pdf.name}: config.json ir bez lapu ierakstiem - izmantoju automātisko plānu"
            )

    auto_pages, _auto_defaults, auto_fallback = build_page_plan(
        pdf, page_count, project.template_dir
    )
    entries = {int(entry["page"]): entry for entry in auto_pages}
    return DocumentPlanInputs(entries, PLAN_SOURCE_AUTO, defaults, auto_fallback, tuple(warnings))


def parse_page_spec(spec: str | Iterable[int] | None) -> list[int] | None:
    """Parse "--pages 1-3,5,9-11" into [1, 2, 3, 5, 9, 10, 11].

    None means "every page". Deduplicated, ascending and 1 based.
    """
    if spec is None:
        return None
    if not isinstance(spec, str):
        return sorted({int(value) for value in spec})

    text = spec.replace(";", ",").replace(" ", "")
    if not text:
        return None

    pages: set[int] = set()
    for part in text.split(","):
        if not part:
            continue
        if "-" in part:
            first, _, last = part.partition("-")
            try:
                start = int(first)
                end = int(last)
            except ValueError as exc:
                raise PagePlanError(f"nederīgs lapu diapazons: {part}") from exc
            if end < start:
                start, end = end, start
            pages.update(range(start, end + 1))
        else:
            try:
                pages.add(int(part))
            except ValueError as exc:
                raise PagePlanError(f"nederīgs lapas numurs: {part}") from exc
    return sorted(pages) if pages else None


def plan_pages(
    project: JobProject,
    *,
    pdf: str | Path | None = None,
    pages: str | Iterable[int] | None = None,
    template: str | None = None,
    layer: str | None = None,
    clear_layer: bool | None = None,
    overwrite: bool = False,
    template_mode: str = "auto",
    naming_page_count: int | None = None,
) -> PagePlan:
    """Plan the requested pages of one PDF.

    Raises ProjectError when the PDF is missing, PdfPageCountError when the page
    count cannot be determined and PagePlanError for a bad page or template.

    `naming_page_count` overrides the count used for **output names** (and only for
    them): a document whose PDF page count drifted keeps the stored width, so the
    names of already processed pages do not change behind the operator's back.
    """
    warnings: list[str] = []

    if pdf is None:
        candidates = project.find_pdfs()
        if not candidates:
            raise PagePlanError("JOB/PDF mapē nav neviena PDF faila")
        pdf_path = candidates[0]
    else:
        pdf_path = project.resolve_pdf(pdf)

    page_count, count_method = count_pages(pdf_path)
    name_count = int(naming_page_count) if naming_page_count else page_count

    pool = tuple(project.page_template_pool())
    fallback = default_template(project.template_dir)

    inputs = document_plan_inputs(project, pdf_path, page_count=page_count)
    entries = inputs.entries
    source = inputs.source
    fallback = inputs.fallback or fallback
    configured_default = inputs.defaults.get("template")
    warnings.extend(inputs.warnings)

    requested = parse_page_spec(pages)
    page_numbers = list(range(1, page_count + 1)) if requested is None else requested
    beyond = [page for page in page_numbers if page < 1 or page > page_count]
    if beyond:
        raise PagePlanError(f"lapa {beyond[0]} pārsniedz PDF lappušu skaitu {page_count}")

    jobs: list[PageJob] = []
    for page in page_numbers:
        entry = entries.get(page) or {}

        if template:
            chosen = resolve_template(template, project.template_dir, fallback)
            if chosen is None:
                raise PagePlanError(f"template nav atrasts: {template}")
            template_source = PLAN_SOURCE_EXPLICIT
        else:
            value = entry.get("template") or configured_default
            chosen = resolve_template(value, project.template_dir, fallback)
            if chosen is None and value:
                # The intended template file is missing. Keep the intended path so
                # that only THIS page fails (ERROR + retry), instead of aborting the
                # plan of every other page with it.
                chosen = Path(str(value))
                if not chosen.is_absolute():
                    chosen = project.template_dir / chosen.name
                warnings.append(f"lapa {page}: template nav atrasts: {chosen}")
                template_source = PLAN_SOURCE_MISSING
            elif chosen is None:
                raise PagePlanError("nav neviena template un nav noklusētā (MASTER_*) template")
            else:
                template_source = source

        if clear_layer is not None:
            job_clear = bool(clear_layer)
        elif entry.get("clear_layer") is not None:
            job_clear = bool(entry["clear_layer"])
        elif source == PLAN_SOURCE_CONFIG:
            job_clear = bool(inputs.defaults.get("clear_layer", True))
        else:
            job_clear = True

        output_name = entry.get("output") or output_name_for(pdf_path, page, name_count)
        jobs.append(
            PageJob(
                pdf=pdf_path,
                pdf_name=pdf_path.name,
                page=page,
                page_count=page_count,
                count_method=count_method,
                template=chosen,
                output=project.output_dir / output_name,
                output_name=output_name,
                job_id=job_id_for(pdf_path, page),
                mode=template_mode if template_mode != "auto" else config_module.template_mode_for(chosen),
                pdf_id=pdf_id_for(pdf_path),
                layer=layer or entry.get("layer") or LAYER_DEFAULT,
                clear_layer=job_clear,
                overwrite=bool(overwrite),
                enabled=bool(entry.get("enabled", True)),
                template_source=template_source,
            )
        )

    return PagePlan(
        pdf=pdf_path,
        page_count=page_count,
        count_method=count_method,
        pages=tuple(jobs),
        pool=pool,
        fallback=fallback,
        source=source,
        warnings=tuple(warnings),
    )


def plan_document(
    project: JobProject,
    pdf: str | Path,
    *,
    config: dict | None = None,
    pages: str | Iterable[int] | None = None,
    template: str | None = None,
    layer: str | None = None,
    clear_layer: bool | None = None,
    overwrite: bool = False,
    template_mode: str = "auto",
) -> DocumentPlan:
    """Plan ONE document and report its status instead of rewriting anything.

    A document whose PDF page count no longer matches the stored config is marked
    `CONFIG STALE` and is planned with the **stored** page count (so output names stay
    stable); pages the PDF lost are not planned at all. Pages the PDF gained are not
    planned either - the operator decides with an explicit RECONCILE.
    """
    pdf_path = project.resolve_pdf(pdf)
    configured = config if config is not None else config_module.load_config(project.config_path)
    block = config_module.document_for(configured, pdf_path.name) if configured else None
    stored = config_module.document_page_count(block)
    enabled = bool(block.get("enabled", True)) if block is not None else True

    current_count, count_method = count_pages(pdf_path)
    configured_pages = [
        int(entry["page"])
        for entry in config_module.page_entries(configured, pdf_path.name)
        if isinstance(entry, dict) and isinstance(entry.get("page"), int) and int(entry["page"]) >= 1
    ]
    configured_pages.sort()

    status = DOC_STATUS_NEW if block is None or not configured_pages else DOC_STATUS_OK
    if block is not None and stored and current_count != stored:
        status = DOC_STATUS_STALE

    planned = pages
    if planned is None and status == DOC_STATUS_STALE:
        planned = [page for page in configured_pages if page <= current_count]

    plan = plan_pages(
        project,
        pdf=pdf_path,
        pages=planned,
        template=template,
        layer=layer,
        clear_layer=clear_layer,
        overwrite=overwrite,
        template_mode=template_mode,
        naming_page_count=stored or None,
    )

    warnings = list(plan.warnings)
    jobs = plan.pages
    if not enabled:
        warnings.append(f"{pdf_path.name}: dokuments ir izslēgts (USE nav atzīmēts) - lapas netiks palaistas")
        jobs = tuple(replace(job, enabled=False) for job in plan.pages)
    if status == DOC_STATUS_STALE:
        warnings.append(
            f"{pdf_path.name}: PDF lapu skaits mainījies (stored: {stored}, current: {current_count}) "
            "- nepieciešams RECONCILE"
        )
        missing_pages = [page for page in configured_pages if page > current_count]
        if missing_pages:
            warnings.append(
                f"{pdf_path.name}: lapas {missing_pages} vairs nav PDF, līdz RECONCILE tās netiek plānotas"
            )

    return DocumentPlan(
        pdf_id=pdf_id_for(pdf_path),
        pdf=pdf_path,
        pdf_name=pdf_path.name,
        enabled=enabled,
        status=status,
        page_count=plan.page_count,
        current_page_count=current_count,
        count_method=count_method,
        pages=jobs,
        source=plan.source,
        warnings=tuple(warnings),
        stored_page_count=stored,
    )


def document_from_page_plan(
    plan: PagePlan,
    *,
    enabled: bool = True,
    status: str = DOC_STATUS_OK,
    warnings: tuple[str, ...] = (),
) -> DocumentPlan:
    """Wrap a single document `PagePlan` as a `DocumentPlan` (build_queue, tests)."""
    return DocumentPlan(
        pdf_id=pdf_id_for(plan.pdf),
        pdf=plan.pdf,
        pdf_name=plan.pdf.name,
        enabled=enabled,
        status=status,
        page_count=plan.page_count,
        current_page_count=plan.page_count,
        count_method=plan.count_method,
        pages=plan.pages,
        source=plan.source,
        warnings=warnings,
    )


def plan_project(
    project: JobProject,
    *,
    pdfs: Iterable[str | Path] | None = None,
    pages: str | Iterable[int] | None = None,
    template: str | None = None,
    layer: str | None = None,
    clear_layer: bool | None = None,
    overwrite: bool = False,
    template_mode: str = "auto",
) -> ProjectPlan:
    """Plan every document of a JOB, in the deterministic queue order.

    Order: the order of `documents[]` in config.json first (exactly what the operator
    configured), then any PDF in JOB/PDF that is not configured yet, in natural sort
    order. `pdfs` restricts the pass to those documents (the CLI `--pdf` and the GUI's
    "run current PDF").

    A document that is missing, disabled or cannot be planned is **reported**, never
    dropped: its mapping and its queue state stay available, and the other documents
    continue (a per document problem must not stop the project).
    """
    configured = config_module.load_config(project.config_path)
    wanted: set[str] | None = None
    if pdfs is not None:
        wanted = set()
        for item in pdfs:
            wanted.add(Path(str(item)).name.lower())
            wanted.add(pdf_id_for(item))

    warnings: list[str] = []
    documents: list[DocumentPlan] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        key = pdf_key_for(name)
        if key in seen:
            return
        seen.add(key)
        if wanted is not None and Path(name).name.lower() not in wanted and pdf_id_for(name) not in wanted:
            return

        path = project.pdf_dir / name
        block = config_module.document_for(configured, name) if configured else None
        if not path.is_file():
            documents.append(
                DocumentPlan(
                    pdf_id=pdf_id_for(name),
                    pdf=path,
                    pdf_name=Path(name).name,
                    enabled=bool((block or {}).get("enabled", True)),
                    status=DOC_STATUS_MISSING,
                    page_count=config_module.document_page_count(block),
                    current_page_count=0,
                    count_method="",
                    missing=True,
                    stored_page_count=config_module.document_page_count(block),
                    warnings=(f"PDF nav atrasts: {path}",),
                )
            )
            warnings.append(f"PDF nav atrasts: {name}")
            return

        try:
            documents.append(
                plan_document(
                    project,
                    path,
                    config=configured,
                    pages=pages,
                    template=template,
                    layer=layer,
                    clear_layer=clear_layer,
                    overwrite=overwrite,
                    template_mode=template_mode,
                )
            )
        except (PagePlanError, PdfPageCountError, ProjectError) as exc:
            warnings.append(f"{name}: {exc}")
            documents.append(
                DocumentPlan(
                    pdf_id=pdf_id_for(name),
                    pdf=path,
                    pdf_name=Path(name).name,
                    enabled=bool((block or {}).get("enabled", True)),
                    status=DOC_STATUS_PLAN_ERROR,
                    page_count=config_module.document_page_count(block),
                    current_page_count=0,
                    count_method="",
                    warnings=(f"{name}: {exc}",),
                )
            )

    for block in config_module.document_entries(configured):
        add(str(block.get("pdf") or ""))
    for path in project.find_pdfs():
        add(path.name)

    if not documents:
        warnings.append("JOB/PDF mapē nav neviena PDF faila")

    return ProjectPlan(documents=tuple(documents), warnings=tuple(warnings))


def reconcile_plan(
    project: JobProject,
    pdf: str | Path,
    *,
    config: dict | None = None,
) -> tuple[dict, dict]:
    """Prepare the reconciled config document + report for one PDF (no write)."""
    pdf_path = project.resolve_pdf(pdf)
    configured = config if config is not None else config_module.load_config(project.config_path)
    block = config_module.document_for(configured, pdf_path.name)
    if block is None:
        block = config_module.new_document(pdf_path.name, 1, [])
    current_count, count_method = count_pages(pdf_path)
    document, report = config_module.reconcile_document(
        block, page_count=current_count, defaults=(configured or {}).get("defaults")
    )
    report["count_method"] = count_method
    return document, report


def apply_reconcile(
    project: JobProject,
    pdf: str | Path,
    *,
    config: dict | None = None,
) -> tuple[dict, dict]:
    """Reconcile one document and save the config. Returns (config, report).

    Explicit only: nothing in the pipeline ever reconciles on its own, because that
    would silently rewrite the mapping of a changed PDF.
    """
    document, report = reconcile_plan(project, pdf, config=config)
    configured = config if config is not None else config_module.load_config(project.config_path)
    updated = config_module.replace_document(configured, document)
    config_module.save_config(project.config_path, updated)
    return updated, report


def document_matches_pdf(config: dict | None, pdf: str | Path, page_count: int) -> bool:
    """True when the stored page count of one document equals the current one."""
    block = config_module.document_for(config or {}, pdf)
    stored = config_module.document_page_count(block)
    return bool(stored) and stored == int(page_count)


def output_ready(path: str | Path, *, require_nonempty: bool = True) -> tuple[bool, str]:
    """The DONE rule of the queue: the expected output AI must really be there.

    Returns (ready, reason). An empty file never counts as a result: Illustrator
    does not write a 0 byte AI, so that is a failed save, not a finished page.
    """
    target = Path(str(path))
    try:
        if not target.exists():
            return False, "output fails neeksistē"
        if require_nonempty and target.stat().st_size == 0:
            return False, "output fails ir tukšs (0 baiti)"
    except OSError as exc:  # noqa: BLE001 - an unreadable path is a failed output
        return False, f"output failu nevar pārbaudīt: {exc}"
    return True, ""


OUTPUT_COPIED = "copied"
OUTPUT_SKIPPED = "skipped"
OUTPUT_FAILED = "failed"


@dataclass(frozen=True)
class OutputPrep:
    """What happened while preparing the output file for one attempt."""

    status: str = OUTPUT_COPIED
    reason: str = ""

    @property
    def ok(self) -> bool:
        """The output is in place, the worker may run."""
        return self.status == OUTPUT_COPIED

    @property
    def skipped(self) -> bool:
        """Do not run: the output already exists and overwrite is off."""
        return self.status == OUTPUT_SKIPPED

    @property
    def failed(self) -> bool:
        """The environment is broken (missing template, no write access)."""
        return self.status == OUTPUT_FAILED


def prepare_output_copy(
    template: str | Path,
    output: str | Path,
    overwrite: bool = False,
    logger=None,
) -> OutputPrep:
    """Prepare the output AI before a run (Python owns this for .ai templates).

    copied  - the file is ready (fresh copy, or a replacement when overwrite is on)
    skipped - the output already exists and overwrite is off: the caller must SKIP
    failed  - the source or the destination cannot be used: the caller must ERROR
    """
    import shutil

    template_path = Path(template)
    output_path = Path(output)

    if output_path.exists():
        if not overwrite:
            return OutputPrep(OUTPUT_SKIPPED, "output jau eksistē un overwrite nav atļauts")
        try:
            output_path.unlink()
        except OSError as exc:
            return OutputPrep(OUTPUT_FAILED, f"nevar izdzēst esošo output: {exc}")

    if not template_path.is_file():
        return OutputPrep(OUTPUT_FAILED, f"template nav atrasts: {template_path}")

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template_path, output_path)
    except OSError as exc:
        return OutputPrep(OUTPUT_FAILED, f"nevar nokopēt template uz output: {exc}")

    if logger is not None:
        logger.info("Nokopēju template %s -> %s", template_path.name, output_path.name)
    return OutputPrep(OUTPUT_COPIED)
