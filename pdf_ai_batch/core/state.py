"""Persistent queue state: JOB/CONFIG/state.json.

One document per JOB folder, written through the shared atomic JSON writer
(`core/jsonio.write_json_atomic`), so a crash never leaves a half written file.

State model (one entry per page):

    WAITING      queued, will be picked up by CONTINUE / RUN ALL
    RUNNING      a worker run is in flight (written BEFORE Illustrator is asked)
    DONE         worker returned OK **and** the output AI exists
    ERROR        the run failed (worker ERROR, missing output, COM problem)
    SKIPPED      deliberately not processed (output already there, manual skip)
    INTERRUPTED  was RUNNING when the previous session ended

    WAITING ──run──▶ RUNNING ──OK + output──▶ DONE
                        │   │
                        │   ├──ERROR────────▶ ERROR ──retry_errors──▶ WAITING
                        │   └──SKIP─────────▶ SKIPPED ──reset_item──▶ WAITING
                        └──crash/restart────▶ INTERRUPTED ──retry_interrupted/continue──▶ WAITING

Rules
    * DONE is never set from "the worker said OK" alone: the output file must exist
      (the check lives in `pagejob.output_ready`, the queue applies it).
    * a stale RUNNING item is recovered as INTERRUPTED at startup - never DONE,
      never left RUNNING forever, and it stays retryable.
    * an attempt is counted when a run really starts (RUNNING), not on reset/skip.
    * `error_type` / `error_message` describe the CURRENT situation; the full
      history stays in LOG/app.log and LOG/batch_<timestamp>.log.

The paths in state.json are absolute and forward slashed, exactly like the
contract (`core/contract.contract_path`), so the state can be read from any
working directory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import jsonio
from .contract import LAYER_DEFAULT, TEMPLATE_MODE_COPY, build_request, is_absolute_path
from .naming import job_id_for

STATE_VERSION = 1
STATE_FILE_NAME = "state.json"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_MESSAGE_LENGTH = 1500

WAITING = "WAITING"
RUNNING = "RUNNING"
DONE = "DONE"
ERROR = "ERROR"
SKIPPED = "SKIPPED"
INTERRUPTED = "INTERRUPTED"

VALID_STATES = (WAITING, RUNNING, DONE, ERROR, SKIPPED, INTERRUPTED)
TERMINAL_STATES = (DONE, SKIPPED)
RUNNABLE_STATES = (WAITING, INTERRUPTED)
RETRY_ERROR_STATES = (ERROR,)
RETRY_INTERRUPTED_STATES = (INTERRUPTED,)

ITEM_FIELDS = (
    "job_id",
    "page",
    "state",
    "enabled",
    "pdf",
    "template",
    "output",
    "layer",
    "template_mode",
    "clear_layer",
    "overwrite",
    "last_run_id",
    "error_type",
    "error_message",
    "attempts",
    "created",
    "updated",
    "started",
    "finished",
)


def now_stamp(when: datetime | None = None) -> str:
    """Local timestamp in the format the log files use."""
    return (when or datetime.now()).strftime(TIMESTAMP_FORMAT)


def short_message(message: str, limit: int = MAX_MESSAGE_LENGTH) -> str:
    """Keep a failure reason readable but bounded (state.json stays small)."""
    text = " ".join(str(message or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


@dataclass(frozen=True)
class QueueItem:
    """One page of the queue, with everything needed to recover after a restart."""

    job_id: str
    page: int
    pdf: str
    template: str
    output: str
    layer: str = LAYER_DEFAULT
    template_mode: str = TEMPLATE_MODE_COPY
    clear_layer: bool = True
    overwrite: bool = False
    enabled: bool = True
    state: str = WAITING
    last_run_id: str = ""
    error_type: str = ""
    error_message: str = ""
    attempts: int = 0
    created: str = ""
    updated: str = ""
    started: str = ""
    finished: str = ""

    # ------------------------------------------------------------------ helpers

    @property
    def pdf_name(self) -> str:
        return Path(self.pdf).name

    @property
    def runnable(self) -> bool:
        """True when CONTINUE / RUN ALL would pick this item up."""
        return bool(self.enabled) and self.state in RUNNABLE_STATES

    @property
    def finished_state(self) -> bool:
        return self.state in TERMINAL_STATES

    def request(self, run_id: str) -> dict:
        """The contract request for this item (absolute paths, forward slashes)."""
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
            template_mode=self.template_mode,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialisation order is the ITEM_FIELDS order (stable diffs)."""
        return {name: getattr(self, name) for name in ITEM_FIELDS}

    @classmethod
    def from_dict(cls, data: dict) -> tuple["QueueItem", list[str]]:
        """Build an item from JSON; never raises, returns (item, problems)."""
        problems: list[str] = []
        if not isinstance(data, dict):
            return cls(job_id="", page=0, pdf="", template="", output=""), ["elements nav objekts"]

        job_id = str(data.get("job_id") or "")
        try:
            page = int(data.get("page") or 0)
        except (TypeError, ValueError):
            page = 0
            problems.append(f"{job_id or '?'}: page nav skaitlis")

        state_value = str(data.get("state") or WAITING).upper()
        if state_value not in VALID_STATES:
            problems.append(f"{job_id or '?'}: nezināms stāvoklis {state_value!r} -> {WAITING}")
            state_value = WAITING

        try:
            attempts = max(0, int(data.get("attempts") or 0))
        except (TypeError, ValueError):
            attempts = 0
            problems.append(f"{job_id or '?'}: attempts nav skaitlis")

        item = cls(
            job_id=job_id,
            page=page,
            pdf=str(data.get("pdf") or ""),
            template=str(data.get("template") or ""),
            output=str(data.get("output") or ""),
            layer=str(data.get("layer") or LAYER_DEFAULT),
            template_mode=str(data.get("template_mode") or TEMPLATE_MODE_COPY),
            clear_layer=bool(data.get("clear_layer", True)),
            overwrite=bool(data.get("overwrite", False)),
            enabled=bool(data.get("enabled", True)),
            state=state_value,
            last_run_id=str(data.get("last_run_id") or ""),
            error_type=str(data.get("error_type") or ""),
            error_message=str(data.get("error_message") or ""),
            attempts=attempts,
            created=str(data.get("created") or ""),
            updated=str(data.get("updated") or ""),
            started=str(data.get("started") or ""),
            finished=str(data.get("finished") or ""),
        )

        if not item.job_id:
            problems.append("elements bez job_id")
        if item.page < 1:
            problems.append(f"{item.job_id or '?'}: page < 1")
        for name in ("pdf", "template", "output"):
            value = getattr(item, name)
            if not value:
                problems.append(f"{item.job_id or '?'}: trūkst {name}")
            elif not is_absolute_path(value):
                problems.append(f"{item.job_id or '?'}: {name} nav absolūts ceļš")
        return item, problems


