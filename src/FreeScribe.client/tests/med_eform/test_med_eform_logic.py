"""
Layer 1: decision and formatting logic of the medication eForm auto-fill (no LLM, no Oscar).

Covers when the medication form opens, the fallbacks when the model misbehaves, how the
model's output is cleaned, and the exact prescription-body text that gets written.
"""

import json

import pytest

from utils import med_eform
from utils.rx_med_options import RX_MED_OPTIONS

PLAN = (
    "Start metoprolol 25 mg BID. Increase furosemide to 80 mg daily. "
    "Stop amlodipine. Repeat CBC and renal function in 2 weeks."
)


def reply(medication, labs=False):
    return json.dumps({"medication": medication, "labs": labs})


# --- when the medication form opens -------------------------------------------------------

def test_changes_open_form_with_prefill(fake_llm):
    llm = fake_llm(reply([
        {"action": "start", "name": "Metoprolol", "text": "Metoprolol 25 mg BID"},
        {"action": "increase", "name": "Furosemide", "text": "Furosemide 80 mg daily"},
        {"action": "stop", "name": "Amlodipine", "text": ""},
    ], labs=True))
    result = med_eform.analyze_plan_for_eforms(PLAN, llm)
    assert result["medication"]["open"] is True
    assert [c["action"] for c in result["medication"]["changes"]] == ["start", "increase", "stop"]
    assert result["labs"] is True


def test_no_changes_does_not_open(fake_llm):
    result = med_eform.analyze_plan_for_eforms("Continue current medications.", fake_llm(reply([])))
    assert result == {"medication": {"open": False, "changes": []}, "labs": False, "lab_period": None, "lab_checkboxes": None}


@pytest.mark.parametrize("scope", ["", "   ", None])
def test_empty_plan_opens_nothing_and_skips_llm(fake_llm, scope):
    llm = fake_llm(reply([{"action": "start", "name": "X", "text": "X 1 mg daily"}]))
    result = med_eform.analyze_plan_for_eforms(scope, llm)
    assert result == {"medication": {"open": False, "changes": []}, "labs": False, "lab_period": None, "lab_checkboxes": None}
    assert llm.prompts == []


def test_unmappable_change_still_opens_form_unfilled(fake_llm):
    # The model saw a change but used an action we cannot render: open the form, fill nothing.
    llm = fake_llm(reply([{"action": "switch", "name": "Amlodipine", "text": "Nifedipine 30 mg XL daily"}]))
    result = med_eform.analyze_plan_for_eforms(PLAN, llm)
    assert result["medication"] == {"open": True, "changes": []}


# --- fallbacks -----------------------------------------------------------------------------

@pytest.mark.parametrize("bad_reply", [
    RuntimeError("timeout"),
    "Sorry, I cannot help with that.",
    '{"medication": [unquoted]}',
    '["not", "an", "object"]',
])
def test_bad_llm_output_falls_back_to_keywords(fake_llm, bad_reply):
    result = med_eform.analyze_plan_for_eforms(PLAN, fake_llm(bad_reply))
    # Keywords see "start"/"stop" and "repeat CBC": both forms open, nothing pre-filled.
    assert result == {"medication": {"open": True, "changes": []}, "labs": True, "lab_period": None, "lab_checkboxes": None}


def test_python_style_booleans_are_accepted(fake_llm):
    llm = fake_llm('{"medication": [{"action": "start", "name": "Metoprolol", '
                   '"text": "Metoprolol 25 mg BID"}], "labs": True}')
    result = med_eform.analyze_plan_for_eforms(PLAN, llm)
    assert result["labs"] is True
    # Drug names keep their case (the reply is not lowercased as a whole).
    assert result["medication"]["changes"][0]["text"] == "Metoprolol 25 mg BID"


def test_json_wrapped_in_prose_or_code_fence(fake_llm):
    llm = fake_llm("Here you go:\n```json\n" + reply([], labs=True) + "\n```")
    assert med_eform.analyze_plan_for_eforms(PLAN, llm) == {
        "medication": {"open": False, "changes": []}, "labs": True, "lab_period": None, "lab_checkboxes": None}


