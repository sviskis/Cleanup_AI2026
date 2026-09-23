"""Where the application finds its files - in the repository AND as an installed app.

Two layouts are supported from the same code:

    development (the repository)          production (dist/Cleanup AI 2026)
    <repo>/pdf_ai_batch/paths.py          <install>/Cleanup AI 2026.exe
    <repo>/jsx/*.jsx                      <install>/program/...   (app + runtime)
    <repo>/runtime/                       <install>/jsx/*.jsx
    <repo>/logs/                          <install>/config/default_config.json
                                          <install>/runtime/  or  %LOCALAPPDATA%/...

Rules

* `app_root()` is the folder that holds the executable (frozen) or the repository
  (source). Everything else is derived from it, **never** from the current working
  directory (Illustrator runs the worker with its own cwd).
* `PDF_AI_BATCH_HOME` is the production override (an installed app can be moved or
  read only); `PDF_AI_BATCH_ROOT` stays the development/test override the tests use.
* read-only assets are searched (install folder, PyInstaller bundle, repository), so a
  missing folder is reported by path, never by a mysterious failure.
* writable folders fall back to a per user location when the install folder is not
  writable - production logs never have to be written into Program Files.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_ENV_VAR = "PDF_AI_BATCH_ROOT"
HOME_ENV_VAR = "PDF_AI_BATCH_HOME"
APP_FOLDER_NAME = "Cleanup AI 2026"

#: the fixed layout of an installed application
PROGRAM_FOLDER = "program"
JSX_FOLDER = "jsx"
CONFIG_FOLDER = "config"
RUNTIME_FOLDER = "runtime"
LOGS_FOLDER = "logs"


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def is_frozen() -> bool:
    """True inside a PyInstaller build (``sys.frozen`` is set by the bootloader)."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path | None:
    """PyInstaller's extraction folder (`sys._MEIPASS`), or None in development."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


def executable_path() -> Path | None:
    """The running .exe when frozen (None in development)."""
    return Path(sys.executable) if is_frozen() else None


def home_override() -> Path | None:
    """`PDF_AI_BATCH_HOME` - an explicit install folder (production override)."""
    override = os.environ.get(HOME_ENV_VAR)
    return Path(override).expanduser().resolve() if override else None


def app_root() -> Path:
    """The folder the application was started from.

    Frozen: the folder of the .exe (so the distribution can be moved as a whole).
    Source: the repository root. `PDF_AI_BATCH_HOME` wins over both, the tests'
    `PDF_AI_BATCH_ROOT` only applies to a source checkout.
    """
    override = home_override()
    if override is not None:
        return override
    if is_frozen():
        return Path(sys.executable).resolve().parent
    root = os.environ.get(ROOT_ENV_VAR)
    if root:
        return Path(root).expanduser().resolve()
    return package_dir().parent


def install_jsx_dir() -> Path:
    """Where the JSX worker lives in an installed application (``<install>/jsx``)."""
    return app_root() / JSX_FOLDER


def _first_existing(candidates: list[Path], fallback: Path) -> Path:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return fallback


def jsx_dir() -> Path:
    """The folder with worker.jsx / cleanup.jsx / json2.js.

    Order: the install folder, then the PyInstaller bundle, then the repository
    layout. The first existing folder wins; when none exists the install folder is
    returned, so `--diagnose` can print which path was expected.
    """
    candidates: list[Path] = []
    if is_frozen() or home_override() is not None:
        candidates.append(install_jsx_dir())
        bundled = bundle_dir()
        if bundled is not None:
            candidates.append(bundled / JSX_FOLDER)
    candidates.append(repo_root() / JSX_FOLDER)
    return _first_existing(candidates, candidates[0])



def worker_jsx() -> Path:
    return jsx_dir() / "worker.jsx"


def cleanup_jsx() -> Path:
    return jsx_dir() / "cleanup.jsx"


def json_polyfill_jsx() -> Path:
    return jsx_dir() / "json2.js"


def config_dir() -> Path:
    """Default configuration of the installation (`<install>/config`)."""
    return app_root() / CONFIG_FOLDER


def default_config_file() -> Path:
    return config_dir() / "default_config.json"


def user_data_dir() -> Path:
    """Per user folder for anything writable: `%LOCALAPPDATA%/Cleanup AI 2026`."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / APP_FOLDER_NAME


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / "__write_test.tmp"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def runtime_dir() -> Path:
    """The JSON handoff folder between Python and the JSX worker.

    `<install>/runtime` when that is writable, otherwise the per user folder. Both
    Python and Illustrator write here, so a read only install must not be required.
    The returned folder is created (best effort).
    """
    candidate = app_root() / RUNTIME_FOLDER
    if _writable(candidate):
        return candidate
    fallback = user_data_dir() / RUNTIME_FOLDER
    _writable(fallback)  # best effort: the caller may write a file here right away
    return fallback


def log_dir() -> Path:
    """Application level logs (JOB logs always stay in `JOB/LOG`).

    Development: `<repo>/logs`. Production: `<install>/logs` when writable, else
    `%LOCALAPPDATA%/Cleanup AI 2026/logs` - never Program Files. Created best effort.
    """
    candidate = app_root() / LOGS_FOLDER
    if _writable(candidate):
        return candidate
    fallback = user_data_dir() / LOGS_FOLDER
    _writable(fallback)
    return fallback


def repo_root() -> Path:
    """Source checkout root: the folder with pdf_ai_batch/, jsx/ and src/."""
    override = os.environ.get(ROOT_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return app_root()
    return package_dir().parent


def legacy_dir() -> Path:
    return app_root() / "legacy"


def tools_dir() -> Path:
    return app_root() / "tools"


def describe() -> dict[str, str]:
    """Small helper for --diagnose output."""
    return {
        "app_root": str(app_root()),
        "layout": "installed" if is_frozen() else "source",
        "jsx_dir": str(jsx_dir()),
        "worker_jsx": str(worker_jsx()),
        "cleanup_jsx": str(cleanup_jsx()),
        "json_polyfill": str(json_polyfill_jsx()),
        "runtime_dir": str(runtime_dir()),
        "log_dir": str(log_dir()),
    }
