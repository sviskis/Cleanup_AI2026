"""Bulk page mapping: ranges, bulk assignment, numbered auto map, copy/paste, presets.

Everything the MAPPING tab can do in bulk is decided HERE, in core. The GUI only
collects the operator's input (a range text, a template name, a checkbox) and calls
the controller, which calls these functions through one mutation funnel
(`AppController._mutate_config`) that validates and saves `config.json` atomically.

A mapping is **plan data only**: `template`, `layer` and - per document - the
`clear_layer` default of `defaults`. Queue/runtime fields (`state`, `attempts`,
`run_id`, `error_type`, `error_message`), the output file names and the execution
status NEVER travel through a clipboard or a preset (see `validate_preset`, which
rejects them explicitly).

Public API

    parse_pages / format_pages          range text <-> page list
    assign_template / set_layer / ...   one document, a list of pages
    auto_map_by_number                  deterministic numbered templates (never fuzzy)
    copy_mapping / paste_mapping        plan clipboard, even across documents
    preset_from_mapping / save_preset / load_preset / preset_preview / apply_preset
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from . import jsonio
from .contract import LAYER_DEFAULT
from .template_mapper import is_master_template, is_template_file

#: presets are versioned separately from config.json (mapping intent, no runtime)
PRESET_VERSION = 1
#: a range may never expand beyond this many pages (typo guard for "1-999999999")
MAX_PAGES_PER_RANGE = 20_000
PRESET_DIR_NAME = "presets"
ALL_TOKENS = ("*", "all", "visas")

#: keys a preset entry may carry - and nothing else
PRESET_ENTRY_KEYS = ("pages", "template", "layer", "enabled")
#: keys a preset file may carry
PRESET_KEYS = ("version", "name", "created", "source", "entries")
#: keys a preset must never contain (runtime / execution data)
FORBIDDEN_KEYS = (
    "state",
    "status",
    "attempts",
    "run_id",
    "last_run_id",
    "error_type",
    "error_message",
    "output",
    "outputs",
    "job_id",
    "pdf",
    "pdf_id",
    "started_at",
    "finished_at",
    "duration",
    "objects_copied",
    "stats",
    "queue",
    "items",
)
SOURCE_KEYS = ("pdf", "page_count")


class MappingError(RuntimeError):
    """Raised when a mapping operation cannot be performed as asked."""


class RangeParseError(MappingError):
    """Raised for malformed or out of range page selection text."""


class PresetError(MappingError):
    """Raised when a preset is invalid or cannot be applied."""


# --------------------------------------------------------------------------- ranges


def _normalize_text(text: str) -> str:
    return str(text or "").replace("\u2013", "-").replace("\u2014", "-").strip()


def _positive_int(token: str, chunk: str) -> int:
    if not token.isdigit():
        raise RangeParseError(f"Nederīgs lapas numurs: {chunk!r}")
    value = int(token)
    if value < 1:
        raise RangeParseError(f"Lapas numurs sākas no 1: {chunk!r}")
    return value


def parse_pages(
    text: str,
    *,
    page_count: int | None = None,
    normalize_reversed: bool = True,
) -> list[int]:
    """Parse a page selection: ``1``, ``1-5``, ``1,3,5``, ``1-5,8,10-14``.

    Accepted as "all pages": ``*`` / ``all`` / ``visas`` (needs `page_count`).
    The result is ascending and unique. Rejected with `RangeParseError`: an empty
    selection, ``0``, negatives, decimals, a missing range side (``1-``), unknown
    characters, pages beyond `page_count` and - unless `normalize_reversed` is set -
    a reversed range like ``5-3``.
    """
    raw = _normalize_text(text)
    if not raw:
        raise RangeParseError("Lapas nav norādītas (piemērs: 1-5,8,10-14)")

    if raw.lower() in ALL_TOKENS:
        if not page_count or int(page_count) < 1:
            raise RangeParseError("'*' nozīmē visas lapas, bet lappušu skaits nav zināms")
        return list(range(1, int(page_count) + 1))

    pages: list[int] = []
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            raise RangeParseError(f"Tukšs fragments lapu sarakstā: {text!r}")
        if "-" in token:
            head, _, tail = token.partition("-")
            head, tail = head.strip(), tail.strip()
            if not head or not tail:
                raise RangeParseError(f"Nepilnīgs lapu diapazons: {token!r} (piemērs: 6-35)")
            start = _positive_int(head, token)
            end = _positive_int(tail, token)
            if start > end:
                if not normalize_reversed:
                    raise RangeParseError(
                        f"Apgriezts lapu diapazons: {token!r} (raksti {end}-{start})"
                    )
                start, end = end, start
            if end - start + 1 > MAX_PAGES_PER_RANGE:
                raise RangeParseError(f"Diapazons ir pārāk liels: {token!r}")
            pages.extend(range(start, end + 1))
        else:
            pages.append(_positive_int(token, token))

    unique = sorted(set(pages))
    if page_count is not None:
        beyond = [page for page in unique if page > int(page_count)]
        if beyond:
            raise RangeParseError(
                f"Lapas ārpus dokumenta (1-{int(page_count)}): "
                + ", ".join(str(page) for page in beyond[:8])
            )
    return unique


def format_pages(pages: Iterable[int]) -> str:
    """Compress a page list back into range text: ``1-5,8,10-14``."""
    numbers = sorted({int(page) for page in pages})
    if not numbers:
        return ""
    parts: list[str] = []
    start = previous = numbers[0]
    for page in numbers[1:]:
        if page == previous + 1:
            previous = page
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(parts)


def page_count_of(block: dict) -> int:
    """Stored page count of a document block."""
    value = (block or {}).get("page_count")
    return int(value) if isinstance(value, int) and value > 0 else 0


# ------------------------------------------------------------------------- documents


def document_block(config: dict, pdf: str | Path) -> dict:
    """The document block of one PDF, or `MappingError` when it is not planned."""
    from .config import document_for

    block = document_for(config, pdf)
    if block is None:
        raise MappingError(f"Dokuments nav plānā: {Path(str(pdf)).name}")
    return block


def entries_by_page(config: dict, pdf: str | Path) -> dict[int, dict]:
    """{page: entry} of one document (the entries are the live config objects)."""
    pages = document_block(config, pdf).get("pages")
    result: dict[int, dict] = {}
    for entry in pages if isinstance(pages, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("page"), int):
            result[int(entry["page"])] = entry
    return result


def known_pages(config: dict, pdf: str | Path) -> list[int]:
    """Ascending page numbers of one document as they exist in the plan."""
    return sorted(entries_by_page(config, pdf))


def _wanted_pages(config: dict, pdf: str | Path, pages: Iterable[int]) -> list[int]:
    """Validate a page list against one document (strict, never silent)."""
    if isinstance(pages, (str, bytes)):
        raise MappingError("Lapas jānodod kā sarakstu (izmanto parse_pages)")
    wanted = sorted({int(page) for page in pages})
    if not wanted:
        raise MappingError("Nav atlasīta neviena lapa")
    available = set(known_pages(config, pdf))
    if not available:
        raise MappingError(f"Dokumentam nav nevienas lapas plānā: {Path(str(pdf)).name}")
    unknown = [page for page in wanted if page not in available]
    if unknown:
        raise MappingError(
            f"Lapas nav plānā ({min(available)}-{max(available)}): "
            + ", ".join(str(page) for page in unknown[:8])
        )
    return wanted


def assign_template(
    config: dict,
    pdf: str | Path,
    pages: Iterable[int],
    template: str | None,
    *,
    layer: str | None = None,
) -> dict:
    """Set the template (and optionally the layer) of the given pages.

    `template=None` means "inherit `defaults.template`". Only plan fields change;
    queue state is untouched (the caller rebuilds the queue afterwards).
    """
    value = (template or "").strip() or None
    if value and not is_template_file(value):
        raise MappingError(f"Template jābūt .ai vai .ait failam: {value!r}")
    wanted = _wanted_pages(config, pdf, pages)
    entries = entries_by_page(config, pdf)
    layer_value = (layer or "").strip() or None

    changed: list[int] = []
    for page in wanted:
        entry = entries[page]
        before = (entry.get("template"), entry.get("layer"))
        entry["template"] = value
        if layer_value:
            entry["layer"] = layer_value
        if (entry.get("template"), entry.get("layer")) != before:
            changed.append(page)
    return {
        "pdf": Path(str(pdf)).name,
        "pages": wanted,
        "changed": changed,
        "template": value,
        "layer": layer_value,
    }


def use_default_template(config: dict, pdf: str | Path, pages: Iterable[int]) -> dict:
    """Back to the document default (`template: null`)."""
    return assign_template(config, pdf, pages, None)


def clear_override(config: dict, pdf: str | Path, pages: Iterable[int]) -> dict:
    """Drop both the page template and any page specific layer (back to defaults)."""
    wanted = _wanted_pages(config, pdf, pages)
    entries = entries_by_page(config, pdf)
    default_layer = str((config.get("defaults") or {}).get("layer") or LAYER_DEFAULT)
    changed: list[int] = []
    for page in wanted:
        entry = entries[page]
        before = (entry.get("template"), entry.get("layer"))
        entry["template"] = None
        entry["layer"] = default_layer
        if (entry.get("template"), entry.get("layer")) != before:
            changed.append(page)
    return {
        "pdf": Path(str(pdf)).name,
        "pages": wanted,
        "changed": changed,
        "template": None,
        "layer": default_layer,
    }


def set_layer(config: dict, pdf: str | Path, pages: Iterable[int], layer: str) -> dict:
    """Change the target layer of the given pages (template stays as it is)."""
    value = (layer or "").strip()
    if not value:
        raise MappingError("Slāņa nosaukums ir tukšs")
    wanted = _wanted_pages(config, pdf, pages)
    entries = entries_by_page(config, pdf)
    changed = []
    for page in wanted:
        entry = entries[page]
        if entry.get("layer") != value:
            entry["layer"] = value
            changed.append(page)
    return {"pdf": Path(str(pdf)).name, "pages": wanted, "changed": changed, "layer": value}


def set_enabled(config: dict, pdf: str | Path, pages: Iterable[int], enabled: bool) -> dict:
    """USE column: the operator's switch for single pages (plan data)."""
    wanted = _wanted_pages(config, pdf, pages)
    entries = entries_by_page(config, pdf)
    value = bool(enabled)
    changed = []
    for page in wanted:
        entry = entries[page]
        if bool(entry.get("enabled", True)) != value:
            entry["enabled"] = value
            changed.append(page)
    return {"pdf": Path(str(pdf)).name, "pages": wanted, "changed": changed, "enabled": value}


