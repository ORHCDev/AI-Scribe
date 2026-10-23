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


_CORE_KEYS = ("medication", "labs", "lab_period", "lab_checkboxes")


def core(result):
    """The medication / lab part of analyze_plan_for_eforms' result (requisition fields excluded)."""
    return {k: result[k] for k in _CORE_KEYS}


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
    assert core(result) == {"medication": {"open": False, "changes": []}, "labs": False, "lab_period": None, "lab_checkboxes": None}


@pytest.mark.parametrize("scope", ["", "   ", None])
def test_empty_plan_opens_nothing_and_skips_llm(fake_llm, scope):
    llm = fake_llm(reply([{"action": "start", "name": "X", "text": "X 1 mg daily"}]))
    result = med_eform.analyze_plan_for_eforms(scope, llm)
    assert core(result) == {"medication": {"open": False, "changes": []}, "labs": False, "lab_period": None, "lab_checkboxes": None}
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
    assert core(result) == {"medication": {"open": True, "changes": []}, "labs": True, "lab_period": None, "lab_checkboxes": None}


def test_python_style_booleans_are_accepted(fake_llm):
    llm = fake_llm('{"medication": [{"action": "start", "name": "Metoprolol", '
                   '"text": "Metoprolol 25 mg BID"}], "labs": True}')
    result = med_eform.analyze_plan_for_eforms(PLAN, llm)
    assert result["labs"] is True
    # Drug names keep their case (the reply is not lowercased as a whole).
    assert result["medication"]["changes"][0]["text"] == "Metoprolol 25 mg BID"