@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False), ("true", True), ("false", False), ("False", False),
    ("yes", True), ("no", False), (1, True), (0, False), (None, False),
])
def test_as_flag(value, expected):
    assert med_eform.as_flag(value) is expected


def test_keyword_mode_never_calls_llm(fake_llm):
    llm = fake_llm(RuntimeError("should not be called"))
    result = med_eform.analyze_plan_for_eforms(PLAN, llm, mode="keyword")
    assert result == {"medication": {"open": True, "changes": []}, "labs": True, "lab_period": None, "lab_checkboxes": None}
    assert llm.prompts == []


@pytest.mark.parametrize("plan,med,labs", [
    ("Start bisoprolol 2.5 mg daily.", True, False),
    ("Continue all medications. Follow up in 6 months.", False, False),
    ("Repeat bloodwork including potassium in 1 week.", False, True),
    ("Echo in 3 months.", False, False),
])
def test_keyword_flags(plan, med, labs):
    assert med_eform.keyword_flags(plan) == {"medication": med, "labs": labs}


def test_keyword_flags_known_false_positive():
    # Documents the keyword limitation the LLM mode exists to fix.
    assert med_eform.keyword_flags("Start a stress test.")["medication"] is True


# --- cleaning the model output ---------------------------------------------------------------

@pytest.mark.parametrize("action,expected", [
    ("start", "start"), ("Add", "start"), ("initiate", "start"),
    ("increase", "increase"), ("uptitrate", "increase"),
    ("decrease", "decrease"), ("reduce", "decrease"),
    ("stop", "stop"), ("Discontinue", "stop"), ("hold", "stop"),
    # past tense / other forms, as echoed from a PLAN written like "I increased ..."
    ("increased", "increase"), ("Increasing", "increase"), ("started", "start"),
    ("added", "start"), ("initiated", "start"), ("decreased", "decrease"), ("reduced", "decrease"),
    ("stopped", "stop"), ("discontinued", "stop"), ("held", "stop"),
])
def test_action_synonyms(action, expected):
    changes = med_eform.clean_med_changes([{"action": action, "name": "Drug", "text": "Drug 5 mg daily"}])
    assert changes[0]["action"] == expected


@pytest.mark.parametrize("item", [
    {"action": "start", "name": "", "text": "X 5 mg daily"},       # no name
    {"action": "start", "name": "X", "text": ""},                  # start without a line
    {"action": "increase", "name": "X"},                           # increase without a line
    {"action": "switch", "name": "X", "text": "Y 5 mg daily"},     # unknown action
    "Start X 5 mg daily",                                          # not an object
])
def test_malformed_entries_are_dropped(item):
    assert med_eform.clean_med_changes([item]) == []


def test_stop_needs_no_text_and_trailing_commas_are_trimmed():
    changes = med_eform.clean_med_changes([
        {"action": "stop", "name": "Amlodipine"},
        {"action": "start", "name": "Apixaban", "text": "Apixaban 5 mg BID, LU code 448, "},
    ])
    assert changes == [
        {"action": "stop", "name": "Amlodipine", "text": ""},
        {"action": "start", "name": "Apixaban", "text": "Apixaban 5 mg BID, LU code 448"},
    ]


def test_non_list_medication_is_ignored():
    assert med_eform.clean_med_changes({"action": "start"}) == []
    assert med_eform.parse_med_response('{"medication": "none", "labs": false}')["open"] is False


# --- prescription-body text ------------------------------------------------------------------

def test_format_rx_lines():
    # New meds as the regimen (form's drug menu), dose changes as "Increase/Decrease X to ..."
    # (form's increase/decrease checkboxes), "Stop X" for stops, each followed by ", ".
    text = med_eform.format_rx_lines([
        {"action": "start", "name": "Metoprolol", "text": "Metoprolol 25 mg BID"},
        {"action": "increase", "name": "Furosemide", "text": "Furosemide 80 mg daily"},
        {"action": "decrease", "name": "Ramipril", "text": "Ramipril 2.5 mg daily"},
        {"action": "stop", "name": "Amlodipine", "text": ""},
    ])
    assert text == ("Metoprolol 25 mg BID, Increase Furosemide to 80 mg daily, "
                    "Decrease Ramipril to 2.5 mg daily, Stop Amlodipine, ")


