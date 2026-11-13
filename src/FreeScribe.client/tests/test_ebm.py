"""
Logic of the "EBM" prompt (no LLM, no Oscar): prompt building, cleaning the LLM's plan, the result box.
"""

from pathlib import Path

import pytest

import yaml

from utils import ebm

CHART = [["Chief complaint:", "atrial fibrillation"], ["Patient Age:", "71"], ["Pertinent Negatives", " DIABETES"]]


def test_prompt_has_the_rule_plan_and_the_chart():
    prompt = ebm.build_checks_prompt("Start Coversyl 4 mg daily", CHART)
    assert "Start Coversyl 4 mg daily" in prompt
    assert "Chief complaint: atrial fibrillation" in prompt and "Patient Age: 71" in prompt


def test_prompt_without_a_rule_plan_says_so():
    assert "(the rules gave no action plan)" in ebm.build_checks_prompt("  ", CHART)


def test_edited_prompt_is_used_and_a_deleted_placeholder_is_added_at_the_end():
    prompt = ebm.build_checks_prompt("PLAN", CHART, "Review this plan: {RULE_PLAN}")
    assert prompt.startswith("Review this plan: PLAN")
    assert "CHART:\nChief complaint: atrial fibrillation" in prompt


def test_identifiers_and_billing_are_not_sent():
    assert {"Name", "dob", "billsheet", "actionplan"} <= ebm.CHART_SKIP


def test_earlier_plans_are_not_sent():
    assert {"history7", "history16", "history17", "actionplan"} <= ebm.CHART_SKIP


def test_clean_action_plan_removes_markdown_bullets_and_fences():
    raw = "```\n**Action plan**\n- Start Coversyl 4 mg daily.\n\n\n2. We will assess with an echo.\n```"
    assert ebm.clean_action_plan(raw) == "Action plan\nStart Coversyl 4 mg daily.\n\nWe will assess with an echo."


def test_plan_from_result_box_drops_status_and_check_lines():
    box = (f"{ebm.STATUS_PREFIX} Action plan saved to APLAN.\n{ebm.CHECK_PREFIX} HR 51 on bisoprolol.\n\n"
           f"Start Coversyl 4 mg daily.\n{ebm.CHECK_PREFIX} added by the doctor in the middle\nEcho in 1 year.")
    assert ebm.plan_from_result_box(box) == "Start Coversyl 4 mg daily.\nEcho in 1 year."


def test_a_check_line_without_its_prefix_is_saved():
    box = f"{ebm.CHECK_PREFIX} HR 51 on bisoprolol.\nWe will arrange a repeat Holter.\n\nEcho in 1 year."
    assert ebm.plan_from_result_box(box) == "We will arrange a repeat Holter.\n\nEcho in 1 year."
    assert ebm.plan_from_result_box(f"{ebm.STATUS_PREFIX} Running the EBM rules...") == ""


def test_latest_aplan_query_needs_a_number():
    assert "demographicNo = 42" in ebm.latest_aplan_query("42") and "'APLAN'" in ebm.latest_aplan_query(42)


def test_default_prompts_yaml_has_the_same_ebm_prompt():
    data = yaml.safe_load((Path(__file__).resolve().parents[1] / "prompts" / "default_prompts.yaml").read_text("utf-8"))
    assert {k: v.strip() for k, v in data["EBM"]["Sections"].items()} == \
        {k: v.strip() for k, v in ebm.PROMPT_SECTIONS.items()}


def test_clean_action_plan_turns_br_tags_into_lines():
    assert ebm.clean_action_plan("Repeat K+ in 3 months.<br><br>Echo in 1 year.<BR/>") == \
        "Repeat K+ in 3 months.\n\nEcho in 1 year."


def test_rule_plan_is_kept_without_br_blanks_repeats_or_we_will():
    rule = "We will assess recent cardiac testing with an echo in 24 months.<br><br>\n  Start Coversyl 4 mg daily.  \n" \
           "start coversyl 4 mg daily."
    assert ebm.rule_plan_lines(rule) == ["Assess recent cardiac testing with an echo in 24 months.",
                                         "Start Coversyl 4 mg daily."]


def test_checks_from_reply_are_prefixed_and_capped():
    reply = "1. HR 51 on bisoprolol.\n- Check: Holter due.\n" + "\n".join(f"point {i}" for i in range(10))
    checks = ebm.checks_from_reply(reply)
    assert checks[:2] == [f"{ebm.CHECK_PREFIX} HR 51 on bisoprolol.", f"{ebm.CHECK_PREFIX} Holter due."]
    assert len(checks) == ebm.MAX_CHECKS


def test_none_reply_gives_no_checks():
    assert ebm.checks_from_reply("NONE") == [] and ebm.checks_from_reply("None.") == []


def test_result_text_puts_checks_and_notes_above_the_plan():
    text = ebm.result_text(["Echo in 24 months."], [f"{ebm.CHECK_PREFIX} HR 51."], rules_stopped=True,
                           notes=[f"{ebm.CHECK_PREFIX} Left out: x"])
    assert text.splitlines() == [ebm.RULES_STOPPED_CHECK, f"{ebm.CHECK_PREFIX} HR 51.", f"{ebm.CHECK_PREFIX} Left out: x",
                                 "", "Echo in 24 months."]
    assert ebm.plan_from_result_box(text) == "Echo in 24 months."


def test_result_text_says_when_the_rules_gave_no_plan():
    text = ebm.result_text([], [], rules_stopped=False)
    assert text == ebm.NO_RULE_PLAN_CHECK and ebm.plan_from_result_box(text) == ""