# ------------------------------------------------------------- numbered auto mapping


_TEMPLATE_NUMBER = re.compile(r"^[^0-9]*(\d+)")


def template_number(name_or_path: str | Path) -> int | None:
    """Leading number of a template name: ``001_cover.ai`` -> 1, ``MASTER.ai`` -> None."""
    match = _TEMPLATE_NUMBER.match(Path(str(name_or_path)).stem)
    return int(match.group(1)) if match else None


def numbered_template_pool(template_dir: str | Path) -> tuple[dict[int, str], dict[int, list[str]], list[str]]:
    """Numbered templates of a folder: (by number, ambiguous, unnumbered).

    MASTER templates are excluded: they are the default template and must never be
    handed out by a numbered auto mapping. A number that appears twice is reported
    as ambiguous and is NOT assigned - never guessed.
    """
    from .pdf_info import sorted_naturally

    files = sorted_naturally([path for path in Path(template_dir).iterdir() if path.is_file()]) \
        if Path(template_dir).is_dir() else []
    by_number: dict[int, str] = {}
    ambiguous: dict[int, list[str]] = {}
    unnumbered: list[str] = []
    for path in files:
        if not is_template_file(path) or is_master_template(path):
            continue
        number = template_number(path.name)
        if number is None:
            unnumbered.append(path.name)
            continue
        if number in by_number:
            ambiguous.setdefault(number, [by_number[number]]).append(path.name)
            continue
        by_number[number] = path.name
    for number in ambiguous:
        by_number.pop(number, None)
    return by_number, ambiguous, unnumbered