def test_format_rx_lines_keeps_lu_codes_with_the_forms_separator():
    # The form's med_update strips "LU code 448, " - with the comma and space - so keep that shape.
    text = med_eform.format_rx_lines([
        {"action": "start", "name": "Apixaban", "text": "Apixaban 5 mg BID, LU code 448"}])
    assert text == "Apixaban 5 mg BID, LU code 448, "


def test_format_rx_lines_brand_generic_mismatch_uses_the_line():
    text = med_eform.format_rx_lines([
        {"action": "decrease", "name": "Lasix", "text": "Furosemide 20 mg daily"}])
    assert text == "Decrease Furosemide to 20 mg daily, "


@pytest.mark.parametrize("change,expected", [
    ({"action": "increase", "name": "Diltiazem", "text": "Diltiazem CD 240 mg daily"},
     "Increase Diltiazem CD to 240 mg daily"),
    ({"action": "increase", "name": "sacubitril/valsartan", "text": "sacubitril/valsartan 97/103 mg BID, LU 497"},
     "Increase sacubitril/valsartan to 97/103 mg BID, LU 497"),
    ({"action": "decrease", "name": "Apixaban", "text": "Apixaban 2.5 mg BID, LU code 448"},
     "Decrease Apixaban to 2.5 mg BID, LU code 448"),
    ({"action": "increase", "name": "Warfarin", "text": "Warfarin"}, "Increase Warfarin"),
])
def test_dose_change_wording(change, expected):
    assert med_eform.rx_entries([change]) == [expected]


def test_format_rx_lines_empty():
    assert med_eform.format_rx_lines([]) == ""


def test_rx_entries():
    assert med_eform.rx_entries([
        {"action": "start", "name": "Apixaban", "text": "Apixaban 5 mg BID, LU code 448"},
        {"action": "stop", "name": "Aspirin", "text": ""},
    ]) == ["Apixaban 5 mg BID, LU code 448", "Stop Aspirin"]


# --- prompt ----------------------------------------------------------------------------------

def test_prompt_contains_plan_and_standard_lines():
    prompt = med_eform.build_med_prompt(PLAN)
    assert PLAN in prompt
    for option in RX_MED_OPTIONS:
        assert f"- {option}" in prompt


def test_standard_lines_are_unique_and_clean():
    assert len(RX_MED_OPTIONS) == len(set(RX_MED_OPTIONS))
    for option in RX_MED_OPTIONS:
        assert option == option.strip() and not option.endswith(",")


# --- PLAN extraction (utils/read_files.extract_plan_section) ---------------------------------

def test_extract_plan_section_takes_text_after_plan(read_files):
    note = "HPI: on amlodipine.\nASSESSMENT: HTN.\nPLAN: Start metoprolol 25 mg BID."
    assert read_files.extract_plan_section(note).strip() == ": Start metoprolol 25 mg BID."


def test_extract_plan_section_is_case_sensitive(read_files):
    # Documents current behaviour: a "Plan:" heading is not found, so the caller falls back to
    # the whole consult (HPI meds included) when deciding about the medication form.
    assert read_files.extract_plan_section("HPI: x\nPlan: start metoprolol") == ""


def test_past_tense_plan_from_consult_prompt_is_filled(fake_llm):
    # Real case (2026-10-09): the consult2 prompt wrote the PLAN in the past tense and the
    # form opened empty. The model echoing "increased" must still produce a prescription line.
    plan = ("I increased the furosemide dosage to 80 mg daily. I advised the patient to continue "
            "ramipril 5 mg daily. I ordered a recheck of electrolytes and creatinine in one week.")
    llm = fake_llm(reply([{"action": "increased", "name": "Furosemide", "text": "Furosemide 80 mg daily"}],
                         labs=True))
    result = med_eform.analyze_plan_for_eforms(plan, llm)
    assert result["medication"]["changes"] == [
        {"action": "increase", "name": "Furosemide", "text": "Furosemide 80 mg daily"}]
    assert med_eform.format_rx_lines(result["medication"]["changes"]) == "Increase Furosemide to 80 mg daily, "
    assert result["labs"] is True


