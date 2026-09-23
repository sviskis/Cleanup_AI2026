"""Repository relative paths (JSX side, runtime handoff folder).

Everything is derived from this file's location, so the project can be copied
anywhere without configuration:

    <repo>/pdf_ai_batch/paths.py   <- this file
    <repo>/jsx/worker.jsx
    <repo>/jsx/cleanup.jsx
    <repo>/runtime/                <- handoff folder (git ignored)

The environment variable PDF_AI_BATCH_ROOT overrides the detected root, which
the tests use to point at a temporary repository.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT_ENV_VAR = "PDF_AI_BATCH_ROOT"


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def repo_root() -> Path:
    """Repository root: the folder that contains pdf_ai_batch/, jsx/ and src/."""
    override = os.environ.get(ROOT_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    return package_dir().parent


def jsx_dir() -> Path:
    return repo_root() / "jsx"


def worker_jsx() -> Path:
    return jsx_dir() / "worker.jsx"


def cleanup_jsx() -> Path:
    return jsx_dir() / "cleanup.jsx"


def json_polyfill_jsx() -> Path:
    return jsx_dir() / "json2.js"


def runtime_dir() -> Path:
    return repo_root() / "runtime"


def legacy_dir() -> Path:
    return repo_root() / "legacy"


def config_dir() -> Path:
    return repo_root() / "config"


def default_config_file() -> Path:
    return config_dir() / "default_config.json"


def tools_dir() -> Path:
    return repo_root() / "tools"


def describe() -> dict[str, str]:
    """Small helper for --diagnose output."""
    return {
        "repo_root": str(repo_root()),
        "jsx_dir": str(jsx_dir()),
        "worker_jsx": str(worker_jsx()),
        "cleanup_jsx": str(cleanup_jsx()),
        "json_polyfill": str(json_polyfill_jsx()),
        "runtime_dir": str(runtime_dir()),
    }