def auto_map_by_number(
    config: dict,
    pdf: str | Path,
    *,
    page_count: int,
    template_dir: str | Path | None = None,
    pool: dict[int, str] | None = None,
) -> dict:
    """Deterministic numbered mapping: page N -> template whose name starts with N.

    Pages without a numbered template keep their current mapping (this never touches
    them). Masters are excluded, an ambiguous number is a reported problem instead of
    a guess, and there is no fuzzy/AI matching anywhere in this path.
    """
    if template_dir is None:
        raise MappingError("Nav norādīta TEMPLATE mape")
    if pool is None:
        by_number, ambiguous, unnumbered = numbered_template_pool(template_dir)
    else:
        by_number = {int(number): str(name) for number, name in pool.items()}
        ambiguous, unnumbered = {}, []

    total = int(page_count)
    if total < 1:
        raise MappingError("Lappušu skaits nav zināms (aizpildi plānu vispirms)")

    entries = entries_by_page(config, pdf)
    assigned: dict[int, str] = {}
    for page in range(1, total + 1):
        name = by_number.get(page)
        if not name or page not in entries:
            continue
        entries[page]["template"] = name
        assigned[page] = name

    unmatched = [page for page in range(1, total + 1) if page not in assigned]
    out_of_range = {
        number: name for number, name in sorted(by_number.items()) if number > total
    }
    problems = [
        f"Numurs {number} ir vairākiem template: {', '.join(names)}"
        for number, names in sorted(ambiguous.items())
    ]
    return {
        "pdf": Path(str(pdf)).name,
        "page_count": total,
        "assigned": assigned,
        "assigned_count": len(assigned),
        "unmatched": unmatched,
        "ambiguous": ambiguous,
        "unnumbered": unnumbered,
        "out_of_range": out_of_range,
        "pool": by_number,
        "problems": problems,
    }


