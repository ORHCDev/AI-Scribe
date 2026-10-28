"""
Logic of the referral letter -> requisition eForm (716) auto-fill (no LLM, no Oscar).
"""

import json
from datetime import date
from pathlib import Path

import pytest

from utils import referral_requisition as rr

FORM_JSON = json.loads((Path(__file__).resolve().parents[1] / "utils" / "referral_form.json").read_text())


def _parse(answer: dict):
    return rr.parse_referral_response(json.dumps(answer), FORM_JSON)


def _value(result, field_id):
    return next(f["value"] for f in result["fields"] if f["id"] == field_id)


def test_matching_option_uses_the_dropdown_value():
    result = _parse({"tests": {"ecg": {"indication": "Chest pain of suspected cardiac origin."}}})
    assert result["tests"] == ["ecg"]
    assert _value(result, "ecg-input") == "Cor Health Ind. # 1.1. Chest pain of suspected cardiac origin."
    assert result["indications"]["ecg"][1] is True


def test_option_match_ignores_case_punctuation_and_small_typos():
    value, from_dropdown = rr.match_indication("chest pain of suspected cardiac orgin",
                                               rr.indication_options(FORM_JSON)["ecg"])
    assert from_dropdown and value.startswith("Cor Health Ind. # 1.1")


def test_no_matching_option_writes_the_referral_wording():
    result = _parse({"tests": {"echo": {"indication": "family history of sarcoid"}}})
    assert _value(result, "echo-input") == "family history of sarcoid"
    assert result["indications"]["echo"] == ("family history of sarcoid", False)


def test_tests_follow_form_order_and_unknown_ids_are_ignored():
    result = _parse({"tests": {"echo": {}, "mri": {"indication": "x"}, "ecg": {}}})
    assert result["tests"] == ["ecg", "echo"]
    assert [f["id"] for f in result["fields"]] == ["ecg", "echo"]


def test_null_indication_ticks_the_test_without_text():
    result = _parse({"tests": {"ecg": {"indication": None}, "echo": {"indication": "null"}}})
    assert result["tests"] == ["ecg", "echo"]
    assert all(f["type"] == "check" for f in result["fields"])


def test_holter_duration_is_ticked_after_its_indication():
    result = _parse({"tests": {"holter": {"indication": "palpitation.  Cor Health Ind. # 2"}},
                     "holter_duration": "48h"})
    assert [f["id"] for f in result["fields"]] == ["holter", "holter-input", "48hr"]


def test_unknown_holter_duration_is_left_for_the_doctor():
    result = _parse({"tests": {"holter": {}}, "holter_duration": "1 week"})
    assert [f["id"] for f in result["fields"]] == ["holter"]


def test_contrast_only_when_marked():
    assert "contrastecho" in [f["id"] for f in _parse({"tests": {"echo": {"contrast": True}}})["fields"]]
    assert "contrastecho" not in [f["id"] for f in _parse({"tests": {"echo": {"contrast": "no"}}})["fields"]]


def test_consult_reason_goes_to_the_reason_box():
    result = _parse({"tests": {"consult": {"indication": "new onset SOBOE"}}})
    assert _value(result, rr.CONSULT_REASON_ID) == "new onset SOBOE"


def test_list_of_tests_and_fenced_json_are_accepted():
    raw = "```json\n" + json.dumps({"tests": ["ecg"], "explanation": "ECG requested"}) + "\n```"
    result = rr.parse_referral_response(raw, FORM_JSON)
    assert result["tests"] == ["ecg"] and result["explanation"] == "ECG requested"


def test_no_tests_gives_no_fields():
    assert _parse({"tests": {}})["fields"] == []


def test_bad_response_raises():
    with pytest.raises(ValueError):
        rr.parse_referral_response("I could not read the referral.", FORM_JSON)


def test_prompt_lists_tests_and_options():
    prompt = rr.build_referral_prompt("OCR TEXT", FORM_JSON)
    assert '"holter"' in prompt and "Chest pain of suspected cardiac origin." in prompt
    assert prompt.rstrip().endswith("OCR TEXT")


def test_queries_reject_unsafe_input():
    with pytest.raises(ValueError):
        rr.new_referral_documents_query("2026-10-28'; DROP TABLE x; --")
    with pytest.raises(ValueError):
        rr.requisition_exists_query("1 OR 1=1")
    assert "fid IN (716, 698)" in rr.requisition_exists_query(42)


D = date(2026, 10, 28)


@pytest.mark.parametrize("last_checked, expected", [
    # Checked yesterday morning: yesterday's uploads now.
    (date(2026, 10, 26), (date(2026, 10, 27), date(2026, 10, 27))),
    # Already checked this morning (or AI-Scribe restarted): nothing.
    (date(2026, 10, 27), None),
    # Long weekend: every missed day, at most 7 back.
    (date(2026, 10, 23), (date(2026, 10, 24), date(2026, 10, 27))),
    (date(2026, 9, 1), (date(2026, 10, 21), date(2026, 10, 27))),
    # First run ever: only yesterday.
    (None, (date(2026, 10, 27), date(2026, 10, 27))),
])
def test_days_to_check(last_checked, expected):
    assert rr.days_to_check(last_checked, D) == expected


def test_patient_provider_query_rejects_unsafe_input():
    assert "demographic_no = 42" in rr.patient_provider_query("42")
    with pytest.raises(ValueError):
        rr.patient_provider_query("1 OR 1=1")


def test_query_has_upper_bound():
    q = rr.new_referral_documents_query("2026-10-27 00:00:00", "2026-10-28 00:00:00")
    assert "d.updatedatetime >= '2026-10-27 00:00:00'" in q and "d.updatedatetime < '2026-10-28 00:00:00'" in q
    with pytest.raises(ValueError):
        rr.new_referral_documents_query("2026-10-27 00:00:00", "tomorrow")
