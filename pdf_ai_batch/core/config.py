"""config.json: read, validate, write (atomically).

The config file is the runtime source of truth for a JOB. Version 2 keeps **one
plan per PDF**, so one JOB can process several documents:

    {
      "version": 2,
      "defaults": { "template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK", "clear_layer": true },
      "documents": [
        {
          "pdf": "manualis.pdf",
          "page_count": 42,
          "enabled": true,
          "pages": [
            { "page": 1, "enabled": true, "template": "001_cover.ai", "layer": "ARTWORK",
              "output": "manualis__001.ai" },
            { "page": 2, "enabled": true, "template": null, "layer": "ARTWORK",
              "output": "manualis__002.ai" }
          ]
        },
        { "pdf": "appendix.pdf", "page_count": 18, "enabled": true, "pages": [] }
      ]
    }

Version 1 held exactly one document (`{"version": 1, "pdf": ..., "page_count": ...,
"pages": [...]}`). `load_config` migrates it **in memory** on read, so an existing
JOB keeps working unchanged; the file is rewritten as v2 the next time a plan is
saved. `template: null` means: inherit `defaults.template` of that document.

`documents[i].enabled` is the operator's switch for the whole PDF; a disabled
document is neither planned nor run, but its pages stay in the file.
`removed_pages` archives entries that a RECONCILE removed (the PDF lost pages), so
nothing is ever silently dropped: if the page comes back it can be restored.
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import jsonio
from .contract import LAYER_DEFAULT
from .naming import find_duplicate_outputs, output_name_for, pdf_id_for, pdf_key_for, validate_output_name
from .template_mapper import is_template_file, resolve_template

CONFIG_VERSION = 2
LEGACY_CONFIG_VERSION = 1
DEFAULT_KEYS = ("template", "layer", "clear_layer")
DOCUMENT_KEYS = ("pdf", "page_count", "enabled", "pages", "removed_pages")


def normalize_defaults(defaults: dict | None) -> dict:
    """The defaults block, with every key present."""
    values = defaults if isinstance(defaults, dict) else {}
    return {
        "template": values.get("template"),
        "layer": values.get("layer") or LAYER_DEFAULT,
        "clear_layer": bool(values.get("clear_layer", True)),
    }


def new_page_entry(entry: dict | None, index: int = 0) -> dict:
    """Normalise one page entry (line/page are derived from the position)."""
    values = entry if isinstance(entry, dict) else {}
    return {
        "page": int(values.get("page", index + 1)),
        "enabled": bool(values.get("enabled", True)),
        "template": values.get("template"),
        "layer": values.get("layer") or LAYER_DEFAULT,
        "output": values.get("output"),
    }


def new_document(
    pdf_name: str,
    page_count: int,
    pages: list[dict] | None = None,
    *,
    enabled: bool = True,
) -> dict:
    """One document block of a version 2 config."""
    return {
        "pdf": Path(str(pdf_name)).name,
        "page_count": int(page_count),
        "enabled": bool(enabled),
        "pages": [new_page_entry(entry, index) for index, entry in enumerate(pages or [])],
    }


def new_documents_from_plan(pdf_name: str, page_count: int, pages: list[dict]) -> list[dict]:
    """Convenience: a single document list from a fresh plan."""
    return [new_document(pdf_name, page_count, pages)]


def new_config(pdf_name: str, page_count: int, pages: list[dict], defaults: dict) -> dict:
    """Assemble a complete **single document** version 2 config.

    Kept with the old signature so every single PDF caller (run_one, the mapping
    editor) keeps working; multi PDF callers use `new_project_config`.
    """
    return {
        "version": CONFIG_VERSION,
        "defaults": normalize_defaults(defaults),
        "documents": [new_document(pdf_name, page_count, pages)],
    }


def new_project_config(documents: list[dict], defaults: dict | None = None) -> dict:
    """Assemble a complete multi document config (keeping the given order)."""
    blocks = [
        new_document(doc.get("pdf"), doc.get("page_count") or 1, doc.get("pages"), enabled=doc.get("enabled", True))
        for doc in documents
    ]
    return {
        "version": CONFIG_VERSION,
        "defaults": normalize_defaults(defaults),
        "documents": blocks,
    }


def migrate_config(config: dict | None) -> tuple[dict, str]:
    """Return (version 2 config, note). A version 1 config is wrapped, never rejected.

    The migration is deliberately lossless: the single document of version 1 becomes
    `documents[0]` with the same page entries and defaults, so the mapping, the
    outputs and the queue item ids of an existing JOB stay exactly as they were.
    """
    if not isinstance(config, dict) or not config:
        return {}, "config nav objekts"

    if config.get("version") == CONFIG_VERSION and isinstance(config.get("documents"), list):
        return config, ""

    if config.get("version") in (None, LEGACY_CONFIG_VERSION) or "pages" in config or "pdf" in config:
        document = new_document(
            config.get("pdf") or "",
            config.get("page_count") or 1,
            config.get("pages") or [],
        )
        migrated = {
            "version": CONFIG_VERSION,
            "defaults": normalize_defaults(config.get("defaults")),
            "documents": [document],
        }
        return migrated, f"config v{config.get('version') or 1} pārveidots uz v2 (1 dokuments)"

    return config, f"nezināma config versija: {config.get('version')!r}"


def validate_config(config: dict | None) -> list[str]:
    """Structural validation of a config document (empty list = valid).

    A version 1 config is migrated first, so every existing JOB validates. The check
    covers the whole project: duplicate documents, duplicate output names inside one
    document **and** across all documents (two PDFs must never write the same AI).
    """
    document, note = migrate_config(config)
    if not document:
        return [note]

    problems: list[str] = []
    if note and note.startswith("nezināma"):
        problems.append(note)

    if document.get("version") != CONFIG_VERSION:
        problems.append(f"version nav {CONFIG_VERSION}: {document.get('version')!r}")

    defaults = document.get("defaults")
    if not isinstance(defaults, dict):
        problems.append("trūkst defaults sadaļas")
    elif not defaults.get("layer"):
        problems.append("defaults.layer ir tukšs")

    documents = document.get("documents")
    if not isinstance(documents, list) or not documents:
        problems.append("documents saraksts ir tukšs")
        return problems

    seen_keys: dict[str, int] = {}
    labels: dict[str, list[str]] = {}
    for index, block in enumerate(documents):
        if not isinstance(block, dict):
            problems.append(f"documents[{index}] nav objekts")
            continue

        pdf_name = str(block.get("pdf") or "")
        if not pdf_name:
            problems.append(f"documents[{index}].pdf ir tukšs")
        elif pdf_name != Path(pdf_name).name:
            problems.append(f"documents[{index}].pdf nedrīkst saturēt mapes: {pdf_name}")

        page_count = block.get("page_count")
        if not isinstance(page_count, int) or page_count < 1:
            problems.append(f"documents[{index}].page_count nav derīgs: {page_count!r}")

        if pdf_name:
            key = pdf_key_for(pdf_name)
            if key in seen_keys:
                problems.append(
                    f"dokuments '{pdf_name}' parādās divreiz (arī documents[{seen_keys[key]}])"
                )
            seen_keys.setdefault(key, index)

        pages = block.get("pages")
        if not isinstance(pages, list):
            problems.append(f"documents[{index}].pages nav saraksts")
            continue

        seen_pages: set[int] = set()
        for page_index, entry in enumerate(pages):
            if not isinstance(entry, dict):
                problems.append(f"documents[{index}].pages[{page_index}] nav objekts")
                continue
            page = entry.get("page")
            if not isinstance(page, int) or page < 1:
                problems.append(
                    f"documents[{index}].pages[{page_index}].page nav derīgs: {page!r}"
                )
                continue
            if page in seen_pages:
                problems.append(f"{pdf_name}: lappuse {page} parādās divreiz")
            seen_pages.add(page)
            if isinstance(page_count, int) and page > page_count:
                problems.append(f"{pdf_name}: lappuse {page} pārsniedz page_count {page_count}")
            template = entry.get("template")
            if template and not is_template_file(template):
                problems.append(f"{pdf_name}: pages[{page_index}].template nav .ai/.ait: {template!r}")
            output = entry.get("output")
            if output:
                problems.extend(
                    f"{pdf_name}: pages[{page_index}].output: {problem}"
                    for problem in validate_output_name(output)
                )
                if str(output).strip() and entry.get("enabled", True):
                    labels.setdefault(str(output).strip().lower(), []).append(f"{pdf_name} l.{page}")

        duplicates = find_duplicate_outputs(pages)
        for name, page_numbers in duplicates.items():
            problems.append(f"{pdf_name}: output '{name}' ir vairākām lapām: {page_numbers}")

    for name, where in labels.items():
        if len(where) > 1:
            problems.append(f"output '{name}' ir vairākiem dokumentiem: {', '.join(where)}")

    return problems


def load_config(path: str | Path, *, migrate: bool = True) -> dict:
    """Read a config file; returns {} when missing or unparsable.

    Version 1 files are migrated **in memory** (see `migrate_config`), so every other
    module only ever sees the version 2 shape. The file on disk is not rewritten here:
    an existing JOB stays byte identical until a plan edit is saved.
    """
    data = jsonio.read_json(path, default={})
    if not isinstance(data, dict) or not data:
        return {}
    if not migrate:
        return data
    return migrate_config(data)[0]


def save_config(path: str | Path, config: dict) -> Path:
    """Write the config atomically, always in the current version."""
    document, note = migrate_config(config)
    if note and not document:
        raise ValueError(note)
    if note:
        logging.getLogger("pdf_ai_batch.config").info("%s -> rakstu kā v%d", note, CONFIG_VERSION)
    return jsonio.write_json_atomic(path, document)


def document_entries(config: dict) -> list[dict]:
    """Every document block, in config order (= the queue order)."""
    blocks = config.get("documents")
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []


def enabled_document_entries(config: dict) -> list[dict]:
    """Only the documents the operator enabled."""
    return [block for block in document_entries(config) if block.get("enabled", True)]


def document_for(config: dict, pdf_name_or_id: str | Path | None) -> dict | None:
    """The document block of one PDF: by file name, stem or comparison key."""
    if not config or not pdf_name_or_id:
        return None
    wanted_name = Path(str(pdf_name_or_id)).name.lower()
    wanted_key = pdf_key_for(pdf_name_or_id)
    for block in document_entries(config):
        name = str(block.get("pdf") or "")
        if name.lower() == wanted_name or (name and pdf_key_for(name) == wanted_key):
            return block
    return None


def page_entries(config: dict, pdf: str | Path | None = None) -> list[dict]:
    """Page entries of one document.

    `pdf=None` returns the entries of the only/first document, which keeps every
    single document caller (and every migrated version 1 JOB) working unchanged.
    """
    if pdf is None:
        blocks = document_entries(config)
        block = blocks[0] if blocks else None
    else:
        block = document_for(config, pdf)
    if not block:
        return []
    pages = block.get("pages")
    return pages if isinstance(pages, list) else []


def enabled_page_entries(config: dict, pdf: str | Path | None = None) -> list[dict]:
    """Only the entries the operator enabled."""
    return [entry for entry in page_entries(config, pdf) if entry.get("enabled", True)]


def all_page_entries(config: dict) -> list[tuple[dict, dict]]:
    """[(document block, page entry), ...] over every document, in config order."""
    pairs: list[tuple[dict, dict]] = []
    for block in document_entries(config):
        pages = block.get("pages")
        if not isinstance(pages, list):
            continue
        pairs.extend((block, entry) for entry in pages if isinstance(entry, dict))
    return pairs


def document_page_count(block: dict | None) -> int:
    """Stored page count of one document (0 when unknown)."""
    value = (block or {}).get("page_count")
    return int(value) if isinstance(value, int) and value > 0 else 0


def resolve_page_template(config: dict, entry: dict, template_dir: str | Path) -> Path | None:
    """Resolve the template for one page entry, applying the default fallback."""
    defaults = config.get("defaults") or {}
    value = entry.get("template") or defaults.get("template")
    return resolve_template(value, template_dir, defaults.get("template"))


def template_mode_for(template_path: str | Path) -> str:
    """copy for .ai (Python copies), saveas for .ait (Illustrator converts)."""
    from .contract import TEMPLATE_MODE_COPY, TEMPLATE_MODE_SAVEAS

    return TEMPLATE_MODE_SAVEAS if Path(str(template_path)).suffix.lower() == ".ait" else TEMPLATE_MODE_COPY


def reconcile_document(
    block: dict,
    *,
    page_count: int,
    defaults: dict | None = None,
) -> tuple[dict, dict]:
    """Rebuild one document for a new PDF page count. Returns (document, report).

    Called only when the operator explicitly reconciles a document whose stored page
    count no longer matches the PDF. The rules:

    * **kept** - pages that still exist keep template / layer / output / enabled
    * **restored** - a page that had been archived earlier comes back with its old
      settings (nothing is ever lost by a reconcile)
    * **added** - new pages get the default template, the default layer and the
      standard output name of the new page count, and start enabled
    * **removed** - pages the PDF no longer has move to `removed_pages`

    `report` = {"pdf", "stored", "current", "kept", "restored", "added", "removed"}.
    """
    pdf_name = str(block.get("pdf") or "")
    stored = document_page_count(block)
    layer = (normalize_defaults(defaults)).get("layer") or LAYER_DEFAULT

    current: dict[int, dict] = {
        int(entry["page"]): entry
        for entry in (block.get("pages") or [])
        if isinstance(entry, dict) and isinstance(entry.get("page"), int) and int(entry["page"]) > 0
    }
    archive: dict[int, dict] = {
        int(entry["page"]): entry
        for entry in (block.get("removed_pages") or [])
        if isinstance(entry, dict) and isinstance(entry.get("page"), int) and int(entry["page"]) > 0
    }

    pages: list[dict] = []
    added: list[int] = []
    restored: list[int] = []
    for page in range(1, int(page_count) + 1):
        entry = current.get(page)
        if entry is None and page in archive:
            entry = dict(archive[page])
            restored.append(page)
        if entry is None:
            entry = {
                "page": page,
                "enabled": True,
                "template": None,
                "layer": layer,
                "output": output_name_for(pdf_name, page, page_count),
            }
            added.append(page)
        pages.append(new_page_entry(entry, page - 1))

    kept = [page for page in range(1, int(page_count) + 1) if page not in added and page not in restored]
    removed = sorted(page for page in {**current, **archive} if page > int(page_count) or page < 1)

    archived_entries = {page: archive.get(page) or current.get(page) for page in removed}
    archived_entries.update(
        {page: archive[page] for page in list(archive) if page <= int(page_count) and page not in restored}
    )
    document = {
        "pdf": pdf_name,
        "page_count": int(page_count),
        "enabled": bool(block.get("enabled", True)),
        "pages": pages,
    }
    if archived_entries:
        document["removed_pages"] = [new_page_entry(archived_entries[page], page - 1) for page in sorted(archived_entries)]

    report = {
        "pdf": pdf_name,
        "stored": stored,
        "current": int(page_count),
        "kept": kept,
        "restored": restored,
        "added": added,
        "removed": removed,
    }
    return document, report


def replace_document(config: dict, document: dict) -> dict:
    """Return a copy of `config` with one document block replaced (or added)."""
    updated = {
        "version": CONFIG_VERSION,
        "defaults": normalize_defaults(config.get("defaults")),
        "documents": [],
    }
    replaced = False
    for block in document_entries(config):
        if pdf_key_for(block.get("pdf") or "") == pdf_key_for(document.get("pdf") or ""):
            updated["documents"].append(document)
            replaced = True
        else:
            updated["documents"].append(block)
    if not replaced:
        updated["documents"].append(document)
    return updated
