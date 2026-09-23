"""Naming rules: page padding, output names, job ids, collisions."""

from __future__ import annotations

from pdf_ai_batch.core import naming


def test_page_width_has_a_minimum_of_three_digits():
    assert naming.page_width(1) == 3
    assert naming.page_width(14) == 3
    assert naming.page_width(42) == 3
    assert naming.page_width(300) == 3
    assert naming.page_width(1000) == 4
    assert naming.page_width(10000) == 5
    assert naming.page_width(0) == 3
    assert naming.page_width(None) == 3


def test_default_output_name_matches_the_contract_example():
    assert naming.default_output_name("manual", 1, 42) == "manual__001.ai"
    assert naming.default_output_name("manual", 17, 42) == "manual__017.ai"
    assert naming.default_output_name("book", 186, 186) == "book__186.ai"
    assert naming.default_output_name("big", 7, 1000) == "big__0007.ai"


def test_output_name_for_uses_the_pdf_stem():
    assert naming.output_name_for("C:/JOB/PDF/manual.pdf", 3, 14) == "manual__003.ai"
    assert naming.output_name_for("leaflet.PDF", 1, 1) == "leaflet__001.ai"


def test_job_id_format():
    assert naming.job_id_for("manual.pdf", 17) == "manual_p017"
    assert naming.job_id_for("C:/JOB/PDF/calendar.pdf", 2) == "calendar_p002"


def test_validate_output_name_accepts_contract_names():
    assert naming.validate_output_name("manual__001.ai") == []
    assert naming.validate_output_name("Mājas lapa__012.ai") == []


def test_validate_output_name_rejects_problems():
    assert naming.validate_output_name("")
    assert naming.validate_output_name("manual__001.pdf")
    assert naming.validate_output_name("sub/manual__001.ai")
    assert naming.validate_output_name("manual:001.ai")
    assert naming.validate_output_name("CON.ai")


def test_find_duplicate_outputs_ignores_disabled_pages():
    pages = [
        {"page": 1, "enabled": True, "output": "a__001.ai"},
        {"page": 2, "enabled": True, "output": "a__002.ai"},
        {"page": 3, "enabled": False, "output": "a__001.ai"},
    ]
    assert naming.find_duplicate_outputs(pages) == {}

    pages[2]["enabled"] = True
    duplicates = naming.find_duplicate_outputs(pages)
    assert duplicates == {"a__001.ai": [1, 3]}