@dataclass
class StateDocument:
    """The complete state.json of one JOB folder."""

    version: int = STATE_VERSION
    session_id: str = ""
    job_root: str = ""
    created: str = ""
    updated: str = ""
    items: list[QueueItem] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ lookup

    def index_of(self, job_id: str) -> int:
        for index, item in enumerate(self.items):
            if item.job_id == job_id:
                return index
        return -1

    def find(self, item_id: str | int) -> QueueItem | None:
        """Find one item by job_id, page number or output file name."""
        if item_id is None:
            return None
        if isinstance(item_id, int):
            text = str(item_id)
        else:
            text = str(item_id).strip()

        for item in self.items:
            if item.job_id == text:
                return item
        lowered = text.lower()
        for item in self.items:
            if item.job_id.lower() == lowered:
                return item
        for item in self.items:
            if Path(item.output).name.lower() == lowered:
                return item
        if text.isdigit():
            page = int(text)
            for item in self.items:
                if item.page == page:
                    return item
        return None

    def replace_item(self, item: QueueItem) -> None:
        """Store an item in place (keeps the queue order stable)."""
        index = self.index_of(item.job_id)
        if index < 0:
            self.items.append(item)
            return
        self.items[index] = item

    # ----------------------------------------------------------------- content

    def with_state(self, *states: str) -> list[QueueItem]:
        wanted = set(states)
        return [item for item in self.items if item.state in wanted]

    def runnable(self) -> list[QueueItem]:
        return [item for item in self.items if item.runnable]

    def counts(self) -> dict[str, int]:
        return summary(self)

    def to_dict(self) -> dict[str, Any]:
        """The serialised document. Load problems are diagnostics, not state."""
        return {
            "version": STATE_VERSION,
            "session_id": self.session_id,
            "job_root": self.job_root,
            "created": self.created,
            "updated": self.updated,
            "items": [item.to_dict() for item in self.items],
        }


