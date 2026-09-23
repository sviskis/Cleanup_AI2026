"""Output naming and job identifiers.

Python OWNS output names (the worker receives the finished path). The scheme is
fixed by the contract in docs/ARCHITECTURE.md:

    <pdf stem>__<page, zero padded>.ai        e.g. manual__017.ai

The padding width follows the page count so that a natural sort of AI_OUT matches
the page order: 42 pages -> 3 digits, 1000 pages -> 4 digits, minimum 3.

The older application used "<stem>_p03.ai"; that scheme lives only in the frozen
legacy baseline (legacy/current_working_v10.jsx) and is intentionally not used
for new jobs.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

DEFAULT_PATTERN = "{stem}__{page:0{width}d}.ai"
MIN_WIDTH = 3
DEFAULT_EXTENSION = ".ai"
RUN_ID_FORMAT = "%Y%m%d-%H%M%S"

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def page_width(page_count: int) -> int:
    """Digits used for the page number (at least 3)."""
    try:
        count = int(page_count)
    except (TypeError, ValueError):
        count = 0
    return max(MIN_WIDTH, len(str(max(count, 1))))


def pdf_stem(pdf_name_or_path: str | Path) -> str:
    """File name of a PDF without its extension."""
    return Path(str(pdf_name_or_path)).stem


def default_output_name(stem: str, page: int, page_count: int, pattern: str = DEFAULT_PATTERN) -> str:
    """Return the output file name for one page."""
    return pattern.format(stem=stem, page=int(page), width=page_width(page_count))


def output_name_for(pdf_name_or_path: str | Path, page: int, page_count: int) -> str:
    """Convenience wrapper: derive the stem from the PDF and build the name."""
    return default_output_name(pdf_stem(pdf_name_or_path), page, page_count)


def job_id_for(pdf_name_or_path: str | Path, page: int) -> str:
    """Stable identifier of one page job, e.g. "manual_p017"."""
    return f"{pdf_stem(pdf_name_or_path)}_p{int(page):03d}"


def new_run_id(when: datetime | None = None) -> str:
    """Unique id of one run, e.g. "20260923-173858-3bd373".

    It is written into the request and compared with the result, so a stale or
    foreign result file can never be mistaken for the answer to this run.
    """
    stamp = (when or datetime.now()).strftime(RUN_ID_FORMAT)
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def validate_output_name(name: str) -> list[str]:
    """Return a list of problems with an output file name (empty = valid)."""
    problems: list[str] = []
    if not name or not name.strip():
        problems.append("nosaukums ir tukšs")
        return problems
    if name != Path(name).name:
        problems.append(f"nosaukumā nedrīkst būt mapes: {name}")
    if _INVALID_NAME_CHARS.search(name):
        problems.append(f"nosaukumā ir nederīgas rakstzīmes: {name}")
    if not name.lower().endswith(DEFAULT_EXTENSION):
        problems.append(f"nosaukumam jābeidzas ar {DEFAULT_EXTENSION}: {name}")
    if Path(name).stem.upper() in _RESERVED_WINDOWS_NAMES:
        problems.append(f"rezervēts Windows nosaukums: {name}")
    return problems


def find_duplicate_outputs(pages: list[dict]) -> dict[str, list[int]]:
    """Map output name -> list of page numbers that would write the same file.

    Only enabled pages count; an empty mapping means the plan is collision free.
    """
    seen: dict[str, list[int]] = {}
    for page_cfg in pages:
        if not page_cfg.get("enabled", True):
            continue
        name = (page_cfg.get("output") or "").strip()
        if not name:
            continue
        seen.setdefault(name.lower(), []).append(int(page_cfg.get("page", 0)))
    return {name: nums for name, nums in seen.items() if len(nums) > 1}
