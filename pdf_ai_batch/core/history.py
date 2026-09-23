"""Plan history: atomic snapshots of `config.json` and undo / restore.

The plan of a JOB is production data: a 300 page mapping that took an hour to build
must survive a wrong bulk action. This module records **the plan before every
meaningful change** and can put an older plan back.

    JOB/CONFIG/history/
        2026-09-23_201503.json      before "template piešķire (6-35)"
        2026-09-23_202105.json      before "preset magazine_36_pages"
        ...

A snapshot holds only the PLAN (the exact `config.json` content) plus metadata
(version, timestamp, reason, kind, job, app version, document/page counts). It never
contains queue/runtime state - `state.json`, the outputs and the JOB folders are not
touched by any function here.

Atomicity, in both directions:

* a snapshot is written through `jsonio.write_json_atomic` (temp file + rename), so a
  crash can never leave a half written history file
* a restore snapshots the CURRENT plan first ("recovery snapshot") and then writes the
  restored config atomically, so restoring is itself reversible and a crash cannot
  corrupt `config.json`

Retention keeps the newest `DEFAULT_RETENTION` (100) snapshots; a snapshot marked
`pinned` in its metadata is never deleted (the hook for manually named snapshots).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config as cfg
from . import jsonio

HISTORY_DIR_NAME = "history"
SNAPSHOT_VERSION = 1
FILE_STAMP_FORMAT = "%Y-%m-%d_%H%M%S"
DEFAULT_RETENTION = 100
MAX_NAME_ATTEMPTS = 100

KIND_PLAN = "plan"
KIND_BULK = "bulk-assign"
KIND_PRESET = "preset"
KIND_AUTOMAP = "auto-map"
KIND_RECONCILE = "reconcile"
KIND_UNDO = "undo"
KIND_RESTORE = "restore"
KIND_MANUAL = "manual"


class HistoryError(RuntimeError):
    """Raised when a snapshot cannot be written, read or restored."""


@dataclass(frozen=True)
class SnapshotInfo:
    """One snapshot on disk (what `[RESTORE SNAPSHOT]` lists)."""

    path: Path
    created: str = ""
    reason: str = ""
    kind: str = KIND_PLAN
    documents: int = 0
    pages: int = 0
    pinned: bool = False
    version: int = SNAPSHOT_VERSION

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def stamp(self) -> str:
        """Timestamp of the file name (`2026-09-23_201503`)."""
        return self.path.stem

    def summary(self) -> str:
        text = f"{self.created or self.stamp} | {self.reason or self.kind}"
        text += f" | {self.documents} PDF, {self.pages} lapas"
        if self.pinned:
            text += " | pinned"
        return text


def history_dir(project) -> Path:
    """`JOB/CONFIG/history` (created on demand by `snapshot`)."""
    return Path(project.config_dir) / HISTORY_DIR_NAME


def snapshot_path(project, *, when: datetime | None = None) -> Path:
    """A free snapshot file name for this moment (never an existing file)."""
    folder = history_dir(project)
    stamp = (when or datetime.now()).strftime(FILE_STAMP_FORMAT)
    for attempt in range(1, MAX_NAME_ATTEMPTS + 1):
        name = f"{stamp}.json" if attempt == 1 else f"{stamp}-{attempt}.json"
        path = folder / name
        if not path.exists():
            return path
    raise HistoryError(f"Nevar atrast brīvu snapshot nosaukumu mapē {folder}")


def _document_stats(config: dict) -> tuple[int, int]:
    documents = cfg.document_entries(config)
    pages = sum(len(block.get("pages") or []) for block in documents)
    return len(documents), pages


def make_snapshot(
    config: dict,
    *,
    job: str,
    reason: str,
    kind: str = KIND_PLAN,
    app_version: str = "",
    created: str | None = None,
    pinned: bool = False,
) -> dict:
    """The snapshot payload (no file IO) - what `snapshot` writes."""
    documents, pages = _document_stats(config)
    return {
        "version": SNAPSHOT_VERSION,
        "created": created or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind,
        "reason": reason,
        "job": job,
        "app_version": app_version,
        "meta": {
            "documents": documents,
            "pages": pages,
            "pinned": bool(pinned),
            "config_version": config.get("version") if isinstance(config, dict) else None,
        },
        "config": config,
    }


def snapshot(
    project,
    config: dict | None = None,
    *,
    reason: str,
    kind: str = KIND_PLAN,
    app_version: str = "",
    when: datetime | None = None,
    keep: int = DEFAULT_RETENTION,
    pinned: bool = False,
) -> SnapshotInfo:
    """Write one atomic snapshot of `config` (default: the current config.json).

    Returns the snapshot; raises `HistoryError` when nothing can be written. Retention
    runs after a successful write and never touches pinned or newer snapshots.
    """
    payload_config = config
    if payload_config is None:
        payload_config = cfg.load_config(Path(project.config_path))
        if not payload_config:
            raise HistoryError("Nav ko saglabāt: config.json nav izlasāms")
    if not isinstance(payload_config, dict) or not payload_config:
        raise HistoryError("Nav ko saglabāt: tukšs plāns")

    document, _note = cfg.migrate_config(payload_config)
    payload = make_snapshot(
        document,
        job=Path(project.root).name,
        reason=str(reason or KIND_PLAN),
        kind=kind,
        app_version=app_version,
        created=datetime.now().strftime("%Y-%m-%d %H:%M:%S") if when is None else when.strftime("%Y-%m-%d %H:%M:%S"),
        pinned=pinned,
    )
    path = snapshot_path(project, when=when)
    try:
        jsonio.write_json_atomic(path, payload)
    except Exception as exc:  # noqa: BLE001 - a snapshot must never break the caller
        raise HistoryError(f"Snapshot netika uzrakstīts ({path.name}): {exc}") from exc

    prune(project, keep=keep)
    return info_of(path, payload)


# ---------------------------------------------------------------------- reading


def _info_from_payload(path: Path, payload: dict) -> SnapshotInfo:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return SnapshotInfo(
        path=Path(path),
        created=str(payload.get("created") or ""),
        reason=str(payload.get("reason") or ""),
        kind=str(payload.get("kind") or KIND_PLAN),
        documents=int(meta.get("documents", 0) or 0),
        pages=int(meta.get("pages", 0) or 0),
        pinned=bool(meta.get("pinned", False)),
        version=int(payload.get("version", 0) or 0),
    )


def info_of(path: str | Path, payload: dict | None = None) -> SnapshotInfo:
    """Snapshot metadata; reads the file when `payload` is not given."""
    target = Path(path)
    data = payload if isinstance(payload, dict) else jsonio.read_json(target, default={})
    return _info_from_payload(target, data if isinstance(data, dict) else {})


def load_snapshot(path: str | Path) -> dict:
    """Read + validate one snapshot (raises `HistoryError` when it is unusable)."""
    target = Path(path)
    data = jsonio.read_json(target, default={})
    if not isinstance(data, dict) or not data:
        raise HistoryError(f"Snapshot nav nolasāms: {target.name}")
    if data.get("version") != SNAPSHOT_VERSION:
        raise HistoryError(
            f"Snapshot versija nav {SNAPSHOT_VERSION}: {data.get('version')!r} ({target.name})"
        )
    config = data.get("config")
    if not isinstance(config, dict) or not config:
        raise HistoryError(f"Snapshot nesatur plānu: {target.name}")
    problems = cfg.validate_config(config)
    if problems:
        raise HistoryError(
            f"Snapshot plāns nav derīgs ({target.name}): " + "; ".join(problems[:3])
        )
    return data


def _snapshot_files(project) -> list[Path]:
    folder = history_dir(project)
    if not folder.is_dir():
        return []
    return [path for path in folder.glob("*.json") if path.is_file()]


def list_snapshots(project, *, limit: int | None = None) -> list[SnapshotInfo]:
    """Snapshots newest first.

    Ordered by modification time (a second snapshot within the same second gets a
    `-2` suffix and that one is newer), then by name for a stable order. An unreadable
    file is still listed (never silently skipped) - restoring it raises later.
    """
    infos = []
    for path in _snapshot_files(project):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        infos.append((mtime, path.name, info_of(path)))
    infos.sort(key=lambda row: (row[0], row[1]), reverse=True)
    ordered = [info for _mtime, _name, info in infos]
    return ordered[:limit] if limit else ordered


def count_snapshots(project) -> int:
    return len(_snapshot_files(project))


def latest_snapshot(project) -> SnapshotInfo | None:
    infos = list_snapshots(project, limit=1)
    return infos[0] if infos else None


def _same_plan(left: dict | None, right: dict | None) -> bool:
    """Do two configs describe the same plan? (order of keys does not matter)."""
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(
        right, sort_keys=True, ensure_ascii=False
    )


def undo_target(project, current: dict | None = None) -> SnapshotInfo | None:
    """The newest snapshot whose plan differs from the current plan (the undo step).

    Every mutation snapshots the plan it is about to replace, so this is normally the
    newest snapshot. After a restore the newest snapshot is the recovery copy of the
    state we came from, which makes an undo itself undoable (the two states toggle).
    """
    payload = current if isinstance(current, dict) else cfg.load_config(Path(project.config_path))
    for info in list_snapshots(project):
        try:
            data = load_snapshot(info.path)
        except HistoryError:
            continue
        if not _same_plan(data.get("config"), payload):
            return info
    return None


# --------------------------------------------------------------------- retention


def prune(project, *, keep: int = DEFAULT_RETENTION) -> list[Path]:
    """Delete the oldest snapshots beyond `keep` (pinned ones are never deleted)."""
    if keep is None or keep <= 0:
        return []
    infos = list_snapshots(project)
    kept: list[SnapshotInfo] = []
    removed: list[Path] = []
    for index, info in enumerate(infos):
        if info.pinned or index < keep:
            kept.append(info)
            continue
        try:
            info.path.unlink()
            removed.append(info.path)
        except OSError:
            kept.append(info)
    return removed


# ------------------------------------------------------------- restore and undo


@dataclass(frozen=True)
class RestoreResult:
    """What one restore/undo did (the recovery snapshot makes it reversible)."""

    restored: SnapshotInfo
    recovery: SnapshotInfo | None = None
    reason: str = ""
    kind: str = KIND_RESTORE
    documents: int = 0
    pages: int = 0

    def summary(self) -> str:
        text = (
            f"Atjaunots plāns no {self.restored.name} ({self.restored.reason}) | "
            f"{self.documents} PDF, {self.pages} lapas"
        )
        if self.recovery is not None:
            text += f" | atgriešanās kopija {self.recovery.name}"
        return text


def restore_snapshot(
    project,
    target: str | Path | SnapshotInfo,
    *,
    reason: str = "",
    kind: str = KIND_RESTORE,
    app_version: str = "",
    when: datetime | None = None,
    keep: int = DEFAULT_RETENTION,
    write_config=None,
) -> RestoreResult:
    """Put an older plan back, atomically and reversibly.

    1. the CURRENT plan is snapshotted first (the recovery copy), so this action can be
       undone with the same function
    2. the target plan is validated
    3. `config.json` is written atomically through `cfg.save_config`

    `write_config` is a seam for the caller (the GUI passes its own save + queue
    rebuild); by default the config is written here.
    """
    info = target if isinstance(target, SnapshotInfo) else info_of(target)
    data = load_snapshot(info.path)
    restored_config = data["config"]

    current = cfg.load_config(Path(project.config_path))
    recovery: SnapshotInfo | None = None
    if current:
        recovery = snapshot(
            project,
            current,
            reason=reason or f"pirms atjaunošanas ({info.reason})",
            kind=KIND_RESTORE,
            app_version=app_version,
            when=when,
            keep=keep,
        )

    save = write_config or (lambda config: cfg.save_config(project.config_path, config))
    save(restored_config)

    documents, pages = _document_stats(restored_config)
    return RestoreResult(
        restored=info,
        recovery=recovery,
        reason=reason,
        kind=kind,
        documents=documents,
        pages=pages,
    )


def undo_last(
    project,
    *,
    current: dict | None = None,
    app_version: str = "",
    when: datetime | None = None,
    keep: int = DEFAULT_RETENTION,
    write_config=None,
) -> RestoreResult | None:
    """Undo the last plan change: restore the newest snapshot that differs.

    Returns None when there is nothing to undo (no snapshot, or every snapshot already
    equals the current plan).
    """
    payload = current if isinstance(current, dict) else cfg.load_config(Path(project.config_path))
    target = undo_target(project, payload)
    if target is None:
        return None
    return restore_snapshot(
        project,
        target,
        reason=f"UNDO ({target.reason})",
        kind=KIND_UNDO,
        app_version=app_version,
        when=when,
        keep=keep,
        write_config=write_config,
    )


