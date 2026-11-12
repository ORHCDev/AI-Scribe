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


def test_a_plan_that_fits_is_not_changed():
    assert ebm.fit_plan(["Echo in 24 months."], "anything") == (["Echo in 24 months."], [])


def test_a_shortened_plan_that_fits_and_keeps_the_numbers_is_used():
    short = "\n".join(f"Consider item {i} in {i} mo." for i in range(1, 6))
    plan, notes = ebm.fit_plan(LONG, short)
    assert plan == [f"Consider item {i} in {i} mo." for i in range(1, 6)] and ebm.fits(plan)
    assert notes[0].startswith(f"{ebm.CHECK_PREFIX} Shortened from") and len(notes) == 1 + len(LONG)


@pytest.mark.parametrize("short", [
    None, "", "Consider item 1 in 1 mo.\nStart Crestor 40 mg.",  # a dose the plan did not have
    "\n".join(LONG)])  # still too long
def test_otherwise_the_last_items_are_left_out(short):
    plan, notes = ebm.fit_plan(LONG, short)
    assert plan == LONG[:len(plan)] and ebm.fits(plan) and plan
    assert [n.split("limit: ", 1)[1] for n in notes] == LONG[len(plan):]


def test_a_single_item_too_long_on_its_own_is_cut_at_a_word():
    plan, dropped = ebm.fit_by_dropping(["word " * 80])
    assert ebm.fits(plan) and plan[0].endswith("\u2026") and dropped == []


def test_the_shorten_prompt_has_the_limit_and_the_plan():
    prompt = ebm.build_shorten_prompt(["Echo in 24 months."])
    assert "at most 255 characters" in prompt and "Echo in 24 months." in prompt
