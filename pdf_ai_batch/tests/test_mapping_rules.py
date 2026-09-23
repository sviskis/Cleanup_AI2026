"""Bulk mapping tests (milestone 6): ranges, bulk assign, numbered map, copy/paste, presets.

`core/mapping_rules.py` is where every bulk mapping decision lives, so it is tested
here without a display, without Illustrator and - for most cases - without files:
the config dict is the unit under test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_ai_batch.core import config as cfg
from pdf_ai_batch.core import mapping_rules as mr


# ------------------------------------------------------------------------ fixtures


def make_config(pdf_count: int, *, documents: int = 1, defaults: dict | None = None) -> dict:
    """A version 2 config with `documents` PDFs of `pdf_count` pages each."""
    pages = [
        {"page": page, "enabled": True, "template": None, "layer": "ARTWORK", "output": None}
        for page in range(1, pdf_count + 1)
    ]
    blocks = []
    for index in range(documents):
        name = "manualis.pdf" if index == 0 else f"appendix{index}.pdf"
        blocks.append(cfg.new_document(name, pdf_count, pages))
    return cfg.new_project_config(
        blocks,
        defaults or {"template": "MASTER_AI_TEMPLATE.ai", "layer": "ARTWORK", "clear_layer": True},
    )


def templates_of(config: dict, pdf: str = "manualis.pdf") -> list[str | None]:
    return [entry["template"] for entry in cfg.page_entries(config, pdf)]


def make_templates(folder: Path, names: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"%PDF-1.5\ntemplate\n")


# ---------------------------------------------------------------------- range parser


def test_range_parser_single_page():
    assert mr.parse_pages("7") == [7]
    assert mr.parse_pages(" 7 ") == [7]


def test_range_parser_contiguous_range():
    assert mr.parse_pages("2-5") == [2, 3, 4, 5]
    assert mr.parse_pages("2-2") == [2]


def test_range_parser_mixed_syntax():
    assert mr.parse_pages("1-5,8,10-14") == [1, 2, 3, 4, 5, 8, 10, 11, 12, 13, 14]
    assert mr.parse_pages("1,3,5") == [1, 3, 5]
    # duplicates collapse, the order is always ascending
    assert mr.parse_pages("5,1-3,3") == [1, 2, 3, 5]


def test_range_parser_all_pages_token():
    assert mr.parse_pages("*", page_count=4) == [1, 2, 3, 4]
    assert mr.parse_pages("visas", page_count=3) == [1, 2, 3]
    with pytest.raises(mr.RangeParseError):
        mr.parse_pages("*")


def test_range_parser_reversed_range_is_normalized():
    assert mr.parse_pages("5-3") == [3, 4, 5]
    with pytest.raises(mr.RangeParseError):
        mr.parse_pages("5-3", normalize_reversed=False)


@pytest.mark.parametrize(
    "text",
    ["0", "1-0", "-3", "1--5", "1.5", "1-", "-", "a", "1,a", "1,,2", "", "   ", "1-999999999"],
)
def test_range_parser_rejects_malformed_text(text):
    with pytest.raises(mr.RangeParseError):
        mr.parse_pages(text)


def test_range_parser_rejects_pages_beyond_the_document():
    assert mr.parse_pages("1-4", page_count=4) == [1, 2, 3, 4]
    with pytest.raises(mr.RangeParseError) as excinfo:
        mr.parse_pages("1-5", page_count=4)
    assert "1-4" in str(excinfo.value)


def test_format_pages_compresses_ranges():
    assert mr.format_pages([1, 2, 3, 4, 5, 8, 10, 11]) == "1-5,8,10-11"
    assert mr.format_pages([]) == ""
    assert mr.format_pages([3]) == "3"


# ------------------------------------------------------------------- bulk assignment


def test_assign_template_to_selected_and_to_range():
    config = make_config(10)

    report = mr.assign_template(config, "manualis.pdf", [1], "cover.ai")
    assert report["changed"] == [1]
    assert templates_of(config)[0] == "cover.ai"

    report = mr.assign_template(config, "manualis.pdf", mr.parse_pages("2-5"), "intro.ai", layer="ARTWORK")
    assert report["changed"] == [2, 3, 4, 5]
    assert templates_of(config)[1:5] == ["intro.ai"] * 4
    assert templates_of(config)[5] is None  # page 6 untouched


def test_assign_template_uses_the_default_when_template_is_none():
    config = make_config(3)
    mr.assign_template(config, "manualis.pdf", [2], "cover.ai")

    report = mr.use_default_template(config, "manualis.pdf", [2])

    assert report["template"] is None
    assert templates_of(config)[1] is None


def test_assign_template_validates_the_extension_and_the_pages():
    config = make_config(3)
    with pytest.raises(mr.MappingError):
        mr.assign_template(config, "manualis.pdf", [1], "cover.txt")
    with pytest.raises(mr.MappingError):
        mr.assign_template(config, "manualis.pdf", [4], "cover.ai")
    with pytest.raises(mr.MappingError):
        mr.assign_template(config, "manualis.pdf", [], "cover.ai")
    with pytest.raises(mr.MappingError):
        mr.assign_template(config, "manualis.pdf", "1-3", "cover.ai")  # a list is required
    with pytest.raises(mr.MappingError):
        mr.assign_template(config, "missing.pdf", [1], "cover.ai")


def test_clear_override_and_set_layer_and_enabled():
    config = make_config(3)
    mr.assign_template(config, "manualis.pdf", [1, 2], "cover.ai", layer="COVER")

    mr.clear_override(config, "manualis.pdf", [1])
    assert templates_of(config)[0] is None
    assert cfg.page_entries(config, "manualis.pdf")[0]["layer"] == "ARTWORK"

    mr.set_layer(config, "manualis.pdf", [3], "TEXT")
    assert cfg.page_entries(config, "manualis.pdf")[2]["layer"] == "TEXT"
    with pytest.raises(mr.MappingError):
        mr.set_layer(config, "manualis.pdf", [3], "  ")

    report = mr.set_enabled(config, "manualis.pdf", [1, 2], False)
    assert report["changed"] == [1, 2]
    assert [entry["enabled"] for entry in cfg.page_entries(config, "manualis.pdf")] == [False, False, True]


def test_bulk_assignment_keeps_the_other_documents_untouched():
    config = make_config(4, documents=2)
    mr.assign_template(config, "manualis.pdf", [1, 2], "cover.ai")

    assert templates_of(config, "manualis.pdf") == ["cover.ai", "cover.ai", None, None]
    assert templates_of(config, "appendix1.pdf") == [None, None, None, None]


# ------------------------------------------------------------- numbered auto mapping


def test_template_number_reads_the_leading_number():
    assert mr.template_number("001_cover.ai") == 1
    assert mr.template_number("12_intro.ai") == 12
    assert mr.template_number("003_pagina.ait") == 3
    assert mr.template_number("MASTER_AI_TEMPLATE.ai") is None
    assert mr.template_number("cover.ai") is None


def test_numbered_auto_map_assigns_page_n_to_template_number_n(tmp_path):
    folder = tmp_path / "TEMPLATE"
    make_templates(folder, ["001_cover.ai", "002_intro.ai", "003_page.ai", "MASTER_AI_TEMPLATE.ai"])
    config = make_config(5)

    report = mr.auto_map_by_number(config, "manualis.pdf", page_count=5, template_dir=folder)

    assert report["assigned"] == {1: "001_cover.ai", 2: "002_intro.ai", 3: "003_page.ai"}
    assert report["assigned_count"] == 3
    assert report["unmatched"] == [4, 5]
    assert report["problems"] == []
    assert templates_of(config) == ["001_cover.ai", "002_intro.ai", "003_page.ai", None, None]


def test_numbered_auto_map_never_uses_a_master_template(tmp_path):
    folder = tmp_path / "TEMPLATE"
    # both reserved MASTER names and the "master*" prefix are the default template
    make_templates(folder, ["MASTER_AI_TEMPLATE.ai", "MASTER_TEMPLATE.ai", "master_extra.ai", "001_cover.ai"])
    config = make_config(3)

    report = mr.auto_map_by_number(config, "manualis.pdf", page_count=3, template_dir=folder)

    used = {name for name in report["assigned"].values()}
    assert used == {"001_cover.ai"}
    assert report["pool"] == {1: "001_cover.ai"}
    assert all("master" not in name.lower() for name in report["pool"].values())


def test_numbered_auto_map_reports_an_ambiguous_number_instead_of_guessing(tmp_path):
    folder = tmp_path / "TEMPLATE"
    make_templates(folder, ["006_a.ai", "006_b.ai", "007_c.ai"])
    config = make_config(7)

    report = mr.auto_map_by_number(config, "manualis.pdf", page_count=7, template_dir=folder)

    assert 6 not in report["assigned"]
    assert report["ambiguous"] == {6: ["006_a.ai", "006_b.ai"]}
    assert report["problems"] and "6" in report["problems"][0]
    assert report["assigned"] == {7: "007_c.ai"}
    assert templates_of(config)[5] is None  # page 6 was not touched


def test_numbered_auto_map_uses_natural_sort_and_reports_unmatched(tmp_path):
    folder = tmp_path / "TEMPLATE"
    make_templates(folder, ["10_ten.ai", "2_two.ai", "1_one.ai", "cover.ai"])
    config = make_config(3)

    report = mr.auto_map_by_number(config, "manualis.pdf", page_count=3, template_dir=folder)

    assert list(report["pool"]) == [1, 2, 10]
    assert report["assigned"] == {1: "1_one.ai", 2: "2_two.ai"}
    assert report["unmatched"] == [3]
    assert report["unnumbered"] == ["cover.ai"]
    assert report["out_of_range"] == {10: "10_ten.ai"}


def test_numbered_auto_map_needs_a_page_count_and_a_folder():
    config = make_config(3)
    with pytest.raises(mr.MappingError):
        mr.auto_map_by_number(config, "manualis.pdf", page_count=0, template_dir=".")
    with pytest.raises(mr.MappingError):
        mr.auto_map_by_number(config, "manualis.pdf", page_count=3)


# -------------------------------------------------------------------- copy and paste


def test_copy_mapping_carries_plan_data_only():
    config = make_config(6)
    mr.assign_template(config, "manualis.pdf", [2, 3], "intro.ai", layer="INTRO")
    mr.set_enabled(config, "manualis.pdf", [3], False)

    clipboard = mr.copy_mapping(config, "manualis.pdf", [2, 3], include_enabled=True)

    assert clipboard.source_pdf == "manualis.pdf"
    assert clipboard.pages == [2, 3]
    assert clipboard.templates == ["intro.ai"]
    assert [entry.layer for entry in clipboard.entries] == ["INTRO", "INTRO"]
    assert [entry.enabled for entry in clipboard.entries] == [True, False]
    assert clipboard.clear_layer is True
    payload = json.dumps([entry.as_dict() for entry in clipboard.entries])
    for forbidden in ("state", "attempts", "run_id", "error", "output", "job_id", "manualis__"):
        assert forbidden not in payload
    assert "2 lapas no manualis.pdf (2-3)" in clipboard.summary()


def test_paste_mapping_onto_selected_pages_within_one_pdf():
    config = make_config(10)
    mr.assign_template(config, "manualis.pdf", [6, 7], "section.ai", layer="SEC")
    clipboard = mr.copy_mapping(config, "manualis.pdf", [6, 7])

    report = mr.paste_mapping(config, "manualis.pdf", clipboard, pages=[9, 10])

    assert report["pasted_pages"] == [9, 10]
    assert report["skipped_pages"] == []
    assert [entry["template"] for entry in cfg.page_entries(config, "manualis.pdf")[8:]] == ["section.ai"] * 2
    assert [entry["layer"] for entry in cfg.page_entries(config, "manualis.pdf")[8:]] == ["SEC"] * 2


def test_paste_mapping_uses_the_source_pages_when_no_selection_is_given():
    config = make_config(6)
    mr.assign_template(config, "manualis.pdf", [1, 2, 3], "cover.ai")

    clipboard = mr.copy_mapping(config, "manualis.pdf", [1, 2, 3])
    mr.use_default_template(config, "manualis.pdf", [1, 2, 3])
    report = mr.paste_mapping(config, "manualis.pdf", clipboard)

    assert report["pasted_pages"] == [1, 2, 3]
    assert templates_of(config)[:3] == ["cover.ai"] * 3


def test_paste_mapping_supports_cross_pdf_and_an_offset():
    config = make_config(4, documents=2)
    mr.assign_template(config, "manualis.pdf", [1, 2], "cover.ai", layer="COVER")
    clipboard = mr.copy_mapping(config, "manualis.pdf", [1, 2])

    report = mr.paste_mapping(config, "appendix1.pdf", clipboard, offset=2)

    assert report["source_pdf"] == "manualis.pdf"
    assert report["pdf"] == "appendix1.pdf"
    assert report["pasted_pages"] == [3, 4]
    assert templates_of(config, "appendix1.pdf") == [None, None, "cover.ai", "cover.ai"]
    assert templates_of(config, "manualis.pdf") == ["cover.ai", "cover.ai", None, None]


def test_paste_mapping_never_writes_beyond_the_destination_page_count():
    config = make_config(3, documents=2)  # manualis: 3 pages, appendix1: 3 pages
    mr.assign_template(config, "manualis.pdf", [1, 2, 3], "cover.ai")
    clipboard = mr.copy_mapping(config, "manualis.pdf", [1, 2, 3])

    report = mr.paste_mapping(config, "appendix1.pdf", clipboard, pages=[2, 3, 4, 5])

    assert report["pasted_pages"] == [2, 3]
    assert report["skipped_pages"] == [4]  # page 4 exists, but the document has 3 pages
    assert report["unused_pages"] == [5]  # no clipboard entry was left for it
    assert report["truncated"] == 0  # every clipboard entry got a target slot

    # fewer targets than copied pages: the rest is reported, not pasted anywhere
    short = mr.paste_mapping(config, "appendix1.pdf", clipboard, pages=[3])
    assert short["pasted_pages"] == [3]
    assert short["truncated"] == 2
    assert short["unused_pages"] == []

    # nothing fits -> an error, never a silent no-op
    with pytest.raises(mr.MappingError):
        mr.paste_mapping(config, "appendix1.pdf", clipboard, pages=[9, 10])


def test_paste_mapping_copies_enabled_only_when_asked():
    config = make_config(4, documents=2)
    mr.set_enabled(config, "manualis.pdf", [1, 2], False)
    clipboard_on = mr.copy_mapping(config, "manualis.pdf", [1, 2], include_enabled=True)
    clipboard_off = mr.copy_mapping(config, "manualis.pdf", [1, 2])

    mr.paste_mapping(config, "appendix1.pdf", clipboard_off, pages=[1, 2])
    assert [entry["enabled"] for entry in cfg.page_entries(config, "appendix1.pdf")] == [True] * 4

    mr.paste_mapping(config, "appendix1.pdf", clipboard_on, pages=[3, 4], include_enabled=True)
    assert [entry["enabled"] for entry in cfg.page_entries(config, "appendix1.pdf")][2:] == [False, False]


def test_paste_mapping_can_take_over_clear_layer():
    config = make_config(3, documents=2)
    config["defaults"]["clear_layer"] = False
    clipboard = mr.copy_mapping(config, "manualis.pdf", [1])
    config["defaults"]["clear_layer"] = True

    report = mr.paste_mapping(
        config, "appendix1.pdf", clipboard, pages=[1], include_document_defaults=True
    )

    assert report["include_document_defaults"] is True
    assert config["defaults"]["clear_layer"] is False


# -------------------------------------------------------------------------- presets


def test_preset_from_mapping_compresses_ranges():
    config = make_config(40)
    mr.assign_template(config, "manualis.pdf", [1], "cover.ai")
    mr.assign_template(config, "manualis.pdf", [2, 3, 4, 5], "intro.ai")
    mr.assign_template(config, "manualis.pdf", [36], "separator.ai", layer="SEP")

    preset = mr.preset_from_mapping(config, "manualis.pdf", name="magazine_32_pages")

    assert mr.validate_preset(preset) == []
    assert preset["version"] == mr.PRESET_VERSION
    assert preset["source"] == {"pdf": "manualis.pdf", "page_count": 40}
    assert [entry["pages"] for entry in preset["entries"]] == ["1", "2-5", "6-35", "36", "37-40"]
    assert preset["entries"][2]["template"] is None  # the MASTER default block
    assert preset["entries"][3]["layer"] == "SEP"
    assert preset["entries"][0]["template"] == "cover.ai"


def test_preset_save_load_round_trip_and_info(tmp_path):
    config = make_config(6)
    mr.assign_template(config, "manualis.pdf", [1, 2], "cover.ai")
    folder = mr.presets_dir(tmp_path / "CONFIG")
    preset = mr.preset_from_mapping(config, "manualis.pdf", name="Mans Presets", created="2026-09-23T20:15:03")

    path = mr.save_preset(mr.preset_path(folder, "Mans Presets"), preset)

    assert path.is_file() and path.name == "Mans_Presets.json"
    assert mr.presets_dir(tmp_path / "CONFIG") == folder
    loaded = mr.load_preset(path)
    assert loaded == preset
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["created"] == "2026-09-23T20:15:03"
    infos = mr.list_presets(folder)
    assert [info.name for info in infos] == ["Mans Presets"]
    assert infos[0].entries == 2 and infos[0].pages == 6
    assert "manualis.pdf" in infos[0].summary()


def test_preset_keeps_latvian_names_and_paths(tmp_path):
    config = make_config(4)
    mr.assign_template(config, "manualis.pdf", [1], "Vaks_zils.ai", layer="VAKS")
    folder = mr.presets_dir(tmp_path / "MAPI\u0145A ar atstarp\u0113m")

    preset = mr.preset_from_mapping(config, "manualis.pdf", name="\u017durn\u0101ls 32 lpp")
    path = mr.save_preset(mr.preset_path(folder, "\u017durn\u0101ls 32 lpp"), preset)

    assert path.is_file()
    assert path.name == "\u017durn\u0101ls_32_lpp.json"
    assert mr.load_preset(path)["entries"][0]["layer"] == "VAKS"


def test_preset_schema_validation_rejects_bad_documents():
    good = {"version": mr.PRESET_VERSION, "name": "x", "entries": [{"pages": "1-2", "template": "a.ai"}]}
    assert mr.validate_preset(good) == []
    assert mr.validate_preset(None) == ["preset nav objekts"]
    assert mr.validate_preset("nope") == ["preset nav objekts"]

    assert any("version" in problem for problem in mr.validate_preset(dict(good, version=99)))
    assert any("name" in problem for problem in mr.validate_preset(dict(good, name="  ")))
    assert any("entries" in problem for problem in mr.validate_preset(dict(good, entries=[])))
    assert any(
        "pages" in problem
        for problem in mr.validate_preset({"version": 1, "name": "x", "entries": [{"pages": "0"}]})
    )
    assert any(
        "template" in problem
        for problem in mr.validate_preset({"version": 1, "name": "x", "entries": [{"pages": "1", "template": "a.txt"}]})
    )
    assert any(
        "nezin\u0101mas" in problem
        for problem in mr.validate_preset({"version": 1, "name": "x", "entries": [{"pages": "1", "colour": "red"}]})
    )
    assert any("nezin\u0101mas atsl\u0113gas preset\u0101" in problem for problem in mr.validate_preset(dict(good, extra="v")))
    assert any(
        "preset.source" in problem
        for problem in mr.validate_preset(
            {"version": 1, "name": "x", "source": {"pdf": "a.pdf", "state": "DONE"}, "entries": good["entries"]}
        )
    )


def test_presets_contain_no_state_or_runtime_fields():
    """A preset is mapping intent: runtime/execution data is rejected, never stored."""
    config = make_config(5)
    mr.assign_template(config, "manualis.pdf", [1, 2], "cover.ai")
    preset = mr.preset_from_mapping(config, "manualis.pdf", name="t\u012brs")

    stored = json.dumps(preset)
    for forbidden in ("state", "attempts", "run_id", "error", "output", "job_id", "last_run"):
        assert f'"{forbidden}"' not in stored

    for key in ("state", "attempts", "run_id", "error_type", "output", "job_id", "stats"):
        dirty = {
            "version": mr.PRESET_VERSION,
            "name": "net\u012brs",
            "entries": [{"pages": "1", "template": "cover.ai", key: "x"}],
        }
        assert any("izpildes datus" in problem for problem in mr.validate_preset(dirty)), dirty
        with pytest.raises(mr.PresetError):
            mr.save_preset(Path("unused.json"), dirty)


def test_preset_apply_overlays_and_reports_what_it_cannot_reach():
    config = make_config(10)
    preset = {
        "version": mr.PRESET_VERSION,
        "name": "standarta",
        "entries": [
            {"pages": "1", "template": "cover.ai", "layer": "COVER"},
            {"pages": "2-5", "template": "intro.ai"},
            {"pages": "6-12", "template": "page.ai"},
        ],
    }
    mr.assign_template(config, "manualis.pdf", [9], "leftover.ai")

    report = mr.apply_preset(config, "manualis.pdf", preset)

    assert report["changed"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert report["skipped_pages"] == [11, 12]
    assert templates_of(config)[0] == "cover.ai"
    assert cfg.page_entries(config, "manualis.pdf")[0]["layer"] == "COVER"
    assert templates_of(config)[4] == "intro.ai"
    assert templates_of(config)[5:] == ["page.ai"] * 5


def test_preset_apply_replace_all_resets_uncovered_pages():
    config = make_config(6)
    mr.assign_template(config, "manualis.pdf", [5, 6], "old.ai", layer="OLD")
    preset = {"version": 1, "name": "mazais", "entries": [{"pages": "1", "template": "cover.ai"}]}

    report = mr.apply_preset(config, "manualis.pdf", preset, replace_all=True)

    # 2-4 were already on the default template + layer, so only 5 and 6 really change
    assert report["reset"] == [5, 6]
    assert templates_of(config) == ["cover.ai", None, None, None, None, None]
    assert cfg.page_entries(config, "manualis.pdf")[5]["layer"] == "ARTWORK"


def test_preset_apply_validates_before_writing_anything():
    config = make_config(4)
    mr.assign_template(config, "manualis.pdf", [1], "keep.ai")
    before = json.dumps(config)
    broken = {"version": 1, "name": "salauzts", "entries": [{"pages": "9-", "template": "x.ai"}]}

    with pytest.raises(mr.PresetError):
        mr.apply_preset(config, "manualis.pdf", broken)

    assert json.dumps(config) == before


def test_preset_preview_reports_conflicts_without_changing_anything(tmp_path):
    folder = tmp_path / "TEMPLATE"
    make_templates(folder, ["cover.ai"])
    config = make_config(4)
    mr.assign_template(config, "manualis.pdf", [1], "cover.ai")
    before = json.dumps(config)
    preset = {
        "version": 1,
        "name": "ar konfliktiem",
        "entries": [
            {"pages": "1-2", "template": "cover.ai"},
            {"pages": "3-6", "template": "missing.ai"},
        ],
    }

    preview = mr.preset_preview(preset, page_count=4, template_dir=folder, config=config, pdf="manualis.pdf")

    assert preview["targets"] == 4
    assert preview["conflicts"]["beyond_page_count"] == [5, 6]
    assert preview["conflicts"]["missing_templates"] == ["missing.ai"]
    # page 1 keeps cover.ai, pages 2-4 would change (2 -> cover.ai, 3-4 -> missing.ai)
    assert [item["page"] for item in preview["would_change"]] == [2, 3, 4]
    assert json.dumps(config) == before  # a preview never writes

    with pytest.raises(mr.PresetError):
        mr.preset_preview({"version": 1, "name": "x", "entries": []}, page_count=4)


def test_list_presets_reports_an_invalid_file_without_crashing(tmp_path):
    folder = mr.presets_dir(tmp_path / "CONFIG")
    folder.mkdir(parents=True)
    (folder / "broken.json").write_text("{not json", encoding="utf-8")
    mr.save_preset(
        folder / "good.json",
        {"version": 1, "name": "labais", "entries": [{"pages": "1", "template": "a.ai"}]},
    )

    infos = {info.name: info for info in mr.list_presets(folder)}

    assert sorted(infos) == ["broken", "labais"]
    assert infos["broken"].entries == 0
    assert infos["labais"].pages == 1
    with pytest.raises(mr.PresetError):
        mr.load_preset(folder / "broken.json")
    assert mr.list_presets(tmp_path / "nav") == []