# ----------------------------------------------------------------------- clipboard


@dataclass(frozen=True)
class ClipboardEntry:
    """One copied page: plan data only (template + layer, enabled when asked)."""

    page: int
    template: str | None
    layer: str
    enabled: bool = True

    def as_dict(self) -> dict:
        return {
            "page": self.page,
            "template": self.template,
            "layer": self.layer,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class MappingClipboard:
    """What COPY MAPPING put on the clipboard (never queue state, never outputs)."""

    source_pdf: str
    entries: tuple[ClipboardEntry, ...]
    clear_layer: bool = True
    include_enabled: bool = False

    @property
    def pages(self) -> list[int]:
        return [entry.page for entry in self.entries]

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def templates(self) -> list[str]:
        seen: list[str] = []
        for entry in self.entries:
            name = entry.template or ""
            if name not in seen:
                seen.append(name)
        return seen

    def summary(self) -> str:
        return (
            f"{self.count} lapas no {self.source_pdf} ({format_pages(self.pages)}) | "
            + ", ".join(name or "(noklusētais)" for name in self.templates)
        )


def copy_mapping(
    config: dict,
    pdf: str | Path,
    pages: Iterable[int],
    *,
    include_enabled: bool = False,
) -> MappingClipboard:
    """Copy the mapping of the given pages (template + layer, enabled on request)."""
    wanted = _wanted_pages(config, pdf, pages)
    entries = entries_by_page(config, pdf)
    defaults = config.get("defaults") or {}
    return MappingClipboard(
        source_pdf=Path(str(pdf)).name,
        entries=tuple(
            ClipboardEntry(
                page=page,
                template=entries[page].get("template"),
                layer=str(entries[page].get("layer") or LAYER_DEFAULT),
                enabled=bool(entries[page].get("enabled", True)),
            )
            for page in wanted
        ),
        clear_layer=bool(defaults.get("clear_layer", True)),
        include_enabled=bool(include_enabled),
    )


def paste_mapping(
    config: dict,
    pdf: str | Path,
    clipboard: MappingClipboard,
    *,
    pages: Iterable[int] | None = None,
    offset: int = 0,
    include_enabled: bool = False,
    include_document_defaults: bool = False,
) -> dict:
    """Paste a clipboard onto a (possibly different) document.

    The destination is the explicit `pages` list in clipboard order, or - when none
    is given - the source page numbers shifted by `offset` (the "same layout, other
    PDF" case). Pages the destination does not have are reported in `skipped_pages`
    and never written; when nothing fits, this raises instead of guessing.
    """
    block = document_block(config, pdf)
    total = page_count_of(block)
    entries = entries_by_page(config, pdf)
    if not entries:
        raise MappingError(f"Dokumentam nav nevienas lapas plānā: {Path(str(pdf)).name}")

    if pages is None:
        targets = [entry.page + int(offset) for entry in clipboard.entries]
    else:
        if isinstance(pages, (str, bytes)):
            raise MappingError("Lapas jānodod kā sarakstu (izmanto parse_pages)")
        targets = [int(page) for page in pages]

    limit = total or max(entries)
    usable = min(len(targets), clipboard.count)
    pasted: list[dict] = []
    skipped: list[int] = []
    for index, target in enumerate(targets[:usable]):
        source = clipboard.entries[index]
        if target not in entries or target < 1 or (limit and target > limit):
            skipped.append(target)
            continue
        entry = entries[target]
        entry["template"] = source.template
        entry["layer"] = source.layer
        if include_enabled:
            entry["enabled"] = source.enabled
        pasted.append({"page": target, "template": source.template, "layer": source.layer})

    truncated = max(0, clipboard.count - usable)
    unused = [int(page) for page in targets[usable:]]
    if not pasted:
        detail = ", ".join(str(page) for page in (skipped or targets)[:8])
        raise MappingError(
            f"Neviena lapa neietilpst dokumentā {Path(str(pdf)).name} "
            f"(1-{limit}): {detail}; nekas netika ierakstīts"
        )

    if include_document_defaults:
        defaults = config.setdefault("defaults", {})
        defaults["clear_layer"] = bool(clipboard.clear_layer)

    return {
        "pdf": Path(str(pdf)).name,
        "source_pdf": clipboard.source_pdf,
        "pasted": pasted,
        "pasted_pages": [item["page"] for item in pasted],
        "skipped_pages": skipped,
        "unused_pages": unused,
        "truncated": truncated,
        "include_enabled": bool(include_enabled),
        "include_document_defaults": bool(include_document_defaults),
    }


# ------------------------------------------------------------------------- presets


@dataclass(frozen=True)
class PresetInfo:
    """One preset file on disk (what LOAD PRESET lists)."""

    name: str
    path: Path
    entries: int = 0
    pages: int = 0
    created: str = ""
    source_pdf: str = ""

    def summary(self) -> str:
        source = f" | no {self.source_pdf}" if self.source_pdf else ""
        return f"{self.name}: {self.entries} noteikumi, {self.pages} lapas{source}"


def presets_dir(config_dir: str | Path) -> Path:
    """`JOB/CONFIG/presets` (created on demand by the caller that writes there)."""
    return Path(config_dir) / PRESET_DIR_NAME


def preset_file_name(name: str) -> str:
    """A safe preset file name: letters, digits, `_-.` and Latvian letters only."""
    text = str(name or "").strip()
    if not text:
        raise PresetError("Preset nosaukums ir tukšs")
    cleaned = re.sub(r"[^\w\-.\u00c0-\u024f]+", "_", text, flags=re.UNICODE).strip("_.")
    if not cleaned:
        raise PresetError(f"Nederīgs preset nosaukums: {name!r}")
    if not cleaned.lower().endswith(".json"):
        cleaned += ".json"
    return cleaned


def preset_path(folder: str | Path, name: str) -> Path:
    return Path(folder) / preset_file_name(name)


def preset_from_mapping(
    config: dict,
    pdf: str | Path,
    *,
    name: str,
    created: str | None = None,
) -> dict:
    """Compress the current mapping of one document into a preset (mapping intent).

    Consecutive pages that share template / layer / enabled become one range entry,
    so a 300 page plan with 4 templates becomes a short, readable preset.
    """
    wanted = sorted(entries_by_page(config, pdf))
    entries = entries_by_page(config, pdf)
    blocks: list[dict] = []
    for page in wanted:
        entry = entries[page]
        current = (
            entry.get("template"),
            str(entry.get("layer") or LAYER_DEFAULT),
            bool(entry.get("enabled", True)),
        )
        if blocks and blocks[-1]["keys"] == current and blocks[-1]["end"] == page - 1:
            blocks[-1]["end"] = page
            continue
        blocks.append({"keys": current, "start": page, "end": page})

    return {
        "version": PRESET_VERSION,
        "name": str(name).strip(),
        "created": created or datetime.now().isoformat(timespec="seconds"),
        "source": {
            "pdf": Path(str(pdf)).name,
            "page_count": page_count_of(document_block(config, pdf)),
        },
        "entries": [
            {
                "pages": format_pages(range(block["start"], block["end"] + 1)),
                "template": block["keys"][0],
                "layer": block["keys"][1],
                "enabled": block["keys"][2],
            }
            for block in blocks
        ],
    }


def validate_preset(preset: dict | None) -> list[str]:
    """Structural validation of a preset (empty list = valid).

    Rejects anything that is not mapping intent: an entry with an unknown key, a
    document name, an output name or any runtime field (`state`, `attempts`,
    `run_id`, `error_type`, ...) makes the preset invalid.
    """
    problems: list[str] = []
    if not isinstance(preset, dict) or not preset:
        return ["preset nav objekts"]

    if preset.get("version") != PRESET_VERSION:
        problems.append(f"preset.version nav {PRESET_VERSION}: {preset.get('version')!r}")
    if not str(preset.get("name") or "").strip():
        problems.append("preset.name ir tukšs")

    unknown_top = [key for key in preset if key not in PRESET_KEYS]
    if unknown_top:
        problems.append("nezināmas atslēgas presetā: " + ", ".join(sorted(unknown_top)))

    source = preset.get("source")
    if source is not None:
        if not isinstance(source, dict):
            problems.append("preset.source nav objekts")
        else:
            unknown_source = [key for key in source if key not in SOURCE_KEYS]
            if unknown_source:
                problems.append(
                    "nezināmas atslēgas preset.source: " + ", ".join(sorted(unknown_source))
                )

    entries = preset.get("entries")
    if not isinstance(entries, list) or not entries:
        problems.append("preset.entries ir tukšs")
        return problems

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"entries[{index}] nav objekts")
            continue
        forbidden = sorted(set(entry) & set(FORBIDDEN_KEYS))
        if forbidden:
            problems.append(f"entries[{index}] satur izpildes datus: " + ", ".join(forbidden))
        unknown = sorted(set(entry) - set(PRESET_ENTRY_KEYS))
        if unknown:
            problems.append(f"entries[{index}] nezināmas atslēgas: " + ", ".join(unknown))
        pages = entry.get("pages")
        if not isinstance(pages, str) or not pages.strip():
            problems.append(f"entries[{index}].pages ir tukšs")
        else:
            try:
                parse_pages(pages)
            except RangeParseError as exc:
                problems.append(f"entries[{index}].pages: {exc}")
        template = entry.get("template")
        if template is not None and not is_template_file(str(template)):
            problems.append(f"entries[{index}].template nav .ai/.ait: {template!r}")
        layer = entry.get("layer")
        if layer is not None and not str(layer).strip():
            problems.append(f"entries[{index}].layer ir tukšs")
    return problems