def test_json_wrapped_in_prose_or_code_fence(fake_llm):
    llm = fake_llm("Here you go:\n```json\n" + reply([], labs=True) + "\n```")
    assert core(med_eform.analyze_plan_for_eforms(PLAN, llm)) == {
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
    assert core(result) == {"medication": {"open": True, "changes": []}, "labs": True, "lab_period": None, "lab_checkboxes": None}
    assert llm.prompts == []


@pytest.mark.parametrize("plan,med,labs", [
    ("Start bisoprolol 2.5 mg daily.", True, False),
    ("Continue all medications. Follow up in 6 months.", False, False),
    ("Repeat bloodwork including potassium in 1 week.", False, True),
    ("Echo in 3 months.", False, False),
])
def test_keyword_flags(plan, med, labs):
    assert med_eform.keyword_flags(plan) == {"medication": med, "labs": labs, "requisition": False}


@pytest.mark.parametrize("plan", [
    "Start a stress test.",
    "Stop smoking counselling provided.",
    "Increase physical activity to 150 minutes per week.",
    "I renewed his prescriptions.",
    "I asked whether he needed any renewals.",
])
def test_keyword_fallback_needs_a_medication_in_the_sentence(plan):
    # A change verb alone (stress test, smoking, activity) is not a medication change.
    assert med_eform.keyword_flags(plan)["medication"] is False


@pytest.mark.parametrize("plan", [
    "Start bisoprolol 2.5 mg daily.",
    "Increase the Lasix.",
    "Stop amlodipine.",
    "Increase the dose of his beta blocker.",
    "Started apixaban 5 mg BID today.",
])
def test_keyword_fallback_still_sees_real_medication_changes(plan):
    assert med_eform.keyword_flags(plan)["medication"] is True


def test_prompt_says_renewals_and_history_are_not_changes():
    prompt = med_eform.build_med_prompt("x")
    assert "Renewing or refilling a current medication at the same dose does NOT count" in prompt
    assert "Changes the patient made on their own, or changes from before this visit" in prompt


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

@pytest.mark.parametrize("note,expected", [
    # PLAN in capitals, on its own line or not
    ("HPI: on amlodipine.\nASSESSMENT: HTN.\nPLAN:\nStart metoprolol 25 mg BID.", "Start metoprolol 25 mg BID."),
    ("HPI: x\nPLAN: Start metoprolol 25 mg BID.", "Start metoprolol 25 mg BID."),
    ("HPI: x. ASSESSMENT: AF. PLAN: Start apixaban 5 mg BID.", "Start apixaban 5 mg BID."),
    ("HPI: x\nPLAN\nI increased the furosemide to 80 mg daily.", "I increased the furosemide to 80 mg daily."),
    # last PLAN wins (an earlier one is part of the history)
    ("HPI: previous PLAN: start ramipril. Doing well.\nPLAN:\nContinue meds.", "Continue meds."),
    # words that only contain PLAN are not the heading
    ("EXPLANATION given. PLANNED follow-up.\nPLAN: repeat echo in 1 year.", "repeat echo in 1 year."),
    # fallback when the note is not written in capitals
    ("HPI: x\nPlan: start metoprolol", "start metoprolol"),
    ("The patient is stable. Plan: repeat echo in 1 year.", "repeat echo in 1 year."),
])
def test_extract_plan_section_finds_plan(read_files, note, expected):
    assert read_files.extract_plan_section(note) == expected


@pytest.mark.parametrize("note", [
    "HPI: on ramipril 5 mg daily. ASSESSMENT: stable. The plan is to see him again next year.",
    "HPI: started metoprolol last year; recent CBC normal.",
    "",
    None,
])
def test_extract_plan_section_returns_empty_without_a_plan(read_files, note):
    # "the plan is ..." without a colon is not a heading; no PLAN -> "" (eForms are then not opened)
    assert read_files.extract_plan_section(note) == ""


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


# --- requisition field missing from the reply --------------------------------------------------

@pytest.mark.parametrize("requisition", ["<missing>", None, False, "1y", ["echo"]])
def test_missing_or_bad_requisition_keeps_med_and_lab_results(fake_llm, requisition):
    # A reply without a usable "requisition" object used to raise in parse_med_response, so the
    # whole reply fell back to keywords and the medication / lab results were lost too.
    body = {"medication": [{"action": "start", "name": "Metoprolol", "text": "Metoprolol 25 mg BID"}],
            "labs": {"required": True, "period": "1w"}}
    if requisition != "<missing>":
        body["requisition"] = requisition
    parsed = med_eform.parse_med_response(json.dumps(body))
    assert parsed["open"] is True
    assert parsed["changes"][0]["text"] == "Metoprolol 25 mg BID"
    assert parsed["labs"] is True and parsed["lab_period"] == "1w"
    assert parsed["requisition"] is False
    assert parsed["requisition_diagnostics"] == []
    assert parsed["requisition_period"] is None and parsed["holter_period"] is None


def test_requisition_object_is_still_parsed():
    parsed = med_eform.parse_med_response(json.dumps({
        "medication": [], "labs": {"required": False, "period": None},
        "requisition": {"period": "1y", "period_reason": None, "ecg": True, "echo": True, "holter": None}}))
    assert parsed["requisition"] is True and parsed["requisition_period"] == "1y"
    assert parsed["requisition_diagnostics"] == ["ecg", "echo"]


# --- requisition: what gets ticked ----------------------------------------------------------------

def req(requisition, plan=None):
    return med_eform.requisition_from_response(requisition, plan)


def test_follow_up_period_without_any_test_does_not_open_the_form():
    # "See back in 1 year" alone used to open the requisition with nothing ticked.
    r = req({"period": "1y", "period_reason": None, "consult": False, "ecg": False, "holter": None})
    assert r["requisition"] is False and r["requisition_diagnostics"] == []


def test_tests_without_a_period_still_open_the_form():
    r = req({"period": None, "echo": True})
    assert r["requisition"] is True and r["requisition_diagnostics"] == ["echo"]
    assert r["requisition_period"] is None


def test_only_form_ids_are_kept_case_insensitively_in_form_order():
    r = req({"period": "1y", "Echo": True, "ECG": "true", "notes": "see plan", "reason": "x", "est": "false"})
    assert r["requisition_diagnostics"] == ["ecg", "echo"]


@pytest.mark.parametrize("holter,expected", [
    ("24h", "24h"), ("48 hours", "48h"), ("72hr", "72h"), ("3 days", "72h"), ("2 weeks", "2w"),
    ("14d", "2w"), ("2wk", "2w"), ("1 month", None), (None, None)])
def test_holter_period_is_normalized(holter, expected):
    assert med_eform.normalize_holter_period(holter) == expected


@pytest.mark.parametrize("holter", ["48h", "2 weeks", True, "unknown"])
def test_holter_always_comes_with_an_ecg(holter):
    r = req({"period": "1y", "holter": holter})
    assert r["requisition_diagnostics"] == ["ecg", "holter"]


def test_holter_period_none_when_not_a_form_option():
    r = req({"period": "1y", "holter": "1 month"})
    assert "holter" in r["requisition_diagnostics"] and r["holter_period"] is None


@pytest.mark.parametrize("plan", [
    "Arrange a stress test and echo. Follow up in 1 year.",
    "Treadmill test and echocardiogram before next visit.",
])
def test_stress_test_and_echo_are_est_plus_echo_not_stress_echo(plan):
    r = req({"period": "1y", "stecho": True, "contrast": True}, plan)
    assert r["requisition_diagnostics"] == ["echo", "est"]


def test_stress_test_alone_is_est():
    r = req({"period": "1y", "stecho": True}, "Book an exercise stress test.")
    assert r["requisition_diagnostics"] == ["est"]


@pytest.mark.parametrize("plan", ["Arrange a stress echo in 3 months.", "Stress-echocardiogram to assess ischemia."])
def test_stress_echo_kept_when_the_plan_says_so(plan):
    r = req({"period": "3m", "stecho": True, "contrast": True}, plan)
    assert r["requisition_diagnostics"] == ["stecho", "contrast"]


def test_contrast_options_need_their_base_test():
    r = req({"period": "1y", "contrastecho": True, "contrast": True, "ecg": True})
    assert r["requisition_diagnostics"] == ["ecg"]


def test_indications_kept_only_for_ticked_tests_with_an_indication_box():
    r = req({"period": "1y", "echo": True, "holter": "24h",
             "indications": {"Echo": " reassess LV function ", "holter": "palpitations", "est": "chest pain",
                             "consult": "x", "ecg": ""}})
    assert r["requisition_indications"] == {"echo": "reassess LV function", "holter": "palpitations"}


def test_parse_passes_the_plan_to_the_requisition_check():
    plan = "PLAN: stress test and echo in 1 year."
    parsed = med_eform.parse_med_response(json.dumps({
        "medication": [], "labs": {"required": False, "period": None},
        "requisition": {"period": "1y", "stecho": True}}), plan)
    assert parsed["requisition_diagnostics"] == ["echo", "est"]
    assert parsed["requisition_indications"] == {}


# --- lab checkbox call only picks boxes; it never opens the lab form by itself ------------------

class RoutedLLM:
    """First call (medication prompt) gets `med_reply`; the lab-checkbox prompt gets `lab_reply`."""

    def __init__(self, med_reply, lab_reply):
        self.med_reply, self.lab_reply, self.lab_calls = med_reply, lab_reply, 0

    def __call__(self, prompt):
        if "lab test checkboxes" in prompt:
            self.lab_calls += 1
            return self.lab_reply
        return self.med_reply


def test_lab_form_not_opened_when_first_call_says_no_labs():
    # e.g. "I reviewed his recent CBC, which was normal" - the checkbox call would pick CBC
    llm = RoutedLLM(json.dumps({"medication": [], "labs": {"required": False, "period": None}}),
                    '["CompleteBloodCount"]')
    result = med_eform.analyze_plan_for_eforms("I reviewed his recent CBC, which was normal.", llm)
    assert result["labs"] is False and result["lab_checkboxes"] is None
    assert llm.lab_calls == 0      # the checkbox call is skipped entirely


def test_checkboxes_used_when_labs_required():
    llm = RoutedLLM(json.dumps({"medication": [], "labs": {"required": True, "period": "1w"}}),
                    '["RenalFunction", "CompleteBloodCount"]')
    result = med_eform.analyze_plan_for_eforms("Repeat CBC and renal function in 1 week.", llm)
    assert result["labs"] is True and result["lab_period"] == "1w"
    assert result["lab_checkboxes"] == {"RenalFunction", "CompleteBloodCount"}
    assert llm.lab_calls == 1


def test_labs_required_but_no_box_picked_opens_blank_form():
    llm = RoutedLLM(json.dumps({"medication": [], "labs": {"required": True, "period": None}}), "[]")
    result = med_eform.analyze_plan_for_eforms("Bloodwork in 2 weeks.", llm)
    assert result["labs"] is True and result["lab_checkboxes"] is None


def test_prompts_require_requested_labs_not_mentions():
    from utils.lab_analysis import LAB_CHECKBOX_ANALYSIS_PROMPT as lab_prompt
    assert "Only include checkboxes for lab work the PLAN actually orders or requests" in lab_prompt
    assert "is mentioned)" not in lab_prompt and "simply mentions CHF" not in lab_prompt
    assert "Reviewing, discussing or reporting the results of previous" in med_eform.build_med_prompt("x")


# --- renewals mislabelled as starts by the model -----------------------------------------------

def _start(name, text, action="start"):
    return {"action": action, "name": name, "text": text, "ordered": True}


@pytest.mark.parametrize("plan,item,renewal", [
    ("I renewed his metoprolol 25 mg BID.", _start("Metoprolol", "Metoprolol 25 mg BID"), True),
    ("Prescriptions for ramipril and atorvastatin were renewed at the same dose.",
     _start("Ramipril", "Ramipril 5 mg daily"), True),
    ("Continue apixaban 5 mg BID; refill provided.", _start("Apixaban", "Apixaban 5 mg BID, LU code 448"), True),
    ("I renewed his medications and increased the furosemide to 80 mg daily.",
     _start("Furosemide", "Furosemide 80 mg daily", "increase"), False),
    ("Start metoprolol 25 mg BID. Renewed other meds.", _start("Metoprolol", "Metoprolol 25 mg BID"), False),
    ("Continue metoprolol but increase to 50 mg BID.", _start("Metoprolol", "Metoprolol 50 mg BID", "increase"), False),
    ("Stop amlodipine. Continue other medications.", _start("Amlodipine", "", "stop"), False),
    ("Renewed all medications.", _start("Bisoprolol", "Bisoprolol 5 mg daily"), False),   # drug not in PLAN: keep
])
def test_is_renewal_only(plan, item, renewal):
    assert med_eform.is_renewal_only(item, plan) is renewal


def test_renewal_mislabelled_as_start_does_not_open_med_form(fake_llm):
    plan = "I asked if he needed renewals and renewed his ramipril 5 mg daily. Continue all medications."
    llm = fake_llm(reply([_start("Ramipril", "Ramipril 5 mg daily")]))
    assert med_eform.analyze_plan_for_eforms(plan, llm)["medication"] == {"open": False, "changes": []}


def test_real_change_kept_next_to_renewals(fake_llm):
    plan = "Renewed his ramipril. Increase furosemide to 80 mg daily."
    llm = fake_llm(reply([_start("Ramipril", "Ramipril 5 mg daily"),
                          _start("Furosemide", "Furosemide 80 mg daily", "increase")]))
    result = med_eform.analyze_plan_for_eforms(plan, llm)["medication"]
    assert result["open"] is True
    assert [c["name"] for c in result["changes"]] == ["Furosemide"]


# --- requisition: only tests the PLAN asks to be done ----------------------------------------------

@pytest.mark.parametrize("test,plan", [
    ("ecg", "ECG today shows sinus rhythm. Continue current medications."),
    ("echo", "Echo last year showed EF 55%. Follow up in 1 year."),
    ("echo", "Previous echocardiogram was normal; no need to repeat."),
    ("holter", "Holter monitor from March was unremarkable."),
    ("est", "Stress test done in 2024 was negative."),
    ("holter", "Holter already arranged by her family doctor."),
    ("ecg", "I reviewed his ECG today."),
])
def test_result_or_history_mention_is_not_a_request(test, plan):
    assert med_eform.is_test_requested(test, plan) is False


@pytest.mark.parametrize("test,plan", [
    ("echo", "Repeat echo in 1 year."),
    ("echo", "Echo from 2024 showed EF 40%; repeat in 1 year."),
    ("ecg", "ECG today shows SR. Will repeat ECG at next visit."),
    ("holter", "Arrange 48 h Holter."),
    ("holter", "48 hour Holter."),
    ("est", "Book an exercise stress test before next appointment."),
    ("echo", "We will see him back in 6 months with an echocardiogram."),
    ("ecg", "1. ECG\n2. Echo in one year"),
])
def test_explicit_request_is_a_request(test, plan):
    assert med_eform.is_test_requested(test, plan) is True


def test_reported_results_do_not_open_the_requisition():
    # The model ticked tests that the PLAN only reports on: nothing is left, so the form stays closed.
    plan = "ECG today shows sinus rhythm. Echo last month EF 60%. Continue bisoprolol. Follow up in 1 year."
    r = req({"period": "1y", "ecg": True, "echo": True}, plan)
    assert r["requisition"] is False and r["requisition_diagnostics"] == []


def test_requested_tests_kept_reported_ones_dropped():
    plan = "ECG today shows atrial fibrillation. Arrange 48 h Holter and repeat echo in 6 months."
    r = req({"period": "6m", "ecg": True, "echo": True, "holter": "48h"}, plan)
    # ECG itself was only reported, but comes back with the Holter
    assert r["requisition_diagnostics"] == ["ecg", "echo", "holter"]


def test_stress_echo_conversion_adds_echo_only_when_echo_is_requested():
    r = req({"period": "1y", "stecho": True}, "Echo last year EF 55%. Arrange a stress test.")
    assert r["requisition_diagnostics"] == ["est"]


@pytest.mark.parametrize("plan", [
    "ECG today shows SR. Will increase bisoprolol to 5 mg daily.",
    "Echo last year EF 55%. Follow up in 1 year.",
])
def test_unrelated_next_sentence_does_not_make_a_reported_test_requested(plan):
    assert med_eform.is_test_requested("ecg" if "ECG" in plan else "echo", plan) is False