# --- recommendations are not prescriptions -----------------------------------------------------

def test_recommendation_only_does_not_open_form(fake_llm):
    plan = "I recommend starting metoprolol 25 mg BID; consider increasing ramipril at follow-up."
    llm = fake_llm(reply([
        {"action": "start", "name": "Metoprolol", "text": "Metoprolol 25 mg BID", "ordered": False},
        {"action": "increase", "name": "Ramipril", "text": "Ramipril 10 mg daily", "ordered": "false"},
    ]))
    assert med_eform.analyze_plan_for_eforms(plan, llm)["medication"] == {"open": False, "changes": []}


def test_only_the_prescribed_change_is_filled(fake_llm):
    plan = "Increase furosemide to 80 mg daily. I would recommend starting an SGLT2 inhibitor later."
    llm = fake_llm(reply([
        {"action": "increase", "name": "Furosemide", "text": "Furosemide 80 mg daily", "ordered": True},
        {"action": "start", "name": "Jardiance", "text": "Jardiance 10 mg daily", "ordered": False},
    ]))
    result = med_eform.analyze_plan_for_eforms(plan, llm)["medication"]
    assert result["open"] is True
    assert [c["name"] for c in result["changes"]] == ["Furosemide"]


def test_missing_ordered_field_counts_as_prescribed(fake_llm):
    llm = fake_llm(reply([{"action": "start", "name": "Metoprolol", "text": "Metoprolol 25 mg BID"}]))
    assert med_eform.analyze_plan_for_eforms("Start metoprolol 25 mg BID.", llm)["medication"]["open"] is True


def test_prompt_asks_for_ordered_flag():
    prompt = med_eform.build_med_prompt("x")
    assert '"ordered"' in prompt and "recommend" in prompt


@pytest.mark.parametrize("plan,med", [
    ("I recommend taking metoprolol 25 mg BID.", False),
    ("I would suggest starting apixaban 5 mg BID.", False),
    ("Consider increasing furosemide to 80 mg daily.", False),
    ("If blood pressure remains high, start amlodipine 5 mg daily.", False),
    ("Defer to family doctor to stop the aspirin.", False),
    ("Start metoprolol 25 mg BID.", True),
    ("I increased the furosemide dosage to 80 mg daily.", True),
    ("I recommend a low-salt diet. Start metoprolol 25 mg BID.", True),   # one real change
])
def test_keyword_fallback_ignores_recommendations(plan, med):
    assert med_eform.keyword_flags(plan)["medication"] is med


# --- lab due period ------------------------------------------------------------------------------

def test_lab_period_is_read_from_the_reply(fake_llm):
    llm = fake_llm(json.dumps({"medication": [], "labs": {"required": True, "period": "2m"}}))
    result = med_eform.analyze_plan_for_eforms("Repeat lipids in 2 months.", llm)
    assert result["labs"] is True and result["lab_period"] == "2m"


def test_lab_period_is_none_when_labs_not_required(fake_llm):
    llm = fake_llm(json.dumps({"medication": [], "labs": {"required": False, "period": "2w"}}))
    result = med_eform.analyze_plan_for_eforms("Echo in 3 months.", llm)
    assert result["labs"] is False and result["lab_period"] is None


def test_old_boolean_labs_reply_still_works(fake_llm):
    result = med_eform.analyze_plan_for_eforms("Repeat CBC.", fake_llm(reply([], labs=True)))
    assert result["labs"] is True and result["lab_period"] is None


@pytest.mark.parametrize("scope,mode,llm_reply", [
    ("", "llm", None),                                        # empty plan
    ("Repeat CBC and potassium.", "keyword", None),           # keyword mode
    ("Repeat CBC and potassium.", "llm", RuntimeError("x")),  # LLM failed -> keyword fallback
])
def test_every_branch_returns_lab_period(fake_llm, scope, mode, llm_reply):
    # client._open_relevant_eforms reads decisions["lab_period"]; a missing key used to raise
    # KeyError on the fallback paths, so neither eForm opened.
    result = med_eform.analyze_plan_for_eforms(scope, fake_llm(llm_reply), mode=mode)
    assert "lab_period" in result and result["lab_period"] is None