def load_preset(path: str | Path) -> dict:
    """Read + validate a preset file (raises `PresetError` when invalid)."""
    data = jsonio.read_json(path, default={})
    if not isinstance(data, dict) or not data:
        raise PresetError(f"Preset nav nolasāms: {Path(str(path)).name}")
    problems = validate_preset(data)
    if problems:
        raise PresetError(f"Nederīgs preset {Path(str(path)).name}: " + "; ".join(problems[:4]))
    return data


def save_preset(path: str | Path, preset: dict) -> Path:
    """Validate and write a preset atomically (JSON, UTF-8, no runtime fields)."""
    problems = validate_preset(preset)
    if problems:
        raise PresetError("Nederīgs preset: " + "; ".join(problems[:4]))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return jsonio.write_json_atomic(target, preset)


def _preset_info(preset: dict, path: Path) -> PresetInfo:
    entries = preset.get("entries") or []
    pages = 0
    for entry in entries:
        try:
            pages += len(parse_pages(str(entry.get("pages"))))
        except (RangeParseError, AttributeError):
            pages += 0
    source = preset.get("source") if isinstance(preset.get("source"), dict) else {}
    return PresetInfo(
        name=str(preset.get("name") or path.stem),
        path=Path(path),
        entries=len(entries),
        pages=pages,
        created=str(preset.get("created") or ""),
        source_pdf=str((source or {}).get("pdf") or ""),
    )


