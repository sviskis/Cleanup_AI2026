"""Preflight validation - run BEFORE Illustrator is touched.

Checks the things that would otherwise fail in the middle of a batch:

    PDF exists and its page count is valid
    template exists (and is a real file)
    output folder exists and is writable
    worker.jsx / cleanup.jsx are present
    runtime folder is writable
    Illustrator is reachable (optional, skipped with --no-illustrator)
    output file name is valid and unique
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .naming import validate_output_name
from .project import JobProject

OK = "[OK]  "
FAIL = "[FAIL]"
WARN = "[!]   "


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    warning: bool = False

    def format(self, width: int = 34) -> str:
        tag = WARN if (self.warning and not self.ok) else (OK if self.ok else FAIL)
        return f"{tag} {self.name.ljust(width)} {self.detail}".rstrip()


def is_writable(folder: Path) -> bool:
    """Create and remove a probe file to prove write access."""
    try:
        if not folder.is_dir():
            return False
        probe = folder / "__write_test.tmp"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def check_file(label: str, path: str | Path | None) -> CheckResult:
    if not path:
        return CheckResult(label, False, "nav norādīts")
    file_path = Path(path)
    if not file_path.is_file():
        return CheckResult(label, False, f"nav atrasts: {file_path}")
    return CheckResult(label, True, str(file_path))


def check_folder_writable(label: str, folder: str | Path | None) -> CheckResult:
    if not folder:
        return CheckResult(label, False, "nav norādīts")
    folder_path = Path(folder)
    if not folder_path.is_dir():
        return CheckResult(label, False, f"nav mapes: {folder_path}")
    if not is_writable(folder_path):
        return CheckResult(label, False, f"nav rakstīšanas tiesību: {folder_path}")
    return CheckResult(label, True, str(folder_path))


def preflight(
    project: JobProject,
    *,
    pdf: str | Path | None = None,
    page: int | None = None,
    page_count: int | None = None,
    template: str | Path | None = None,
    output: str | Path | None = None,
    worker_jsx: str | Path | None = None,
    cleanup_jsx: str | Path | None = None,
    runtime_dir: str | Path | None = None,
    illustrator_available: bool | None = None,
) -> list[CheckResult]:
    """Build the full preflight report for one job (or for a whole project)."""
    checks: list[CheckResult] = []

    checks.append(CheckResult("JOB mape", project.root.is_dir(), str(project.root)))
    for name in ("PDF", "TEMPLATE", "CONFIG", "AI_OUT", "LOG"):
        folder = project.root / name
        checks.append(CheckResult(f"JOB/{name}", folder.is_dir(), str(folder)))
    checks.append(check_folder_writable("AI_OUT rakstāms", project.output_dir))
    checks.append(check_folder_writable("CONFIG rakstāms", project.config_dir))
    checks.append(check_folder_writable("LOG rakstāms", project.log_dir))

    if pdf:
        pdf_path = Path(str(pdf))
        resolved = pdf_path if pdf_path.is_absolute() else project.pdf_dir / pdf_path.name
        checks.append(check_file("PDF fails", resolved))
        if page_count is None and resolved.is_file():
            try:
                from .pdf_info import count_pages

                page_count, method = count_pages(resolved)
                checks.append(CheckResult("PDF lapas", page_count > 0, f"{page_count} ({method})"))
            except Exception as exc:  # noqa: BLE001
                checks.append(CheckResult("PDF lapas", False, str(exc)))

    if page is not None and page_count is not None:
        checks.append(
            CheckResult(
                "Lapas numurs",
                1 <= int(page) <= int(page_count),
                f"{page} no {page_count}",
            )
        )

    if template:
        template_path = Path(template)
        if not template_path.is_absolute():
            template_path = project.template_dir / template_path.name
        checks.append(check_file("Template fails", template_path))

    if output:
        output_path = Path(str(output))
        name = output_path.name
        problems = validate_output_name(name)
        checks.append(
            CheckResult("Output nosaukums", not problems, name if not problems else "; ".join(problems))
        )
        parent = output_path.parent if output_path.is_absolute() else project.output_dir
        checks.append(check_folder_writable("Output mape rakstāma", parent))

    checks.append(check_file("worker.jsx", worker_jsx))
    checks.append(check_file("cleanup.jsx", cleanup_jsx))
    checks.append(check_folder_writable("runtime mape", runtime_dir))

    if illustrator_available is not None:
        checks.append(
            CheckResult(
                "Illustrator",
                bool(illustrator_available),
                "pieejams" if illustrator_available else "nav pieejams (COM)",
                warning=not illustrator_available,
            )
        )

    return checks


def has_failures(checks: list[CheckResult]) -> bool:
    """True when at least one hard (non warning) check failed."""
    return any((not check.ok) and (not check.warning) for check in checks)


def format_report(checks: list[CheckResult]) -> str:
    """Human readable preflight report."""
    lines = [check.format() for check in checks]
    failures = sum(1 for check in checks if not check.ok and not check.warning)
    warnings = sum(1 for check in checks if not check.ok and check.warning)
    lines.append("")
    lines.append(f"rezultāts: {len(checks)} pārbaudes, kļūdas={failures}, brīdinājumi={warnings}")
    return os.linesep.join(lines)
