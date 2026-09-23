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

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import load_config, template_mode_for, validate_config
from .contract import LAYER_DEFAULT, build_request
from .naming import job_id_for, output_name_for
from .pdf_info import count_pages
from .project import JobProject
from .template_mapper import build_page_plan, default_template, resolve_template

PLAN_SOURCE_AUTO = "auto"
PLAN_SOURCE_CONFIG = "config"
PLAN_SOURCE_EXPLICIT = "explicit"
PLAN_SOURCE_MISSING = "missing"


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
) -> PagePlan:
    """Plan the requested pages of one PDF.

    Raises ProjectError when the PDF is missing, PdfPageCountError when the page
    count cannot be determined and PagePlanError for a bad page or template.
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

    pool = tuple(project.page_template_pool())
    fallback = default_template(project.template_dir)

    entries: dict[int, dict] = {}
    source = PLAN_SOURCE_AUTO
    configured = load_config(project.config_path)
    if configured and not validate_config(configured):
        if str(configured.get("pdf") or "") == pdf_path.name:
            entries = {
                int(entry["page"]): entry
                for entry in configured.get("pages", [])
                if isinstance(entry, dict) and isinstance(entry.get("page"), int)
            }
            source = PLAN_SOURCE_CONFIG
        else:
            warnings.append(
                "config.json apraksta citu PDF (%s), izmantoju automātisko plānu"
                % configured.get("pdf")
            )

    if not entries:
        auto_pages, _defaults, auto_fallback = build_page_plan(
            pdf_path, page_count, project.template_dir
        )
        entries = {int(entry["page"]): entry for entry in auto_pages}
        fallback = auto_fallback or fallback
        source = PLAN_SOURCE_AUTO

    configured_default = None
    if source == PLAN_SOURCE_CONFIG:
        configured_default = (configured.get("defaults") or {}).get("template")

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
            job_clear = bool((configured.get("defaults") or {}).get("clear_layer", True))
        else:
            job_clear = True

        output_name = entry.get("output") or output_name_for(pdf_path, page, page_count)
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
                mode=template_mode if template_mode != "auto" else template_mode_for(chosen),
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