@pytest.mark.parametrize("line,expected", [
    ("We will consider switching to Crestor 40 mg daily.", "Consider switching to Crestor 40 mg daily."),
    ("We will assess with an echo in 24 months.", "Assess with an echo in 24 months."),
    ("We will also check blood work in 12 months.", "Check blood work in 12 months."),
    ("We recommend a Mediterranean diet.", "Recommend a Mediterranean diet."),
    ("We also discussed smoking cessation.", "Discussed smoking cessation."),
    ("Consider Edoxaban 60 mg daily.", "Consider Edoxaban 60 mg daily."),
    ("Mediterranean-PREDIMED", "Mediterranean-PREDIMED"),
])
def test_we_will_openings_are_removed(line, expected):
    assert ebm.concise_line(line) == expected


def test_saved_length_counts_line_breaks_as_two_characters():
    assert ebm.saved_length("abc\ndef") == 8


LONG = [f"Consider item number {i} of the plan, to be done in {i} months for the reasons in the chart." for i in range(1, 6)]


def test_a_long_plan_keeps_every_item_and_gets_a_note():
    plan, notes = ebm.format_plan(LONG, None)
    assert plan == LONG
    assert notes == [f"{ebm.CHECK_PREFIX} The plan is {ebm.saved_length(chr(10).join(LONG))} characters; Oscar keeps "
                     f"only the first {ebm.APLAN_MAX_CHARS} of APLAN."]


def test_a_rewording_with_the_same_numbers_is_used_even_if_long():
    reworded = [line.replace("Consider item number", "Consider item no.") for line in LONG]
    plan, notes = ebm.format_plan(LONG, "\n".join(reworded))
    assert plan == reworded and notes[0].startswith(f"{ebm.CHECK_PREFIX} The plan is")


@pytest.mark.parametrize("reply", [
    "Consider item 1 in 1 mo.\nStart Crestor 40 mg.",  # a new dose
    "Consider item 1 in 1 mo with an echo."])  # a new test
def test_a_rewording_that_adds_a_number_or_a_test_is_not_used(reply):
    plan, notes = ebm.format_plan(LONG, reply)
    assert plan == LONG and len(notes) == 1 and notes[0].startswith(f"{ebm.CHECK_PREFIX} The plan is")


def test_the_format_prompt_puts_content_first_and_has_the_with_rule():
    prompt = ebm.build_format_prompt(["Echo in 24 months."])
    assert "Getting the content right comes first" in prompt and "never" in prompt
    assert '"Assess <purpose> with <test> <time>"' in prompt and "Echo in 24 months." in prompt


def test_a_reworded_plan_is_used_without_extra_notes():
    plan, notes = ebm.format_plan(["Assess exertional chest tightness; do an echo at the next opportunity."],
                                  "Assess exertional chest tightness with an echo at the next opportunity.")
    assert plan == ["Assess exertional chest tightness with an echo at the next opportunity."] and notes == []


def test_checks_are_capped_at_three():
    assert ebm.MAX_CHECKS == 3 and "at most 3 points" in ebm.CHECKS_PROMPT


def test_the_rules_wording_goes_below_the_plan_only_when_reworded():
    text = ebm.result_text(["Assess chest tightness with an echo."], [f"{ebm.CHECK_PREFIX} HR 51."], False,
                           original=["We will assess chest tightness; do an echo."])
    lines = text.splitlines()
    assert lines[:3] == [f"{ebm.CHECK_PREFIX} HR 51.", "", "Assess chest tightness with an echo."]
    assert lines[4:] == [ebm.ORIGINAL_HEADER, f"{ebm.STATUS_PREFIX}   We will assess chest tightness; do an echo."]
    assert ebm.plan_from_result_box(text) == "Assess chest tightness with an echo."
    same = ebm.result_text(["Echo in 24 months."], [], False, original=["Echo in 24 months."])
    assert ebm.ORIGINAL_HEADER not in same


@pytest.mark.parametrize("text,expected", [
    ("assess ASCVD risk - s echo in the coming months.", {"stress echo"}),
    ("Assess ASCVD risk with a stress echo in the coming months.", {"stress echo"}),
    ("Assess AS with an echo and a 72 hour Holter study.", {"echo", "holter"}),
    ("Assess with persantine sestamibi scan; stress test in 24 months.", {"mibi", "stress test"}),
    ("Check blood work for renal function.", set())])
def test_tests_named_in_a_plan(text, expected):
    assert ebm._tests(text) == expected


def test_a_rewording_that_turns_a_stress_echo_into_an_echo_is_not_used():
    lines = ["assess ASCVD risk - s echo in the coming months."]
    plan, _ = ebm.format_plan(lines, "Assess ASCVD risk with an echo in the coming months.")
    assert plan == lines
    plan, _ = ebm.format_plan(lines, "Assess ASCVD risk with a stress echo in the coming months.")
    assert plan == ["Assess ASCVD risk with a stress echo in the coming months."]


def test_the_format_prompt_keeps_test_names_and_statements():
    assert '"s echo" means stress echo' in ebm.FORMAT_PROMPT and "stays a statement" in ebm.FORMAT_PROMPT


def test_checks_name_their_chart_source_and_leave_repeats_to_the_plan():
    assert "a problem in the chart the plan does not address" in ebm.CHECKS_PROMPT
    assert "names where in the chart it comes from" in ebm.CHECKS_PROMPT
    assert "repeat or conflict with each other are handled when the plan is written" in ebm.CHECKS_PROMPT
    assert "two items asking for the same thing become one" in ebm.FORMAT_PROMPT


def test_a_rewording_may_drop_a_repeated_test():
    lines = ["Assess with a stress test in 24 months.", "Assess with a persantine sestamibi scan in 24 months."]
    plan, _ = ebm.format_plan(lines, "Assess with a persantine sestamibi scan in 24 months.")
    assert plan == ["Assess with a persantine sestamibi scan in 24 months."]
