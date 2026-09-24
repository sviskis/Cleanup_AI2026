"""Production preflight: one action that answers "can this project run now?".

`core/validation.py` checks ONE page (and is what a run already refuses to skip).
This module **aggregates** that check instead of duplicating it: it wraps
`validation.preflight()` into project wide sections, adds the checks only a project
can have (every document, every template, duplicate outputs, the queue, disk space)
and classifies every finding as `OK`, `WARNING` or `ERROR`.

Severity rules
    OK       nothing to do
    WARNING  the project can run, but something deserves attention (a missing
             document other documents can still be run without, a stale page count
             next to healthy documents, low disk space, an existing output that
             would be SKIPped, ...)
    ERROR    a run cannot be trusted or cannot finish (nothing left to run, an
             invalid config, a missing template a planned page needs, duplicate
             output names, an unwritable AI_OUT, an unreachable Illustrator, a
             queue that cannot be built, almost no disk space)

`RUN` is only blocked by a real `ERROR` (`PreflightReport.can_run`), never by a
warning.

    report = run_preflight(project, adapter=...)      # explicit action only
    report.status                                     # READY / NOT READY
    report.summary_rows()                             # the GUI/console layout
    report.to_text()                                  # the full report

Illustrator is contacted ONLY when `check_illustrator=True` (the explicit
`[PREFLIGHT PROJECT]` / `--preflight-project` path), never by opening the GUI.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config as cfg
from . import report as report_module
from . import state, validation
from .naming import find_duplicate_outputs, validate_output_name
from .pagejob import DOC_STATUS_PLAN_ERROR, DOC_STATUS_STALE, output_ready
from .pdf_info import PdfPageCountError, count_pages
from .template_mapper import default_template, is_template_file, list_templates

SEVERITY_OK = validation.SEVERITY_OK
SEVERITY_WARNING = validation.SEVERITY_WARNING
SEVERITY_ERROR = validation.SEVERITY_ERROR

STATUS_READY = "READY"
STATUS_NOT_READY = "NOT READY"

#: free space on the JOB drive: below this a warning, below the error value a stop
FREE_SPACE_WARNING_MB = 500
FREE_SPACE_ERROR_MB = 100

SECTION_ORDER = ("PROJECT", "PDF", "TEMPLATES", "OUTPUT", "QUEUE", "ILLUSTRATOR", "SYSTEM")


@dataclass(frozen=True)
class PreflightSection:
    """One block of the report (its own severity = the worst finding inside)."""

    key: str
    checks: tuple = ()
    facts: dict = field(default_factory=dict)

    @property
    def errors(self) -> tuple:
        return tuple(check for check in self.checks if not check.ok and not check.warning)

    @property
    def warnings(self) -> tuple:
        return tuple(check for check in self.checks if not check.ok and check.warning)

    @property
    def severity(self) -> str:
        if self.errors:
            return SEVERITY_ERROR
        if self.warnings:
            return SEVERITY_WARNING
        return SEVERITY_OK

    def lines(self, width: int = 34) -> list[str]:
        return [check.format(width) for check in self.checks]


@dataclass(frozen=True)
class PreflightReport:
    """The whole preflight: sections, facts, overall status."""

    job: str
    root: str
    started: str = ""
    finished: str = ""
    sections: tuple = ()
    facts: dict = field(default_factory=dict)
    problems: tuple = ()  # the hard failures, ready for a status line
    warnings: tuple = ()

    # ------------------------------------------------------------------ helpers

    def section(self, key: str) -> PreflightSection | None:
        for item in self.sections:
            if item.key == key:
                return item
        return None

    @property
    def can_run(self) -> bool:
        """RUN is blocked by a real ERROR only, never by a warning."""
        return not self.problems

    @property
    def status(self) -> str:
        return STATUS_READY if self.can_run else STATUS_NOT_READY

    @property
    def duration(self) -> float:
        try:
            start = datetime.strptime(self.started, state.TIMESTAMP_FORMAT)
            end = datetime.strptime(self.finished, state.TIMESTAMP_FORMAT)
        except (ValueError, TypeError):
            return 0.0
        return max(0.0, end.timestamp() - start.timestamp())

    def summary_rows(self) -> list[tuple[str, str]]:
        """The compact layout (label, value) the GUI pane and the console show."""
        facts = self.facts or {}
        missing_pdfs = facts.get("missing_pdfs") or []
        missing_templates = facts.get("missing_templates") or []
        return [
            ("PDF", "OK" if not missing_pdfs else f"{len(missing_pdfs)} trūkst"),
            ("Pages", str(facts.get("pages", 0))),
            ("Templates", "OK" if not missing_templates else "TRŪKST"),
            ("Missing templates", str(len(missing_templates))),
            ("Duplicate outputs", str(len(facts.get("duplicate_outputs") or []))),
            ("Output writable", "YES" if facts.get("output_writable") else "NO"),
            ("Illustrator", str(facts.get("illustrator") or "nav pārbaudīts")),
            ("Disk space", str(facts.get("disk") or "?")),
            ("Queue", str(facts.get("queue") or "?")),
            ("", ""),
            ("Overall", self.status),
        ]

    def to_text(self) -> str:
        lines = [
            "PRODUCTION PREFLIGHT",
            "",
            f"Job: {self.job}",
            f"Project: {self.root}",
            f"Checked: {self.started or '-'} ({self.duration:.1f}s)",
            "",
        ]
        width = 22
        for label, value in self.summary_rows():
            lines.append(f"{label:<{width}} {value}" if label else "")
        for item in self.sections:
            lines.append("")
            lines.append(f"[{item.key}] {item.severity}")
            lines.extend("  " + line for line in item.lines())
        if self.problems:
            lines.append("")
            lines.append("BLOĶĒJOŠAS KĻŪDAS:")
            lines.extend(f"  - {problem}" for problem in self.problems)
        if self.warnings:
            lines.append("")
            lines.append("BRĪDINĀJUMI:")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        lines.append("")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "job": self.job,
            "root": self.root,
            "started": self.started,
            "finished": self.finished,
            "status": self.status,
            "can_run": self.can_run,
            "facts": dict(self.facts),
            "problems": list(self.problems),
            "warnings": list(self.warnings),
            "sections": [
                {
                    "key": item.key,
                    "severity": item.severity,
                    "facts": dict(item.facts),
                    "checks": [
                        {
                            "name": check.name,
                            "ok": bool(check.ok),
                            "warning": bool(check.warning),
                            "severity": check.severity,
                            "detail": check.detail,
                        }
                        for check in item.checks
                    ],
                }
                for item in self.sections
            ],
        }


# ------------------------------------------------------------------- the check run


def _check(label: str, ok: bool, detail: str = "", *, warning: bool = False) -> validation.CheckResult:
    return validation.CheckResult(label, bool(ok), detail, warning=warning)


def _disk_facts(project: JobProject) -> tuple[dict, validation.CheckResult]:
    """Free space on the drive that holds the JOB."""
    facts: dict = {}
    try:
        usage = shutil.disk_usage(str(project.root))
    except OSError as exc:  # noqa: BLE001 - an unreachable drive is a finding, not a crash
        facts["disk"] = "?"
        facts["disk_free_mb"] = 0
        return facts, _check("Brīvā vieta", False, f"nevar nolasīt: {exc}")
    free_mb = int(usage.free / (1024 * 1024))
    facts["disk_free_mb"] = free_mb
    if free_mb < FREE_SPACE_ERROR_MB:
        facts["disk"] = f"{free_mb} MB (par maz)"
        return facts, _check("Brīvā vieta", False, f"{free_mb} MB < {FREE_SPACE_ERROR_MB} MB")
    if free_mb < FREE_SPACE_WARNING_MB:
        facts["disk"] = f"{free_mb} MB (maz)"
        return facts, _check(
            "Brīvā vieta", False, f"{free_mb} MB < {FREE_SPACE_WARNING_MB} MB", warning=True
        )
    facts["disk"] = f"OK ({free_mb // 1024} GB)"
    return facts, _check("Brīvā vieta", True, f"{free_mb} MB")


def _project_section(project: JobProject) -> tuple[PreflightSection, dict]:
    checks = [_check("JOB mape", project.root.is_dir(), str(project.root))]
    for name, folder in (
        ("PDF", project.pdf_dir),
        ("TEMPLATE", project.template_dir),
        ("CONFIG", project.config_dir),
        ("AI_OUT", project.output_dir),
        ("LOG", project.log_dir),
        ("ERROR", project.error_dir),
    ):
        checks.append(_check(f"JOB/{name}", folder.is_dir(), str(folder)))

    config = cfg.load_config(project.config_path)
    if not config:
        checks.append(_check("config.json", True, "nav (izmanto automātisko plānu)", warning=True))
    else:
        problems = cfg.validate_config(config)
        checks.append(
            _check(
                "config.json",
                not problems,
                "derīgs" if not problems else "; ".join(problems[:4]),
            )
        )

    document = state.load_state(project.state_path, job_root=project.root)
    state_problems = list(document.problems)
    checks.append(
        _check(
            "state.json",
            not state_problems,
            "; ".join(state_problems[:3]) if state_problems else f"{len(document.items)} ieraksti",
            warning=bool(state_problems),
        )
    )
    checks.append(
        validation.check_folder_writable("CONFIG rakstāms", project.config_dir)
    )
    return PreflightSection("PROJECT", tuple(checks)), {"config": config, "state": document}


def _pdf_section(project: JobProject, plan) -> tuple[PreflightSection, dict]:
    """Every document of the project: present, readable, planned, not drifted."""
    checks: list[validation.CheckResult] = []
    facts: dict = {"documents": [], "missing_pdfs": [], "stale": [], "plan_errors": []}
    if not plan.documents:
        checks.append(_check("Dokumenti", False, "JOB/PDF nesatur nevienu PDF"))
        return PreflightSection("PDF", tuple(checks), facts), facts

    for document in plan.documents:
        counts = [
            int(document.current_page_count or document.page_count),
            len(document.pages),
        ]
        facts["documents"].append(
            {
                "pdf": document.pdf_name,
                "pdf_id": document.pdf_id,
                "status": document.status,
                "enabled": bool(document.enabled),
                "page_count": int(document.current_page_count or document.page_count),
                "stored_page_count": int(document.stored_page_count),
                "missing": bool(document.missing),
                "pages": int(counts[1]),
            }
        )
        if document.missing:
            facts["missing_pdfs"].append(document.pdf_name)
            checks.append(
                _check(
                    f"PDF {document.pdf_name}",
                    False,
                    "nav atrasts (plāns saglabāts)",
                    warning=True,
                )
            )
            continue
        if document.status == DOC_STATUS_STALE:
            facts["stale"].append(document.pdf_name)
            checks.append(
                _check(
                    f"PDF {document.pdf_name}",
                    False,
                    f"CONFIG STALE: saglabāts {document.stored_page_count}, tagad "
                    f"{document.current_page_count} - vajag RECONCILE",
                    warning=True,
                )
            )
        elif document.status == DOC_STATUS_PLAN_ERROR:
            facts["plan_errors"].append(document.pdf_name)
            # a document whose plan cannot be built is excluded from a run, exactly
            # like a missing or stale one: it blocks the project only when nothing
            # else is left to run (see "Izpildāmi dokumenti" below)
            checks.append(
                _check(
                    f"PDF {document.pdf_name}",
                    False,
                    "plānu nevar izveidot (PLAN ERROR)",
                    warning=True,
                )
            )
        else:
            checks.append(
                _check(
                    f"PDF {document.pdf_name}",
                    int(counts[1]) > 0,
                    f"{int(document.current_page_count or document.page_count)} lapas "
                    f"({document.count_method or '?'}), plānā {int(counts[1])}"
                    + ("" if document.enabled else " | izslēgts"),
                )
            )
        if document.warnings:
            checks.append(
                _check(
                    f"PDF {document.pdf_name} plāns",
                    False,
                    "; ".join(document.warnings[:2]),
                    warning=True,
                )
            )

    pdfs = sorted(path.name for path in project.find_pdfs())
    configured = {row["pdf"] for row in facts["documents"]}
    extra = [name for name in pdfs if name not in configured]
    checks.append(
        _check(
            "PDF mapē",
            not extra,
            f"{len(pdfs)} faili"
            + (f" | bez plāna: {', '.join(extra[:4])}" if extra else ""),
            warning=bool(extra),
        )
    )
    facts["pdfs"] = len(pdfs)
    facts["pages"] = sum(int(row["page_count"] or 0) for row in facts["documents"])
    # a document that is missing, stale or unplannable is NOT runnable: the queue
    # keeps its items but excludes them, so it cannot count as a working document
    facts["runnable_documents"] = [
        row["pdf"]
        for row in facts["documents"]
        if row["enabled"]
        and not row["missing"]
        and row["status"] not in (DOC_STATUS_STALE, DOC_STATUS_PLAN_ERROR)
    ]

    # a document that cannot run is only fatal when there is no other document left
    blocked = bool(facts["missing_pdfs"] or facts["stale"] or facts["plan_errors"])
    if blocked and not facts["runnable_documents"]:
        checks.append(
            _check(
                "Izpildāmi dokumenti",
                False,
                "neviens dokuments nav izpildāms (trūkst/STALE/PLAN ERROR)",
            )
        )
    else:
        checks.append(
            _check(
                "Izpildāmi dokumenti",
                bool(facts["runnable_documents"]),
                f"{len(facts['runnable_documents'])} no {len(facts['documents'])}",
                warning=blocked,
            )
        )
    return PreflightSection("PDF", tuple(checks), facts), facts


def _template_section(project: JobProject, plan, config: dict) -> tuple[PreflightSection, dict]:
    """Templates on disk vs. the templates the plan/config really needs.

    Two different findings live here:

    * a template the CONFIG names but the folder does not have - the page would
      silently fall back to the default template, so this is an ERROR
    * a page that inherits the default template while no MASTER exists - also an ERROR,
      because that page cannot be processed at all
    """
    checks: list[validation.CheckResult] = []
    available = {path.name.lower(): path for path in list_templates(project.template_dir)}

    named: dict[str, int] = {}
    for block in cfg.document_entries(config):
        for entry in block.get("pages") or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("template")
            if not name:
                continue
            named[str(name)] = named.get(str(name), 0) + 1
    missing_named = sorted(name for name in named if Path(name).name.lower() not in available)

    effective: dict[str, int] = {}
    for document in plan.documents:
        for job in document.pages:
            if job.template is None:
                continue
            name = Path(job.template).name
            effective[name] = effective.get(name, 0) + 1

    checks.append(
        _check(
            "TEMPLATE faili",
            bool(available),
            f"{len(available)} faili" if available else "mapē nav neviena .ai/.ait",
        )
    )
    checks.append(
        _check(
            "Konfigurētie template",
            not missing_named,
            f"{len(named)} nosaukti, visi atrasti"
            if not missing_named
            else "trūkst: " + ", ".join(missing_named[:6]),
        )
    )

    fallback = default_template(
        project.template_dir, (config.get("defaults") or {}).get("template")
    )
    # a page entry without its own template needs the default one; a document whose
    # plan could not be built at all is asked for the same thing from the config
    needs_fallback = any(
        not entry.get("template")
        for block in cfg.document_entries(config)
        for entry in (block.get("pages") or [])
        if isinstance(entry, dict)
    ) or any(job.template is None for document in plan.documents for job in document.pages)
    if needs_fallback and fallback is None:
        checks.append(
            _check(
                "Noklusētais template",
                False,
                "lappuses bez sava template prasa MASTER, bet tāda nav",
            )
        )
    elif fallback is not None:
        checks.append(_check("Noklusētais template", True, fallback.name))
    else:
        checks.append(
            _check(
                "Noklusētais template",
                True,
                "nav vajadzīgs (visām lapām ir savs)",
                warning=True,
            )
        )

    for name in sorted(effective)[:12]:
        path = available.get(name.lower())
        if path is not None:
            checks.append(validation.check_file(f"Template {name}", path))

    missing_templates = sorted(set(missing_named) | {
        name for name in effective if name.lower() not in available
    })
    facts = {
        "templates": len(available),
        "named": len(named),
        "needed": len(effective),
        "missing_templates": missing_templates,
        "default_template": fallback.name if fallback else "",
    }
    return PreflightSection("TEMPLATES", tuple(checks), facts), facts



def _output_section(
    project: JobProject, plan, queue_items, config: dict
) -> tuple[PreflightSection, dict]:
    """AI_OUT writable, output names valid and unique, overwrite policy."""
    checks: list[validation.CheckResult] = [
        validation.check_folder_writable("AI_OUT rakstāms", project.output_dir)
    ]

    # config level duplicates: an invalid config makes the plan fall back to the auto
    # plan, which is exactly the kind of silent surprise this report must surface
    config_names: dict[str, list[str]] = {}
    for block, entry in cfg.all_page_entries(config):
        if not entry.get("enabled", True):
            continue
        name = str(entry.get("output") or "").strip()
        if not name:
            continue
        config_names.setdefault(name.lower(), []).append(
            f"{Path(str(block.get('pdf') or '?')).name} l.{entry.get('page')}"
        )
    config_duplicates = {
        name: where for name, where in config_names.items() if len(where) > 1
    }

    names: dict[str, list[str]] = {}
    invalid: list[str] = []
    outside: list[str] = []
    per_document: dict[str, dict] = {}
    for document in plan.documents:
        entries: list[dict] = []
        for job in document.pages:
            name = job.output_name
            entries.append({"page": job.page, "enabled": job.enabled, "output": name})
            if not name:
                continue
            problems = validate_output_name(name)
            if problems:
                invalid.append(f"{document.pdf_name} l.{job.page}: {problems[0]}")
            if Path(job.output).parent != project.output_dir:
                outside.append(f"{document.pdf_name} l.{job.page}")
            if job.enabled:
                names.setdefault(name.lower(), []).append(f"{document.pdf_name} l.{job.page}")
        duplicates = find_duplicate_outputs(entries)
        if duplicates:
            per_document[document.pdf_name] = duplicates

    duplicates = {
        name: where
        for name, where in {**names, **config_duplicates}.items()
        if len(where) > 1
    }
    checks.append(
        _check("Output nosaukumi", not invalid, "derīgi" if not invalid else "; ".join(invalid[:4]))
    )
    checks.append(
        _check(
            "Output mapē AI_OUT",
            not outside,
            "visi AI_OUT" if not outside else "; ".join(outside[:4]),
        )
    )
    checks.append(
        _check(
            "Dublikāti",
            not duplicates,
            "nav"
            if not duplicates
            else "; ".join(
                f"{name}: {', '.join(where)}" for name, where in list(duplicates.items())[:3]
            ),
        )
    )
    checks.append(
        _check(
            "Dublikāti dokumentā",
            not per_document,
            "nav"
            if not per_document
            else "; ".join(f"{name}: {found}" for name, found in list(per_document.items())[:3]),
        )
    )

    existing = [
        f"{item.pdf_name} l.{item.page}"
        for item in queue_items
        if item.enabled and item.runnable and Path(item.output).is_file() and not item.overwrite
    ]
    checks.append(
        _check(
            "Esošie output",
            not existing,
            f"{len(existing)} lapas jau eksistē (bez overwrite tās tiks SKIP)"
            if existing
            else "nav konfliktu",
            warning=bool(existing),
        )
    )

    # a DONE page whose output disappeared means the delivered set is incomplete:
    # that is data loss and must never be reported as a finished project
    lost = [
        f"{item.pdf_name} l.{item.page}"
        for item in queue_items
        if item.state == state.DONE and not output_ready(item.output)[0]
    ]
    checks.append(
        _check(
            "DONE output faili",
            not lost,
            f"{len(lost)} DONE lapām output nav atrasts: {', '.join(lost[:6])} "
            f"(RESET šīs lapas un palaid no jauna)"
            if lost
            else "visi DONE output faili ir vietā",
        )
    )

    facts = {
        "output_writable": bool(validation.is_writable(project.output_dir)),
        "duplicate_outputs": sorted(duplicates),
        "invalid_outputs": invalid,
        "existing_outputs": existing,
        "lost_outputs": lost,
    }
    return PreflightSection("OUTPUT", tuple(checks), facts), facts


def _queue_section(project: JobProject, plan, state_document) -> tuple[PreflightSection, dict]:
    """Can the queue be built, is every item valid and unique?"""
    checks: list[validation.CheckResult] = []
    items = list(state_document.items)
    counts = state.counts_of(items)
    facts: dict = {
        "items": len(items),
        "counts": {name: int(counts.get(name, 0)) for name in state.VALID_STATES},
    }

    problems = list(state_document.problems)
    checks.append(
        _check(
            "state.json derīgs",
            not problems,
            "; ".join(problems[:3]) if problems else f"{len(items)} ieraksti",
            warning=bool(problems),
        )
    )

    ids: dict[str, int] = {}
    for item in items:
        ids[item.job_id] = ids.get(item.job_id, 0) + 1
    duplicate_ids = sorted(job_id for job_id, count in ids.items() if count > 1 and job_id)
    checks.append(
        _check(
            "Unikāli job_id",
            not duplicate_ids,
            "ok" if not duplicate_ids else ", ".join(duplicate_ids[:5]),
        )
    )

    planned_documents = {document.pdf_id for document in plan.documents}
    known_pages = {
        (document.pdf_id, job.page) for document in plan.documents for job in document.pages
    }
    orphan = [
        item.job_id
        for item in items
        if item.document not in planned_documents or (item.document, item.page) not in known_pages
    ]
    checks.append(
        _check(
            "Rindas atbilstība plānam",
            not orphan,
            "ok" if not orphan else f"{len(orphan)} ieraksti ārpus plāna: " + ", ".join(orphan[:4]),
            warning=bool(orphan),
        )
    )

    running = [item.job_id for item in items if item.state == state.RUNNING]
    checks.append(
        _check(
            "RUNNING ieraksti",
            not running,
            "nav"
            if not running
            else f"{len(running)} ieraksti palikuši RUNNING: " + ", ".join(running[:4]),
            warning=bool(running),
        )
    )

    runnable = [item for item in items if item.runnable]
    facts["runnable"] = len(runnable)
    if items:
        facts["queue"] = f"READY ({len(items)} lapas)"
        detail = f"{len(runnable)} no {len(items)}"
        if not runnable:
            detail += " - nekas nav WAITING/INTERRUPTED"
        checks.append(_check("Izpildāmas lapas", bool(runnable), detail, warning=not runnable))
    else:
        facts["queue"] = "tukša"
        checks.append(_check("Izpildāmas lapas", True, "rinda vēl nav veidota", warning=True))

    counts_summary = " ".join(f"{name}={counts.get(name, 0)}" for name in state.VALID_STATES)
    checks.append(_check("Stāvokļi", True, counts_summary or "nav ierakstu"))
    return PreflightSection("QUEUE", tuple(checks), facts), facts


def _illustrator_section(
    project: JobProject,
    *,
    adapter=None,
    illustrator_available: bool | None = None,
    illustrator_version: str = "",
    worker_jsx: str | Path | None = None,
    cleanup_jsx: str | Path | None = None,
    runtime_dir: str | Path | None = None,
) -> tuple[PreflightSection, dict]:
    """The Illustrator side: the worker files, the runtime folder, COM."""
    from .. import paths as package_paths

    worker_jsx = worker_jsx or package_paths.worker_jsx()
    cleanup_jsx = cleanup_jsx or package_paths.cleanup_jsx()
    runtime_dir = runtime_dir or package_paths.runtime_dir()
    checks: list[validation.CheckResult] = [
        validation.check_file("worker.jsx", worker_jsx),
        validation.check_file("cleanup.jsx", cleanup_jsx),
        validation.check_folder_writable("runtime mape", runtime_dir),
    ]
    facts: dict = {"illustrator": "", "illustrator_version": illustrator_version}

    if illustrator_available is None and adapter is not None:
        try:
            report = adapter.health_check()
            illustrator_available = bool(report.get("ok"))
            info = report.get("illustrator") or {}
            if isinstance(info, dict) and info.get("version"):
                illustrator_version = str(info["version"])
        except Exception as exc:  # noqa: BLE001 - a broken COM environment is a finding
            illustrator_available = False
            facts["illustrator_error"] = str(exc)

    if illustrator_available is None:
        checks.append(
            _check(
                "Illustrator",
                False,
                "nav pārbaudīts (PREFLIGHT PROJECT to pārbauda)",
                warning=True,
            )
        )
        facts["illustrator"] = "nav pārbaudīts"
    elif illustrator_available:
        checks.append(
            _check(
                "Illustrator",
                True,
                f"READY (versija {illustrator_version})" if illustrator_version else "READY",
            )
        )
        facts["illustrator"] = f"READY {illustrator_version}".strip()
    else:
        detail = facts.get("illustrator_error") or "COM nav sasniedzams"
        checks.append(_check("Illustrator", False, f"nav pieejams: {detail}"))
        facts["illustrator"] = "NAV PIEJAMS"
    facts["illustrator_version"] = illustrator_version
    return PreflightSection("ILLUSTRATOR", tuple(checks), facts), facts


def _system_section(project: JobProject) -> tuple[PreflightSection, dict]:
    """Disk space and the folders a run/report needs to write."""
    facts, disk_check = _disk_facts(project)
    checks: list[validation.CheckResult] = [
        disk_check,
        validation.check_folder_writable("LOG rakstāms", project.log_dir),
    ]
    reports_folder = report_module.reports_dir(project)
    try:
        reports_folder.mkdir(parents=True, exist_ok=True)
        writable = validation.is_writable(reports_folder)
        checks.append(
            _check(
                "Report mape",
                writable,
                str(reports_folder) if writable else f"nav rakstīšanas tiesību: {reports_folder}",
            )
        )
    except OSError as exc:  # noqa: BLE001
        checks.append(_check("Report mape", False, f"nevar izveidot: {exc}"))
    facts["reports"] = len(report_module.list_reports(project))
    checks.append(_check("Iepriekšējie reporti", True, f"{facts['reports']} faili"))
    return PreflightSection("SYSTEM", tuple(checks), facts), facts


# ---------------------------------------------------------------------- the action


def run_preflight(
    project: JobProject,
    *,
    adapter=None,
    check_illustrator: bool = True,
    illustrator_available: bool | None = None,
    illustrator_version: str = "",
    worker_jsx: str | Path | None = None,
    cleanup_jsx: str | Path | None = None,
    runtime_dir: str | Path | None = None,
    when: datetime | None = None,
) -> PreflightReport:
    """Check the whole project and return one report.

    Read only: it plans the project to look at what a run would do, but it never
    writes `config.json`, `state.json` or an output. The only doors it may open are
    the report folder (created so the first pass can write into it) and Illustrator
    when `check_illustrator=True` with an adapter.
    """
    from .pagejob import PagePlanError, plan_project

    started = state.now_stamp(when)
    facts: dict = {}

    project_section, project_facts = _project_section(project)
    state_document = project_facts["state"]
    config = project_facts["config"]
    sections = [project_section]

    try:
        plan = plan_project(project)
        plan_error = ""
    except (PagePlanError, OSError) as exc:  # an unplannable project is a finding
        plan = None
        plan_error = str(exc)
        sections.append(
            PreflightSection(
                "PDF", (_check("Plāns", False, plan_error),), {"plan_error": plan_error}
            )
        )

    if plan is not None:
        for section, section_facts in (
            _pdf_section(project, plan),
            _template_section(project, plan, config),
            _output_section(project, plan, state_document.items, config),
        ):
            sections.append(section)
            facts.update(section_facts)

    if plan is not None:
        queue_section, queue_facts = _queue_section(project, plan, state_document)
    else:
        queue_section = PreflightSection("QUEUE", (_check("Rinda", False, plan_error),), {})
        queue_facts = {}
    sections.append(queue_section)
    facts.update(queue_facts)

    check_com = bool(check_illustrator) and (adapter is not None or illustrator_available is not None)
    illustrator_section, illustrator_facts = _illustrator_section(
        project,
        adapter=adapter if check_com else None,
        illustrator_available=illustrator_available if not check_com else None,
        illustrator_version=illustrator_version,
        worker_jsx=worker_jsx,
        cleanup_jsx=cleanup_jsx,
        runtime_dir=runtime_dir,
    )
    sections.append(illustrator_section)
    facts.update(illustrator_facts)

    system_section, system_facts = _system_section(project)
    sections.append(system_section)
    facts.update(system_facts)

    order = {key: index for index, key in enumerate(SECTION_ORDER)}
    sections.sort(key=lambda item: order.get(item.key, len(order)))

    problems = tuple(
        f"[{section.key}] {check.name}: {check.detail}"
        for section in sections
        for check in section.errors
    )
    warnings = tuple(
        f"[{section.key}] {check.name}: {check.detail}"
        for section in sections
        for check in section.warnings
    )

    return PreflightReport(
        job=project.root.name,
        root=str(project.root),
        started=started,
        finished=state.now_stamp(),
        sections=tuple(sections),
        facts=facts,
        problems=problems,
        warnings=warnings,
    )








