"""The contract: request building/validation, result parsing and the fixtures.

The fixtures in tests/fixtures are the SAME files verified from the JSX side by
tests/jscript/test_json_contract.js, which is what makes them a contract test
instead of two independent expectations.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_ai_batch.core import contract

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_request_fixture_is_valid_and_parses_on_the_python_side():
    request = load_fixture("request_sample.json")
    assert contract.validate_request(request) == []
    assert request["schema"] == contract.REQUEST_SCHEMA
    assert request["page"] == 17


def test_result_fixture_maps_to_a_job_result():
    result = contract.parse_result(load_fixture("result_sample.json"))
    assert result.ok
    assert result.job_id == "manual_p017"
    assert result.objects_copied == 241
    assert result.stat("safe_groups_ungrouped") == 19
    assert result.stat("crop_objects_deleted") == 8
    assert result.stat("crop_perimeters_deleted") + result.stat("short_crop_marks_deleted") == 8


def test_build_request_round_trips_through_json():
    request = contract.build_request(
        run_id="r1",
        job_id="manual_p001",
        pdf="C:/JOB/PDF/manual.pdf",
        page=1,
        template="C:/JOB/TEMPLATE/MASTER_AI_TEMPLATE.ai",
        output="C:/JOB/AI_OUT/manual__001.ai",
    )
    assert contract.validate_request(request) == []
    assert json.loads(json.dumps(request))["cleanup"]["ungroupPasses"] == 40


def test_validate_request_reports_every_missing_field():
    problems = contract.validate_request({})
    assert any("job_id" in problem for problem in problems)
    assert any("schema" in problem for problem in problems)
    assert any("page" in problem for problem in problems)


def test_validate_request_rejects_bad_values():
    request = contract.build_request(
        run_id="r1",
        job_id="a_p001",
        pdf="p.pdf",
        page=0,
        template="t.ai",
        output="o.ai",
        template_mode="nonsense",
    )
    problems = contract.validate_request(request)
    assert any("page" in problem for problem in problems)
    assert any("template_mode" in problem for problem in problems)


def test_result_matching_requires_both_job_id_and_run_id():
    data = {"job_id": "a_p001", "run_id": "r1"}
    assert contract.result_matches(data, "a_p001", "r1")
    assert not contract.result_matches(data, "a_p001", "other")
    assert not contract.result_matches(data, "other", "r1")
    assert not contract.result_matches(None, "a_p001", "r1")


def test_parse_result_tolerates_missing_and_broken_fields():
    assert contract.parse_result(None).failed
    result = contract.parse_result({"status": "weird", "page": "x", "stats": "not a dict"})
    assert result.failed
    assert result.page == 0
    assert result.stat("crop_objects_deleted") == 0
    assert result.error_type == ""

    partial = contract.parse_result({"status": "ok", "stats": {"safe_groups_ungrouped": "12"}})
    assert partial.ok
    assert partial.stat("safe_groups_ungrouped") == 12


def test_summarise_results_counts_and_sums():
    results = [
        contract.parse_result({"status": "OK", "objects_copied": 10, "stats": {"crop_objects_deleted": 3}}),
        contract.parse_result({"status": "SKIP"}),
        contract.parse_result({"status": "ERROR", "message": "boom"}),
        contract.parse_result({"status": "OK", "objects_copied": 5, "stats": {"crop_objects_deleted": 2}}),
    ]
    summary = contract.summarise_results(results)
    assert summary["total"] == 4
    assert summary["ok"] == 2
    assert summary["skipped"] == 1
    assert summary["error"] == 1
    assert summary["objects_copied"] == 15
    assert summary["stats"]["crop_objects_deleted"] == 5


@pytest.mark.parametrize("key", contract.STAT_KEYS)
def test_every_declared_stat_key_is_accepted(key):
    result = contract.parse_result({"status": "OK", "stats": {key: 7}})
    assert result.stat(key) == 7