def validate_document(document: StateDocument) -> list[str]:
    """Structural problems that matter for a run (empty = fine)."""
    problems: list[str] = []
    seen: set[str] = set()
    for item in document.items:
        if item.job_id in seen:
            problems.append(f"dublēts job_id: {item.job_id}")
        seen.add(item.job_id)
        if item.state not in VALID_STATES:
            problems.append(f"{item.job_id}: nezināms stāvoklis {item.state!r}")
    return problems


def load_state(
    path: str | Path,
    *,
    job_root: str | Path | None = None,
    session_id: str = "",
) -> StateDocument:
    """Read state.json. NEVER raises; a broken file becomes `problems`.

    The caller decides what to do with the problems (the queue quarantines the
    file and rebuilds), so a corrupt state can never crash a batch.
    """
    file_path = Path(path)
    document = StateDocument(
        job_root=str(job_root or ""),
        session_id=str(session_id or ""),
        created=now_stamp(),
    )

    if not file_path.is_file():
        return document

    text = jsonio.read_text(file_path)
    if not text.strip():
        return document

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        document.problems.append(f"state.json nav nolasāms (JSON kļūda): {exc}")
        return document

    if not isinstance(data, dict):
        document.problems.append("state.json nav objekts")
        return document

    version = data.get("version")
    if version != STATE_VERSION:
        document.problems.append(
            f"state.json versija {version!r} nav {STATE_VERSION}; lasu, ko varu"
        )

    document.session_id = str(data.get("session_id") or session_id or "")
    document.job_root = str(data.get("job_root") or job_root or "")
    document.created = str(data.get("created") or document.created)
    document.updated = str(data.get("updated") or "")

    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        document.problems.append("state.json items nav saraksts")
        return document

    seen: set[str] = set()
    for index, raw in enumerate(raw_items):
        item, problems = QueueItem.from_dict(raw)
        document.problems.extend(problems)
        if item.job_id and item.job_id in seen:
            document.problems.append(
                f"dublēts job_id {item.job_id} (elements {index}) - paturu pirmo"
            )
            continue
        seen.add(item.job_id)
        document.items.append(item)

    return document


def save_state(path: str | Path, document: StateDocument) -> Path:
    """Write state.json atomically (temp file + rename, UTF-8, LF)."""
    document.version = STATE_VERSION
    document.updated = now_stamp()
    if not document.created:
        document.created = document.updated
    return jsonio.write_json_atomic(path, document.to_dict())


# --------------------------------------------------------------------- transitions


def mark_running(item: QueueItem, run_id: str, *, at: datetime | None = None) -> QueueItem:
    """Start a real run. The attempt counter is incremented HERE and nowhere else."""
    stamp = now_stamp(at)
    return replace(
        item,
        state=RUNNING,
        last_run_id=run_id,
        attempts=item.attempts + 1,
        error_type="",
        error_message="",
        started=stamp,
        finished="",
        updated=stamp,
    )


def mark_done(item: QueueItem, run_id: str, *, at: datetime | None = None) -> QueueItem:
    """OK result AND the output file verified - the only way into DONE."""
    stamp = now_stamp(at)
    return replace(
        item,
        state=DONE,
        last_run_id=run_id,
        error_type="",
        error_message="",
        finished=stamp,
        updated=stamp,
    )