def list_presets(folder: str | Path) -> list[PresetInfo]:
    """Presets of a folder; an unreadable file is listed with `entries == 0`."""
    root = Path(folder)
    if not root.is_dir():
        return []
    infos: list[PresetInfo] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name.lower()):
        try:
            infos.append(_preset_info(load_preset(path), path))
        except PresetError:
            infos.append(PresetInfo(name=path.stem, path=path))
    return infos


def _preset_targets(preset: dict, page_count: int) -> tuple[list[tuple[int, dict]], list[int]]:
    """[(page, entry), ...] the preset would change and the pages it cannot reach."""
    targets: list[tuple[int, dict]] = []
    skipped: list[int] = []
    for entry in preset.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        for page in parse_pages(str(entry.get("pages"))):
            if page_count and page > int(page_count):
                skipped.append(page)
                continue
            targets.append((page, entry))
    return targets, skipped


def preset_preview(
    preset: dict,
    *,
    page_count: int,
    template_dir: str | Path | None = None,
    config: dict | None = None,
    pdf: str | Path | None = None,
) -> dict:
    """What applying this preset would do - computed without touching any file.

    `conflicts` lists the pages the document does not have and the template files the
    preset references but that are missing from TEMPLATE. The GUI shows this before
    it replaces anything; `apply_preset` only ever writes the reachable pages.
    """
    problems = validate_preset(preset)
    if problems:
        raise PresetError("Nederīgs preset: " + "; ".join(problems[:4]))

    targets, skipped = _preset_targets(preset, int(page_count))
    changes: list[dict] = []
    for page, entry in targets:
        changes.append(
            {
                "page": page,
                "template": entry.get("template"),
                "layer": entry.get("layer"),
                "enabled": entry.get("enabled"),
            }
        )

    missing: list[str] = []
    if template_dir is not None:
        folder = Path(template_dir)
        for name in sorted({str(item["template"]) for item in changes if item["template"]}):
            if not (folder / name).is_file():
                missing.append(name)

    before: list[dict] = []
    if config is not None and pdf is not None:
        try:
            entries = entries_by_page(config, pdf)
        except MappingError:
            entries = {}
        for item in changes:
            entry = entries.get(item["page"])
            if entry is None:
                continue
            template = entry.get("template")
            layer = entry.get("layer")
            if template != item["template"] or (item["layer"] and layer != item["layer"]):
                before.append({"page": item["page"], "template": template, "layer": layer})

    return {
        "name": str(preset.get("name") or ""),
        "entries": len(preset.get("entries") or []),
        "targets": len(changes),
        "changes": changes,
        "would_change": before,
        "conflicts": {"beyond_page_count": skipped, "missing_templates": missing},
        "source": preset.get("source") or {},
    }


