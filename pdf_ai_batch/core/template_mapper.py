"""Template discovery, natural sorting and page -> template mapping.

Rules (from the approved plan):

* templates live in JOB/TEMPLATE and are sorted NATURALLY: 1.ai, 2.ai, 3.ai, 10.ai
* automatic mapping is positional: page 1 -> template 1, page 2 -> template 2 ...
* MASTER_AI_TEMPLATE.ai / MASTER_TEMPLATE.ai are the DEFAULT template and must
  never be handed out as if they were page templates, unless the operator picks
  them explicitly
* a page without its own template inherits `defaults.template`
"""

from __future__ import annotations

from pathlib import Path

from .naming import default_output_name, pdf_stem
from .pdf_info import natural_key, sorted_naturally

TEMPLATE_EXTENSIONS = (".ai", ".ait")
MASTER_NAMES = ("master_ai_template.ai", "master_template.ai", "master_ai_template.ait", "master_template.ait")
LAYER_DEFAULT = "ARTWORK"


def is_template_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in TEMPLATE_EXTENSIONS


def is_master_template(path: str | Path) -> bool:
    """True for the reserved default template names (case insensitive)."""
    name = Path(str(path)).name.lower()
    if name in MASTER_NAMES:
        return True
    return name.startswith("master")


def list_templates(folder: str | Path) -> list[Path]:
    """All template files in a folder, sorted naturally."""
    root = Path(folder)
    if not root.is_dir():
        return []
    files = [p for p in root.iterdir() if p.is_file() and is_template_file(p)]
    return sorted_naturally(files)


def page_template_pool(folder: str | Path) -> list[Path]:
    """Templates usable for positional auto mapping (masters excluded)."""
    return [p for p in list_templates(folder) if not is_master_template(p)]


def default_template(folder: str | Path, configured: str | None = None) -> Path | None:
    """Resolve the default (fallback) template.

    `configured` is the value from the config file; when it is missing or does
    not exist, the first MASTER_* file in the folder is used. The path that comes
    back is always the REAL file from the folder listing, so the name keeps the
    case the file has on disk (important on case sensitive shares).
    """
    root = Path(folder)
    available = list_templates(root)
    by_lower = {path.name.lower(): path for path in available}

    if configured:
        candidate = by_lower.get(Path(configured).name.lower())
        if candidate is not None:
            return candidate
        direct = Path(str(configured))
        if direct.is_file():
            return direct

    for name in MASTER_NAMES:
        candidate = by_lower.get(name)
        if candidate is not None:
            return candidate

    masters = [path for path in available if is_master_template(path)]
    if masters:
        return masters[0]
    return None


def resolve_template(
    template_value: str | None,
    template_dir: str | Path,
    default: str | Path | None,
) -> Path | None:
    """Turn a config value (file name, path or None) into an existing file.

    None or an empty value means: use the default template.
    """
    if template_value:
        candidate = Path(str(template_value))
        if not candidate.is_absolute():
            candidate = Path(template_dir) / candidate.name
        if candidate.is_file():
            return candidate
        direct = Path(str(template_value))
        if direct.is_file():
            return direct
        return None
    if default:
        return Path(default)
    return None


def auto_assign_pages(page_count: int, pool: list[Path]) -> list[dict]:
    """Build the config `pages` list for positional automatic mapping.

    Page 1 gets pool[0], page 2 gets pool[1] and so on. Pages beyond the pool
    keep template None, which means "inherit defaults.template".
    """
    total = int(page_count)
    pages: list[dict] = []
    for page in range(1, total + 1):
        template = pool[page - 1].name if page - 1 < len(pool) else None
        pages.append(
            {
                "page": page,
                "enabled": True,
                "template": template,
                "layer": LAYER_DEFAULT,
                "output": None,
            }
        )
    return pages


def fill_output_names(pages: list[dict], stem: str, page_count: int) -> list[dict]:
    """Fill in missing output names using the naming rules."""
    result: list[dict] = []
    for page_cfg in pages:
        entry = dict(page_cfg)
        if not entry.get("output"):
            entry["output"] = default_output_name(stem, int(entry.get("page", 1)), page_count)
        result.append(entry)
    return result


def build_page_plan(
    pdf_path: str | Path,
    page_count: int,
    template_dir: str | Path,
    configured_default: str | None = None,
) -> tuple[list[dict], dict, Path | None]:
    """Full automatic plan: page entries, defaults block and default template.

    Returns (pages, defaults, default_template_path).
    """
    pool = page_template_pool(template_dir)
    fallback = default_template(template_dir, configured_default)
    stem = pdf_stem(pdf_path)
    pages = fill_output_names(auto_assign_pages(page_count, pool), stem, page_count)
    defaults = {
        "template": fallback.name if fallback else None,
        "layer": LAYER_DEFAULT,
        "clear_layer": True,
    }
    return pages, defaults, fallback


def template_stats(template_dir: str | Path) -> dict:
    """Small summary used by the GUI and by preflight output."""
    all_templates = list_templates(template_dir)
    pool = page_template_pool(template_dir)
    fallback = default_template(template_dir)
    return {
        "count": len(all_templates),
        "pool": [p.name for p in pool],
        "pool_count": len(pool),
        "masters": [p.name for p in all_templates if is_master_template(p)],
        "default": fallback.name if fallback else None,
    }


def sort_check(names: list[str]) -> list[str]:
    """Helper for tests and the GUI: names in the positional order used here."""
    return [p.name for p in sorted_naturally([Path(n) for n in names])]
