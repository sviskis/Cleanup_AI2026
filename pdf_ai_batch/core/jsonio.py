"""Atomic JSON file IO for the Python <-> JSX contract.

Every file the orchestrator and the worker exchange is written atomically:
the payload goes to a temporary file in the same folder, is flushed to disk and
only then renamed over the target. A reader therefore either sees the previous
file or the complete new one, never a half written file.

This module has no third party dependencies on purpose: it is used by the
config, the state (later) and the adapter.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_ENCODING = "utf-8"


def read_text(path: str | os.PathLike[str], encoding: str = DEFAULT_ENCODING) -> str:
    """Return the file content, or "" when the file does not exist."""
    file_path = Path(path)
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding=encoding)


def write_text_atomic(
    path: str | os.PathLike[str],
    text: str,
    encoding: str = DEFAULT_ENCODING,
) -> Path:
    """Write text through a temporary file and an atomic rename."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(file_path.name + ".tmp")
    with open(tmp_path, "w", encoding=encoding, newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, file_path)
    return file_path


def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
    """Read JSON; return `default` when the file is missing or unreadable."""
    text = read_text(path)
    if not text.strip():
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def write_json_atomic(
    path: str | os.PathLike[str],
    data: Any,
    indent: int | None = 2,
) -> Path:
    """Serialise `data` as UTF-8 JSON and write it atomically."""
    text = json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=False)
    return write_text_atomic(path, text + "\n")


def delete_if_exists(path: str | os.PathLike[str]) -> bool:
    """Remove a file when it exists. Returns True when something was removed."""
    file_path = Path(path)
    try:
        file_path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def wait_for_json(
    path: str | os.PathLike[str],
    validator,
    timeout: float,
    poll_interval: float = 0.25,
    on_poll=None,
) -> tuple[dict | None, str]:
    """Wait until `validator(data)` accepts the JSON file at `path`.

    Returns (data, "") on success and (None, reason) on failure, where reason is
    "timeout" when nothing acceptable arrived in time, or "invalid" when the file
    kept being unparsable until the deadline.

    `validator` receives the parsed object and must return True to accept it.
    `on_poll` is an optional callback receiving every rejected candidate, which
    the adapter uses to log a worker result that does not belong to this run.
    """
    file_path = Path(path)
    deadline = time.monotonic() + max(0.0, timeout)
    saw_invalid = False
    while True:
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding=DEFAULT_ENCODING))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                saw_invalid = True
                data = None
            if isinstance(data, dict) and validator(data):
                return data, ""
            if isinstance(data, dict) and on_poll is not None:
                on_poll(data)
        if time.monotonic() >= deadline:
            return None, ("invalid" if saw_invalid else "timeout")
        time.sleep(poll_interval)
