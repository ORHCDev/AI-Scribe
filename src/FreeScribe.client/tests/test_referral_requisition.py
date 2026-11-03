"""
Logic of the referral letter -> requisition eForm (716) auto-fill (no LLM, no Oscar).
"""

import json
from pathlib import Path

import pytest

from utils import referral_requisition as rr

FORM_JSON = json.loads((Path(__file__).resolve().parents[1] / "utils" / "referral_form.json").read_text())


def _parse(answer: dict, reason: str):
    return rr.parse_referral_response(json.dumps(answer), FORM_JSON, rr.tests_from_reason(reason))


def _value(result, field_id):
    return next(f["value"] for f in result["fields"] if f["id"] == field_id)


@pytest.mark.parametrize("reason,tests", [
    ("STRESS ECHO - DR. MAHESH", ["stecho"]),
    ("ECHO-ECG - DR. RAGHAVAN", ["ecg", "echo"]),
    ("F/UP- ECG - IN PERSON - DR. MAHESH - waiting for DR", ["ecg"]),
    ("ECHO- DR. MAHESH", ["echo"]),
    ("GXT / treadmill", ["est"]),
    ("Exercise stress test + 48 hr Holter", ["est", "holter"]),
    ("Consult - DR. ZEMAN", ["consult"]),
    ("NP IN PERSON", []),
    ("Phone f/u", []),
])
def test_tests_come_only_from_the_appointment_reason(reason, tests):
    assert rr.tests_from_reason(reason)["tests"] == tests


def test_reason_gives_contrast_and_holter_duration():
    assert rr.tests_from_reason("CONTRAST STRESS ECHO")["contrast"] is True
    assert rr.tests_from_reason("STRESS ECHO")["contrast"] is False
    assert rr.tests_from_reason("HOLTER 14 day")["holter_duration"] == "2w"
    assert rr.tests_from_reason("ECG 48 hr")["holter_duration"] is None


def test_llm_cannot_add_tests_the_appointment_does_not_name():
    result = _parse({"indications": {"consult": "SOB", "echo": "SOB", "stecho": "fatigue/ SOB"}},
                    "STRESS ECHO - DR. MAHESH")
    assert result["tests"] == ["stecho"]
    assert [f["id"] for f in result["fields"]] == ["stecho", "stecho-input"]


def test_matching_option_uses_the_dropdown_value():
    result = _parse({"indications": {"ecg": "Chest pain of suspected cardiac origin."}}, "ECG")
    assert _value(result, "ecg-input") == "Cor Health Ind. # 1.1. Chest pain of suspected cardiac origin."
    assert result["indications"]["ecg"][1] is True


def test_option_match_ignores_case_punctuation_and_small_typos():
    value, from_dropdown = rr.match_indication("chest pain of suspected cardiac orgin",
                                               rr.indication_options(FORM_JSON)["ecg"])
    assert from_dropdown and value.startswith("Cor Health Ind. # 1.1")


def test_no_matching_option_writes_the_document_wording():
    result = _parse({"indications": {"echo": "family history of sarcoid"}}, "ECHO")
    assert result["indications"]["echo"] == ("family history of sarcoid", False)


def test_old_answer_format_is_still_read():
    result = _parse({"indications": {"echo": {"indication": "family history of sarcoid"}}}, "ECHO")
    assert _value(result, "echo-input") == "family history of sarcoid"


def test_null_indication_ticks_the_test_without_text():
    result = _parse({"indications": {"ecg": None, "echo": "null"}}, "ECHO-ECG")
    assert result["tests"] == ["ecg", "echo"]
    assert all(f["type"] == "check" for f in result["fields"])


def test_holter_duration_from_the_appointment_wins_and_comes_after_the_indication():
    result = _parse({"indications": {"holter": "palpitations"}, "holter_duration": "24h"}, "48 hr HOLTER")
    assert [f["id"] for f in result["fields"]] == ["holter", "holter-input", "48hr"]


def test_holter_duration_falls_back_to_the_document():
    result = _parse({"indications": {}, "holter_duration": "72h"}, "HOLTER")
    assert [f["id"] for f in result["fields"]] == ["holter", "72hr"]


