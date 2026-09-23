"""Logging for the orchestrator.

Two destinations, both inside the JOB folder (so a JOB is self contained):

    LOG/app.log                 everything, appended over sessions
    LOG/batch_<timestamp>.log   one file per batch run

Nothing relies on the GUI text: the same records go to disk.

Python's `logging` format is used with the same style as the JSX side:
    2026-09-23 15:30:10 | INFO | Script started
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
APP_LOG_NAME = "app.log"
BATCH_LOG_PREFIX = "batch"
CONSOLE_LOG_NAME = "console.log"
GUI_HANDLER_NAME = "gui"


def _attach_streams() -> None:
    """A windowed build (pythonw / PyInstaller --noconsole) has no stdout/stderr.

    Attach to the console it was started from when there is one (so `--diagnose`
    prints into cmd), otherwise send the text to the application log folder, so
    printing never raises and the information is never lost. In development both
    streams exist and nothing happens here.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return

    if sys.platform == "win32":
        try:
            import ctypes

            if ctypes.windll.kernel32.AttachConsole(-1):  # the parent process console
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                return
        except Exception:  # noqa: BLE001 - no console: fall back to a file
            pass

    from . import paths

    try:
        target = paths.log_dir() / CONSOLE_LOG_NAME
        target.parent.mkdir(parents=True, exist_ok=True)
        stream = open(target, "a", encoding="utf-8", errors="replace")
        sys.stdout = stream
        sys.stderr = stream
    except OSError:  # pragma: no cover - a completely hostile environment
        import io

        sys.stdout = io.StringIO()
        sys.stderr = sys.stdout


def configure_console() -> None:
    """Force UTF-8 output and make the Windows console read it as UTF-8.

    The Windows console defaults to a legacy code page (cp1252 / cp1257) which
    cannot encode Latvian characters, so printing "Apstrādā" would raise
    UnicodeEncodeError. Reconfiguring the streams fixes the writer; switching the
    console output code page to 65001 fixes the reader, otherwise a PowerShell
    capture would show mojibake.
    """
    _attach_streams()

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - stream without buffer
            pass

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # UTF-8
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001 - no console (service, redirected)
            pass


def batch_log_path(log_dir: str | Path, when: datetime | None = None) -> Path:
    """LOG/batch_<YYYYmmdd_HHMMSS>.log"""
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return Path(log_dir) / f"{BATCH_LOG_PREFIX}_{stamp}.log"


def setup_logging(
    log_dir: str | Path | None,
    *,
    level: int = logging.INFO,
    console: bool = True,
    batch_log: bool = False,
    logger_name: str = "pdf_ai_batch",
) -> logging.Logger:
    """Configure (or reconfigure) the package logger.

    `batch_log=True` adds LOG/batch_<timestamp>.log next to LOG/app.log.
    Passing log_dir=None keeps only the console handler, which the tests use.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    if console:
        stream = logging.StreamHandler(stream=sys.stdout)
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    if log_dir:
        folder = Path(log_dir)
        folder.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(folder / APP_LOG_NAME, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        if batch_log:
            batch_handler = logging.FileHandler(batch_log_path(folder), encoding="utf-8")
            batch_handler.setFormatter(formatter)
            logger.addHandler(batch_handler)

    return logger


def get_logger(name: str = "pdf_ai_batch") -> logging.Logger:
    return logging.getLogger(name)