def mark_error(
    item: QueueItem,
    run_id: str,
    error_type: str,
    message: str = "",
    *,
    at: datetime | None = None,
) -> QueueItem:
    """A failed run (worker ERROR, missing output, COM problem)."""
    stamp = now_stamp(at)
    return replace(
        item,
        state=ERROR,
        last_run_id=run_id or item.last_run_id,
        error_type=str(error_type or "ERROR"),
        error_message=short_message(message),
        finished=stamp,
        updated=stamp,
    )


def mark_skipped(item: QueueItem, message: str = "", *, at: datetime | None = None) -> QueueItem:
    """Deliberately not processed (output already there, manual skip)."""
    stamp = now_stamp(at)
    return replace(
        item,
        state=SKIPPED,
        error_type="",
        error_message=short_message(message),
        finished=stamp,
        updated=stamp,
    )


def mark_interrupted(item: QueueItem, message: str = "", *, at: datetime | None = None) -> QueueItem:
    """A RUNNING item whose session ended (startup recovery)."""
    stamp = now_stamp(at)
    return replace(
        item,
        state=INTERRUPTED,
        error_type=item.error_type or "INTERRUPTED",
        error_message=short_message(message),
        finished=stamp,
        updated=stamp,
    )


def mark_waiting(item: QueueItem, *, at: datetime | None = None) -> QueueItem:
    """Back to the queue (retry / reset). Attempts are kept, attempt history stays."""
    stamp = now_stamp(at)
    return replace(
        item,
        state=WAITING,
        error_type="",
        error_message="",
        started="",
        finished="",
        updated=stamp,
    )


def recover_running(
    document: StateDocument,
    *,
    note: str = "Iepriekšējā sesija pārtrūka (RUNNING -> INTERRUPTED)",
    at: datetime | None = None,
) -> list[str]:
    """A stale RUNNING item becomes INTERRUPTED: never DONE, never stuck RUNNING."""
    recovered: list[str] = []
    for index, item in enumerate(document.items):
        if item.state != RUNNING:
            continue
        document.items[index] = mark_interrupted(item, note, at=at)
        recovered.append(item.job_id)
    return recovered


def summary(document: StateDocument) -> dict[str, int]:
    """Counts per state plus total/enabled/runnable (used by the CLI and the GUI)."""
    counts: dict[str, int] = {name: 0 for name in VALID_STATES}
    for item in document.items:
        counts[item.state] = counts.get(item.state, 0) + 1
    return {
        "total": len(document.items),
        "enabled": sum(1 for item in document.items if item.enabled),
        "runnable": sum(1 for item in document.items if item.runnable),
        **counts,
    }


def new_item(
    *,
    job_id: str,
    page: int,
    pdf: str,
    template: str,
    output: str,
    layer: str = LAYER_DEFAULT,
    template_mode: str = TEMPLATE_MODE_COPY,
    clear_layer: bool = True,
    overwrite: bool = False,
    enabled: bool = True,
    state_value: str = WAITING,
    at: datetime | None = None,
) -> QueueItem:
    """A fresh WAITING item with the timestamps filled in."""
    stamp = now_stamp(at)
    return QueueItem(
        job_id=job_id,
        page=int(page),
        pdf=str(pdf),
        template=str(template),
        output=str(output),
        layer=layer or LAYER_DEFAULT,
        template_mode=template_mode,
        clear_layer=bool(clear_layer),
        overwrite=bool(overwrite),
        enabled=bool(enabled),
        state=state_value,
        created=stamp,
        updated=stamp,
    )


def job_id_for_page(pdf: str | Path, page: int) -> str:
    """`mans_fails.pdf` + 3 -> `mans_fails_p003` (the job_id used in state.json)."""
    return job_id_for(pdf, page)


def states_of(items: Iterable[QueueItem]) -> list[str]:
    """Ordered state names of a list of items (reporting helper)."""
    return [item.state for item in items]