def test_contrast_comes_from_the_appointment():
    assert "contrast" in [f["id"] for f in _parse({}, "CONTRAST STRESS ECHO")["fields"]]
    assert "contrastecho" not in [f["id"] for f in _parse({}, "ECHO")["fields"]]


def test_consult_reason_goes_to_the_reason_box():
    result = _parse({"indications": {"consult": "new onset SOBOE"}}, "CONSULT")
    assert _value(result, rr.CONSULT_REASON_ID) == "new onset SOBOE"


def test_fenced_json_is_accepted():
    raw = "```json\n" + json.dumps({"indications": {}, "explanation": "SOB"}) + "\n```"
    result = rr.parse_referral_response(raw, FORM_JSON, rr.tests_from_reason("ECG"))
    assert result["tests"] == ["ecg"] and result["explanation"] == "SOB"


def test_python_style_answer_is_accepted():
    raw = "{'indications': {'ecg': 'family history of sarcoid'}, 'holter_duration': None, 'explanation': 'x'}"
    result = rr.parse_referral_response(raw, FORM_JSON, rr.tests_from_reason("ECG"))
    assert result["indications"]["ecg"] == ("family history of sarcoid", False)


def test_unescaped_quote_in_a_value_raises_a_value_error():
    raw = '{"indications": {"ecg": "pt says "dizzy" spells"}, "explanation": "x"}'
    with pytest.raises(ValueError, match="not valid JSON"):
        rr.parse_referral_response(raw, FORM_JSON, rr.tests_from_reason("ECG"))


def test_bad_response_raises():
    with pytest.raises(ValueError):
        rr.parse_referral_response("I could not read the referral.", FORM_JSON, rr.tests_from_reason("ECG"))


def test_prompt_lists_only_the_booked_tests_and_their_options():
    prompt = rr.build_referral_prompt("OCR TEXT", ["ecg"], FORM_JSON)
    assert '"ecg"' in prompt and "Chest pain of suspected cardiac origin." in prompt
    assert '"holter"' not in prompt
    assert prompt.rstrip().endswith("OCR TEXT")


def test_encounter_reason_comes_from_the_current_note_header():
    note = "[29-Oct-2026 .: F/UP- ECG - IN PERSON - waiting for DR]\n\nsome text"
    assert rr.encounter_reason(["", note]) == "F/UP- ECG - IN PERSON - waiting for DR"


def test_encounter_reason_joins_a_wrapped_header():
    assert rr.encounter_reason(["[29-Oct-2026\n.: F/UP- ECG -\nIN PERSON]"]) == "F/UP- ECG - IN PERSON"


def test_encounter_reason_is_empty_without_a_header_or_reason():
    assert rr.encounter_reason([]) == ""
    assert rr.encounter_reason(["free text", "[29-Oct-2026 .: ]"]) == ""


def test_referral_query_checks_type_and_description_of_this_patient():
    query = rr.latest_referral_query("123")
    assert "cd.module_id = 123" in query
    assert "d.doctype" in query and "d.docdesc" in query and "LIMIT 1" in query


def test_referral_query_rejects_a_bad_patient_number():
    with pytest.raises(ValueError):
        rr.latest_referral_query("1 OR 1=1")


def test_describe_document_shows_type_description_and_date():
    row = {"document_no": 1, "doctype": "lr", "docdesc": " Referral letter ", "observationdate": "2026-10-15"}
    assert rr.describe_document(row) == "lr - Referral letter (2026-10-15)"


def test_describe_document_without_details():
    assert rr.describe_document({"doctype": None, "docdesc": "", "observationdate": None}) == "Document (no date)"


def test_patient_documents_query_lists_all_types_of_this_patient():
    query = rr.patient_documents_query("123")
    assert "cd.module_id = 123" in query and "referral" not in query and "LIMIT 15" in query


@pytest.mark.parametrize("reason,expected", [
    ("HOLTER 2 DAYS", "48h"), ("HOLTER 2 WEEKS", "2w"), ("HOLTER 1 day", "24h"), ("HOLTER", None)])
def test_holter_days_are_not_read_as_weeks(reason, expected):
    assert rr.tests_from_reason(reason)["holter_duration"] == expected


def test_document_holter_duration_in_words_is_read():
    result = _parse({"indications": {}, "holter_duration": "2 days"}, "HOLTER")
    assert [f["id"] for f in result["fields"]] == ["holter", "48hr"]
