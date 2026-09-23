"""Disposable thumbnail/preview cache: JOB/.cache/preview.

Every entry is a PNG whose NAME carries the complete identity of what it shows:

    <kind>_<pdf stem>_p<page>_<fingerprint>_<request>.png

    fingerprint = sha1(pdf absolute path + mtime + size)   -> PDF identity
    request     = sha1(page + kind + requested size/zoom)  -> render request

so a modified PDF, a changed page or a different render size can never hit an old
file (milestone 5: "If PDF changes: old thumbnails must not be reused"), and
invalidating everything of a replaced PDF is a simple prefix + fingerprint compare.

The folder can be deleted by hand at any time; nothing else in the JOB depends on
it, and it never becomes part of `state.json` / `config.json`. It is bounded by
bytes and by file count (LRU by access time) and stays out of git (`.cache/`).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

CACHE_ROOT_NAME = ".cache"
CACHE_DIR_NAME = "preview"
CACHE_GITIGNORE = "*\n"
DEFAULT_MAX_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_FILES = 4000
SUFFIX = ".png"

KIND_THUMBNAIL = "thumb"
KIND_PREVIEW = "large"

_SAFE = re.compile(r"[^0-9A-Za-z_-]+")


def safe_name(value: str, limit: int = 40) -> str:
    """ASCII-only, filesystem safe fragment of a name (Latvian names included)."""
    text = _SAFE.sub("_", str(value)).strip("_")
    return (text or "file")[:limit]


def fingerprint_digest(fingerprint: tuple[str, float, int]) -> str:
    """Stable 12 hex chars for "this exact PDF file state" (path + mtime + size)."""
    path, mtime, size = fingerprint
    payload = f"{path}|{float(mtime):.6f}|{int(size)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class CacheKey:
    """Identity of one cached render (PDF identity + render request)."""

    fingerprint: tuple[str, float, int]
    page: int
    kind: str = KIND_THUMBNAIL
    width: int = 0
    long_side: int = 0
    zoom: float = 0.0

    def __post_init__(self) -> None:
        if int(self.page) < 1:
            raise ValueError("cache key page must be >= 1")

    @property
    def pdf(self) -> str:
        return str(self.fingerprint[0])

    @property
    def document_name(self) -> str:
        return Path(self.fingerprint[0]).name

    @property
    def stem(self) -> str:
        return safe_name(Path(self.fingerprint[0]).stem)

    @property
    def fingerprint_digest(self) -> str:
        return fingerprint_digest(self.fingerprint)

    @property
    def request_digest(self) -> str:
        payload = "|".join(
            (
                self.kind,
                str(int(self.page)),
                str(int(self.width)),
                str(int(self.long_side)),
                f"{float(self.zoom):.4f}",
            )
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]

    def file_name(self) -> str:
        return (
            f"{self.kind}_{self.stem}_p{int(self.page):04d}"
            f"_{self.fingerprint_digest}_{self.request_digest}{SUFFIX}"
        )

    @classmethod
    def for_thumbnail(cls, fingerprint: tuple[str, float, int], page: int, width: int) -> "CacheKey":
        return cls(fingerprint=fingerprint, page=int(page), kind=KIND_THUMBNAIL, width=int(width))

    @classmethod
    def for_preview(
        cls,
        fingerprint: tuple[str, float, int],
        page: int,
        *,
        long_side: int = 0,
        zoom: float = 0.0,
    ) -> "CacheKey":
        return cls(
            fingerprint=fingerprint,
            page=int(page),
            kind=KIND_PREVIEW,
            long_side=int(long_side),
            zoom=float(zoom),
        )



class PreviewCache:
    """Disk cache for rendered pages. Safe to delete entirely at any time."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
        enabled: bool = True,
    ) -> None:
        self.root = Path(root)
        self.max_bytes = int(max_bytes)
        self.max_files = int(max_files)
        self.enabled = bool(enabled)

    # -------------------------------------------------------------------- paths

    @property
    def directory(self) -> Path:
        """`<JOB>/.cache/preview` (created on demand, never committed)."""
        if self.root.name == CACHE_DIR_NAME and self.root.parent.name == CACHE_ROOT_NAME:
            return self.root
        return self.root / CACHE_ROOT_NAME / CACHE_DIR_NAME

    def _ensure_dir(self) -> Path | None:
        if not self.enabled:
            return None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            marker = self.directory / ".gitignore"
            if not marker.exists():
                marker.write_text(CACHE_GITIGNORE, encoding="ascii")
        except OSError:
            return None
        return self.directory

    def path_for(self, key: CacheKey) -> Path:
        return self.directory / key.file_name()

    # ---------------------------------------------------------------- read/write

    def get(self, key: CacheKey) -> bytes | None:
        """Cached PNG bytes, or None (a missing/empty file counts as a miss)."""
        if not self.enabled:
            return None
        path = self.path_for(key)
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if not data:
            return None
        try:  # LRU by access time (best effort; failures are never fatal)
            os.utime(path, None)
        except OSError:
            pass
        return data

    def put(self, key: CacheKey, data: bytes) -> Path | None:
        """Store PNG bytes atomically (temp file + replace); None when disabled."""
        directory = self._ensure_dir()
        if directory is None or not data:
            return None
        path = directory / key.file_name()
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        self.prune()
        return path

    # ------------------------------------------------------------------- upkeep

    def entries(self) -> list[Path]:
        """Cached files, oldest access first."""
        try:
            return sorted(
                (path for path in self.directory.glob(f"*{SUFFIX}") if path.is_file()),
                key=lambda item: item.stat().st_mtime,
            )
        except OSError:
            return []

    def stats(self) -> dict:
        files = self.entries()
        total = 0
        for path in files:
            try:
                total += path.stat().st_size
            except OSError:
                continue
        return {
            "directory": str(self.directory),
            "files": len(files),
            "bytes": total,
            "enabled": self.enabled,
        }

    def clear(self) -> int:
        """Delete every cached render (the folder is disposable)."""
        removed = 0
        for path in self.entries():
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def invalidate_pdf(self, pdf: str | Path, *, keep: tuple[str, float, int] | None = None) -> int:
        """Drop the renders of one PDF, sparing `keep` (its CURRENT fingerprint).

        Used when a PDF changed (page count drift, replaced file): old thumbnails of
        that document are removed, so a stale preview can never be shown again.
        """
        stem = safe_name(Path(str(pdf)).stem)
        prefixes = (f"{KIND_THUMBNAIL}_{stem}_", f"{KIND_PREVIEW}_{stem}_")
        keep_digest = fingerprint_digest(keep) if keep is not None else None
        removed = 0
        for path in self.entries():
            if not path.name.startswith(prefixes):
                continue
            if keep_digest is not None and keep_digest in path.name:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def prune(self) -> int:
        """Keep the cache inside its byte and file bounds (oldest first)."""
        removed = 0
        sizes: list[tuple[Path, int]] = []
        total = 0
        for path in self.entries():
            try:
                size = path.stat().st_size
            except OSError:
                continue
            sizes.append((path, size))
            total += size
        limit = self.max_files if self.max_files > 0 else len(sizes)
        while sizes and (total > self.max_bytes or len(sizes) > limit):
            path, size = sizes.pop(0)
            try:
                path.unlink()
            except OSError:
                continue
            total -= size
            removed += 1
        return removed