def apply_preset(
    config: dict,
    pdf: str | Path,
    preset: dict,
    *,
    replace_all: bool = False,
) -> dict:
    """Overlay a preset on one document (plan fields only).

    Pages the document does not have are skipped and reported. `replace_all=True` is
    the destructive variant: pages the preset does not mention go back to the default
    template and the default layer instead of keeping their old mapping.
    """
    problems = validate_preset(preset)
    if problems:
        raise PresetError("Nederīgs preset: " + "; ".join(problems[:4]))

    block = document_block(config, pdf)
    entries = entries_by_page(config, pdf)
    if not entries:
        raise MappingError(f"Dokumentam nav nevienas lapas plānā: {Path(str(pdf)).name}")
    total = page_count_of(block) or max(entries)
    default_layer = str((config.get("defaults") or {}).get("layer") or LAYER_DEFAULT)

    targets, skipped = _preset_targets(preset, total)
    changed: list[int] = []
    for page, entry in targets:
        if page not in entries:
            skipped.append(page)
            continue
        target = entries[page]
        template = entry.get("template")
        layer = str(entry.get("layer") or target.get("layer") or default_layer)
        enabled = entry.get("enabled")
        before = (target.get("template"), target.get("layer"), bool(target.get("enabled", True)))
        target["template"] = template
        target["layer"] = layer
        if enabled is not None:
            target["enabled"] = bool(enabled)
        if (target.get("template"), target.get("layer"), bool(target.get("enabled", True))) != before:
            changed.append(page)

    reset: list[int] = []
    if replace_all:
        covered = {page for page, _entry in targets}
        for page in sorted(entries):
            if page in covered:
                continue
            target = entries[page]
            if target.get("template") is None and target.get("layer") == default_layer:
                continue
            target["template"] = None
            target["layer"] = default_layer
            reset.append(page)

    return {
        "pdf": Path(str(pdf)).name,
        "name": str(preset.get("name") or ""),
        "entries": len(preset.get("entries") or []),
        "changed": changed,
        "reset": reset,
        "skipped_pages": sorted(set(skipped)),
        "replace_all": bool(replace_all),
        "targets": len(targets),
    }







