"""Production diagnostics: what a packaged build can tell a user without Illustrator.

`--diagnose` prints this; the packaged executable runs it before the GUI opens and, if
something is missing, says so in plain language instead of failing later.

    pywin32 available (COM)          win32com import / the pywintypes api
    internal packaging status        frozen, bundle folder, python, architecture
    required assets                  worker.jsx, cleanup.jsx, json2.js (with their paths)
    version                          VERSION file / package version
    writable folders                 runtime (handoff) and the application log folder
    Illustrator installed            registry ProgID + install folder (no launch)
    Illustrator reachable            only on request (COM attach) - an explicit action

Nothing here launches Illustrator unless `check_illustrator=True`, so opening the GUI
never touches COM (the same rule the adapter follows).
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, paths

OK = "[OK]  "
FAIL = "[FAIL]"
WARN = "[!]   "

PROGID = "Illustrator.Application"


@dataclass(frozen=True)
class DiagnosticItem:
    """One line of the report."""

    name: str
    ok: bool
    detail: str = ""
    warning: bool = False

    def format(self, width: int = 30) -> str:
        tag = WARN if (self.warning and not self.ok) else (OK if self.ok else FAIL)
        return f"{tag} {self.name.ljust(width)} {self.detail}".rstrip()


@dataclass
class Diagnostics:
    """The whole report, plus the answers a startup check cares about."""

    items: list[DiagnosticItem] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    def add(self, item: DiagnosticItem) -> DiagnosticItem:
        self.items.append(item)
        return item

    @property
    def errors(self) -> list[str]:
        return [
            f"{item.name}: {item.detail}"
            for item in self.items
            if not item.ok and not item.warning
        ]

    @property
    def warnings(self) -> list[str]:
        return [f"{item.name}: {item.detail}" for item in self.items if not item.ok and item.warning]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_text(self) -> str:
        lines = [item.format() for item in self.items]
        lines.append("")
        lines.append(
            f"rezultāts: {len(self.items)} pārbaudes, kļūdas={len(self.errors)}, "
            f"brīdinājumi={len(self.warnings)}"
        )
        # "\n" on purpose: os.linesep would become an empty line on a Windows console
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "version": __version__,
            "ok": self.ok,
            "facts": dict(self.facts),
            "items": [
                {
                    "name": item.name,
                    "ok": bool(item.ok),
                    "warning": bool(item.warning),
                    "detail": item.detail,
                }
                for item in self.items
            ],
            "errors": self.errors,
            "warnings": self.warnings,
        }


def pywin32_status() -> tuple[bool, str]:
    """Is the COM layer we need actually importable in this build?"""
    try:
        import win32com.client  # noqa: F401
        import pythoncom  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - a missing/broken pywin32 is a finding
        return False, str(exc)
    return True, "win32com + pythoncom"


def illustrator_installed() -> tuple[bool, str]:
    """Is Illustrator installed? Registry + folders only - this never launches it.

    Two independent hints: the COM ProgID (which the adapter needs) and an Adobe
    install folder that looks like Illustrator. Either one is enough to say
    "installed"; "can we talk to it" is the reachable check.
    """
    progid = False
    try:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, PROGID):
                progid = True
        except OSError:
            progid = False
    except Exception:  # noqa: BLE001 - a non Windows build has no registry
        progid = False

    folders: list[str] = []
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if not base:
            continue
        adobe = Path(base) / "Adobe"
        if not adobe.is_dir():
            continue
        try:
            folders.extend(
                path.name for path in adobe.iterdir() if "illustrator" in path.name.lower()
            )
        except OSError:
            continue

    if progid and folders:
        return True, f"COM ProgID + {', '.join(sorted(folders)[:2])}"
    if progid:
        return True, "COM ProgID (Illustrator.Application)"
    if folders:
        return True, f"instalācijas mape: {', '.join(sorted(folders)[:2])}"
    return False, "nav atrasts (nav COM ProgID, nav Adobe\\Adobe Illustrator* mape)"


def illustrator_reachable(adapter=None) -> tuple[bool, str]:
    """Can we talk to Illustrator right now? Explicit only - this may launch it."""
    try:
        if adapter is None:
            from .adapters.illustrator import IllustratorAdapter

            adapter = IllustratorAdapter(
                worker_jsx=paths.worker_jsx(), runtime_dir=paths.runtime_dir(), timeout=5.0
            )
        report = adapter.health_check()
    except Exception as exc:  # noqa: BLE001 - a broken COM environment is a finding
        return False, str(exc)
    if not report.get("ok"):
        return False, "COM nav sasniedzams"
    info = report.get("illustrator") or {}
    version = info.get("version") if isinstance(info, dict) else ""
    return True, f"READY{(' ' + str(version)) if version else ''}"


def run_diagnostics(*, check_illustrator: bool = False, adapter=None) -> Diagnostics:
    """Build the production diagnostic report.

    `check_illustrator=True` may attach to (or launch) Illustrator - it is only used
    by an explicit `--diagnose --with-illustrator` / health request, never by opening
    the GUI.
    """
    report = Diagnostics()
    report.facts.update(
        {
            "version": __version__,
            "frozen": paths.is_frozen(),
            "app_root": str(paths.app_root()),
            "layout": "installed" if paths.is_frozen() else "source",
        }
    )

    report.add(DiagnosticItem("Versija", bool(__version__), __version__))
    report.add(
        DiagnosticItem(
            "Izpilde",
            True,
            "iepakota .exe" if paths.is_frozen() else "avota kods (python app.py)",
        )
    )
    report.add(
        DiagnosticItem(
            "Python / arhitektūra",
            True,
            f"{platform.python_version()} | {platform.machine()} | "
            f"{'64-bit' if sys.maxsize > 2**32 else '32-bit'}",
        )
    )
    report.add(
        DiagnosticItem(
            "PyInstaller",
            True,
            f"iepakots (bundle: {paths.bundle_dir()})" if paths.bundle_dir() else "nav iepakots",
            warning=not paths.is_frozen(),
        )
    )

    win32_ok, win32_detail = pywin32_status()
    report.facts["pywin32"] = win32_ok
    report.add(DiagnosticItem("pywin32 / COM", win32_ok, win32_detail))

    for label, path in (
        ("worker.jsx", paths.worker_jsx()),
        ("cleanup.jsx", paths.cleanup_jsx()),
        ("json2.js", paths.json_polyfill_jsx()),
    ):
        report.add(DiagnosticItem(f"JSX {label}", path.is_file(), str(path)))
    report.facts["jsx_dir"] = str(paths.jsx_dir())

    defaults = paths.default_config_file()
    report.add(
        DiagnosticItem(
            "Noklusētais config",
            defaults.is_file(),
            str(defaults),
            warning=not defaults.is_file(),
        )
    )

    for label, folder in (("runtime mape", paths.runtime_dir()), ("logu mape", paths.log_dir())):
        shown = str(folder)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / "__diagnose.tmp"
            probe.write_text("probe", encoding="utf-8")
            probe.unlink()
            writable = True
        except OSError as exc:
            writable = False
            shown = f"{folder} ({exc})"
        report.add(DiagnosticItem(f"{label} rakstāma", writable, shown))

    installed, installed_detail = illustrator_installed()
    report.facts["illustrator_installed"] = installed
    report.add(
        DiagnosticItem("Illustrator instalēts", installed, installed_detail, warning=not installed)
    )

    if check_illustrator:
        reachable, detail = illustrator_reachable(adapter=adapter)
        report.facts["illustrator_reachable"] = reachable
        report.add(DiagnosticItem("Illustrator sasniedzams", reachable, detail))
    else:
        report.add(
            DiagnosticItem(
                "Illustrator sasniedzams",
                True,
                "nav pārbaudīts (--with-illustrator vai HEALTH CHECK)",
                warning=True,
            )
        )

    report.facts["cwd"] = os.getcwd()
    report.add(DiagnosticItem("Darba mape (cwd)", True, os.getcwd()))
    return report
