"""Template discovery, natural sorting and the automatic page -> template mapping."""

from __future__ import annotations

from pathlib import Path

from pdf_ai_batch.core import template_mapper as tm


def touch(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"%PDF-1.5\n")
    return path


def test_master_templates_are_recognised():
    assert tm.is_master_template("MASTER_AI_TEMPLATE.ai")
    assert tm.is_master_template("MASTER_TEMPLATE.ai")
    assert tm.is_master_template("master_ai_template.ait")
    assert not tm.is_master_template("001_cover.ai")
    assert not tm.is_master_template("017.ai")


def test_templates_are_sorted_naturally_and_masters_kept_out_of_the_pool(tmp_path):
    for name in ("10.ai", "2.ai", "1.ai", "MASTER_AI_TEMPLATE.ai"):
        touch(tmp_path, name)

    assert [p.name for p in tm.list_templates(tmp_path)] == ["1.ai", "2.ai", "10.ai", "MASTER_AI_TEMPLATE.ai"]
    assert [p.name for p in tm.page_template_pool(tmp_path)] == ["1.ai", "2.ai", "10.ai"]


def test_auto_mapping_is_positional_and_pages_beyond_the_pool_inherit_default(tmp_path):
    for name in ("001_cover.ai", "002_intro.ai", "003_body.ai"):
        touch(tmp_path, name)

    pages = tm.auto_assign_pages(5, tm.page_template_pool(tmp_path))
    assert [page["template"] for page in pages] == [
        "001_cover.ai",
        "002_intro.ai",
        "003_body.ai",
        None,
        None,
    ]
    assert [page["page"] for page in pages] == [1, 2, 3, 4, 5]
    assert all(page["enabled"] is True for page in pages)
    assert all(page["layer"] == "ARTWORK" for page in pages)


def test_default_template_prefers_configured_then_master(tmp_path):
    touch(tmp_path, "MASTER_AI_TEMPLATE.ai")
    assert tm.default_template(tmp_path).name == "MASTER_AI_TEMPLATE.ai"

    touch(tmp_path, "special_default.ai")
    assert tm.default_template(tmp_path, "special_default.ai").name == "special_default.ai"
    assert tm.default_template(tmp_path, "nope.ai").name == "MASTER_AI_TEMPLATE.ai"


def test_resolve_template_handles_names_paths_and_fallback(tmp_path):
    cover = touch(tmp_path, "001_cover.ai")
    fallback = touch(tmp_path, "MASTER_AI_TEMPLATE.ai")

    assert tm.resolve_template("001_cover.ai", tmp_path, fallback) == cover
    assert tm.resolve_template(str(cover), tmp_path, fallback) == cover
    assert tm.resolve_template(None, tmp_path, fallback) == fallback
    assert tm.resolve_template("", tmp_path, fallback) == fallback
    assert tm.resolve_template("missing.ai", tmp_path, fallback) is None


def test_build_page_plan_fills_output_names_and_defaults(tmp_path):
    for name in ("001_cover.ai", "002_intro.ai"):
        touch(tmp_path, name)
    touch(tmp_path, "MASTER_AI_TEMPLATE.ai")

    pages, defaults, fallback = tm.build_page_plan("manual.pdf", 4, tmp_path)

    assert pages[0]["output"] == "manual__001.ai"
    assert pages[3]["output"] == "manual__004.ai"
    assert pages[2]["template"] is None
    assert defaults["template"] == "MASTER_AI_TEMPLATE.ai"
    assert defaults["layer"] == "ARTWORK"
    assert defaults["clear_layer"] is True
    assert fallback is not None and fallback.name == "MASTER_AI_TEMPLATE.ai"


def test_template_stats_summarises_the_folder(tmp_path):
    touch(tmp_path, "1.ai")
    touch(tmp_path, "2.ai")
    touch(tmp_path, "MASTER_AI_TEMPLATE.ai")

    stats = tm.template_stats(tmp_path)
    assert stats["count"] == 3
    assert stats["pool_count"] == 2
    assert stats["masters"] == ["MASTER_AI_TEMPLATE.ai"]
    assert stats["default"] == "MASTER_AI_TEMPLATE.ai"


def test_empty_folder_yields_no_templates(tmp_path):
    assert tm.list_templates(tmp_path) == []
    assert tm.default_template(tmp_path) is None
    pages = tm.auto_assign_pages(2, [])
    assert [page["template"] for page in pages] == [None, None]
