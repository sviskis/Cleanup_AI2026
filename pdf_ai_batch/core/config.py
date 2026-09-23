"""config.json: read, validate, write (atomically).

The config file is the runtime source of truth for a JOB, exactly as approved:

    {
      "version": 1,
      "pdf": "manual.pdf",
      "page_count": 42,
      "defaults": { "template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK", "clear_layer": true },
      "pages": [
        { "page": 1, "enabled": true, "template": "001_cover.ai", "layer": "ARTWORK", "output": "manual__001.ai" },
        { "page": 2, "enabled": true, "template": null,           "layer": "ARTWORK", "output": "manual__002.ai" }
      ]
    }

`template: null` means: inherit defaults.template.
"""

from __future__ import annotations

from pathlib import Path

from . import jsonio
from .contract import LAYER_DEFAULT
from .naming import find_duplicate_outputs, validate_output_name
from .template_mapper import is_template_file, resolve_template

CONFIG_VERSION = 1
DEFAULTS_KEYS = ("template", "layer", "clear_layer")


def new_config(pdf_name: str, page_count: int, pages: list[dict], defaults: dict) -> dict:
    """Assemble a complete config document."""
    return {
        "version": CONFIG_VERSION,
        "pdf": Path(pdf_name).name,
        "page_count": int(page_count),
        "defaults": {
            "template": defaults.get("template"),
            "layer": defaults.get("layer") or LAYER_DEFAULT,
            "clear_layer": bool(defaults.get("clear_layer", True)),
        },
        "pages": [
            {
                "page": int(entry.get("page", index + 1)),
                "enabled": bool(entry.get("enabled", True)),
                "template": entry.get("template"),
                "layer": entry.get("layer") or LAYER_DEFAULT,
                "output": entry.get("output"),
            }
            for index, entry in enumerate(pages)
        ],
    }


def validate_config(config: dict | None) -> list[str]:
    """Structural validation of a config document (empty list = valid)."""
    if not isinstance(config, dict):
        return ["config nav objekts"]

    problems: list[str] = []

    version = config.get("version")
    if version != CONFIG_VERSION:
        problems.append(f"version nav {CONFIG_VERSION}: {version!r}")

    if not config.get("pdf"):
        problems.append("trūkst pdf nosaukuma")

    page_count = config.get("page_count")
    if not isinstance(page_count, int) or page_count < 1:
        problems.append(f"page_count nav derīgs: {page_count!r}")

    defaults = config.get("defaults")
    if not isinstance(defaults, dict):
        problems.append("trūkst defaults sadaļas")
        defaults = {}
    elif not defaults.get("layer"):
        problems.append("defaults.layer ir tukšs")

    pages = config.get("pages")
    if not isinstance(pages, list) or not pages:
        problems.append("pages saraksts ir tukšs")
        return problems

    seen_pages: set[int] = set()
    for index, entry in enumerate(pages):
        if not isinstance(entry, dict):
            problems.append(f"pages[{index}] nav objekts")
            continue
        page = entry.get("page")
        if not isinstance(page, int) or page < 1:
            problems.append(f"pages[{index}].page nav derīgs: {page!r}")
            continue
        if page in seen_pages:
            problems.append(f"lappuse {page} parādās divreiz")
        seen_pages.add(page)
        if isinstance(page_count, int) and page > page_count:
            problems.append(f"lappuse {page} pārsniedz page_count {page_count}")
        template = entry.get("template")
        if template and not is_template_file(template):
            problems.append(f"pages[{index}].template nav .ai/.ait: {template!r}")
        output = entry.get("output")
        if output:
            problems.extend(f"pages[{index}].output: {problem}" for problem in validate_output_name(output))

    duplicates = find_duplicate_outputs(pages)
    for name, page_numbers in duplicates.items():
        problems.append(f"output '{name}' ir vairākām lapām: {page_numbers}")

    return problems


def load_config(path: str | Path) -> dict:
    """Read a config file; returns {} when missing or unparsable."""
    data = jsonio.read_json(path, default={})
    return data if isinstance(data, dict) else {}


def save_config(path: str | Path, config: dict) -> Path:
    """Write the config atomically."""
    return jsonio.write_json_atomic(path, config)


def page_entries(config: dict) -> list[dict]:
    """Safe accessor for the pages list."""
    pages = config.get("pages")
    return pages if isinstance(pages, list) else []


def enabled_page_entries(config: dict) -> list[dict]:
    """Only the entries the operator enabled."""
    return [entry for entry in page_entries(config) if entry.get("enabled", True)]


def resolve_page_template(config: dict, entry: dict, template_dir: str | Path) -> Path | None:
    """Resolve the template for one page entry, applying the default fallback."""
    defaults = config.get("defaults") or {}
    value = entry.get("template") or defaults.get("template")
    return resolve_template(value, template_dir, defaults.get("template"))


def template_mode_for(template_path: str | Path) -> str:
    """copy for .ai (Python copies), saveas for .ait (Illustrator converts)."""
    from .contract import TEMPLATE_MODE_COPY, TEMPLATE_MODE_SAVEAS

    return TEMPLATE_MODE_SAVEAS if Path(str(template_path)).suffix.lower() == ".ait" else TEMPLATE_MODE_COPY
