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
    assert checks[:2] == [f"{ebm.CHECK_PREFIX} HR 51 on bisoprolol. (from: no chart field named)",
                          f"{ebm.CHECK_PREFIX} Holter due. (from: no chart field named)"]
    assert len(checks) == ebm.MAX_CHECKS


def test_checks_end_with_the_chart_fields_they_come_from():
    reply = "[chief complaint; Patient Age] AF at 71 with no anticoagulant.\n[Last Holter] Pauses on the Holter."
    assert ebm.checks_from_reply(reply, CHART) == [
        f"{ebm.CHECK_PREFIX} AF at 71 with no anticoagulant. (from: Chief complaint; Patient Age)",
        f"{ebm.CHECK_PREFIX} Pauses on the Holter. (from: no chart field named)"]


def test_check_without_a_sentence_is_dropped():
    assert ebm.checks_from_reply("[Patient Age]", CHART) == []


def test_none_reply_gives_no_checks():
    assert ebm.checks_from_reply("NONE") == [] and ebm.checks_from_reply("None.") == []


def test_result_text_puts_checks_and_notes_above_the_plan():
    text = ebm.result_text(["Echo in 24 months."], [f"{ebm.CHECK_PREFIX} HR 51."], rules_stopped=True,
                           notes=[f"{ebm.CHECK_PREFIX} Left out: x"])
    assert text.splitlines() == [ebm.RULES_STOPPED_CHECK, f"{ebm.CHECK_PREFIX} HR 51.", f"{ebm.CHECK_PREFIX} Left out: x",
                                 "", "Echo in 24 months."]
    assert ebm.plan_from_result_box(text) == "Echo in 24 months."


def test_result_text_shows_the_billing_codes_first_and_never_saves_them():
    text = ebm.result_text(["Echo in 24 months."], [f"{ebm.CHECK_PREFIX} HR 51."], False, billing=" A603   428 ")
    assert text.splitlines() == [f"{ebm.BILLING_PREFIX} A603   428", f"{ebm.CHECK_PREFIX} HR 51.", "",
                                 "Echo in 24 months."]
    assert ebm.plan_from_result_box(text) == "Echo in 24 months."
    assert "To bill next" not in ebm.result_text(["Echo in 24 months."], [], False, billing="")


def test_frame_script_returns_the_billing_codes_in_run_mode():
    assert 'billing: bill ? bill.value : ""' in ebm.EBM_FRAME_JS
    assert 'getElementById("subject")' in ebm.EBM_FRAME_JS


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
    assert "names of the chart fields the point comes from in square brackets" in ebm.CHECKS_PROMPT
    assert "repeat or conflict with each other are handled when the plan is written" in ebm.CHECKS_PROMPT
    assert "two items asking for the same thing become one" in ebm.FORMAT_PROMPT


def test_a_rewording_may_drop_a_repeated_test():
    lines = ["Assess with a stress test in 24 months.", "Assess with a persantine sestamibi scan in 24 months."]
    plan, _ = ebm.format_plan(lines, "Assess with a persantine sestamibi scan in 24 months.")
    assert plan == ["Assess with a persantine sestamibi scan in 24 months."]


def test_format_prompt_does_not_add_a_missing_purpose():
    assert "If an item gives no purpose, do not add one" in ebm.FORMAT_PROMPT


def test_checks_prompt_asks_for_actionable_single_points():
    assert "one sentence that says what is missing" in ebm.CHECKS_PROMPT
    assert "Do not list normal results, or a test or treatment the plan already asks for" in ebm.CHECKS_PROMPT
    assert "Write one point per problem" in ebm.CHECKS_PROMPT


def test_the_format_prompt_makes_255_characters_a_limit():
    prompt = ebm.build_format_prompt(["Echo in 24 months."])
    assert f"try to stay within {ebm.APLAN_MAX_CHARS} characters" in prompt


def test_a_shortened_plan_is_used_when_it_keeps_every_number_and_test():
    short = [f"Consider item {i}, in {i} mo." for i in range(1, 6)]
    assert ebm.shorter_plan(LONG, "\n".join(short)) == short
    assert ebm.fits(short) and ebm.length_note(short) == []
    prompt = ebm.build_shorten_prompt(LONG)
    assert str(ebm.saved_length("\n".join(LONG))) in prompt and LONG[0] in prompt


@pytest.mark.parametrize("reply", [
    "Consider item 1 in 1 mo.\nConsider item 2 in 2 mo.",  # items dropped
    "\n".join(f"Consider item {i} in {i} mo with an echo." for i in range(1, 6)),  # a new test
    "\n".join(LONG) + "\nMore.",  # not shorter
    ""])
def test_a_shortened_plan_that_drops_or_adds_something_is_not_used(reply):
    assert ebm.shorter_plan(LONG, reply) == LONG


def test_new_points_become_plan_items_and_checks_stay_checks():
    reply = ("NEW [Chief complaint; Patient Age] Consider anticoagulation for AF at 71.\n"
             "CHECK [Patient Age] Creatinine not in the chart.\nHR 48 on bisoprolol.")
    checks, items = ebm.points_from_reply(reply, CHART)
    assert items == [("Consider anticoagulation for AF at 71.", ["Chief complaint", "Patient Age"])]
    assert checks == [f"{ebm.CHECK_PREFIX} Creatinine not in the chart. (from: Patient Age)",
                      f"{ebm.CHECK_PREFIX} HR 48 on bisoprolol. (from: no chart field named)"]
    assert ebm.checks_from_reply(reply, CHART) == checks


def test_points_are_capped_at_three_in_all():
    reply = "\n".join(f"NEW Consider item {i}." for i in range(3)) + "\nCHECK HR 48."
    checks, items = ebm.points_from_reply(reply)
    assert len(items) == 3 and checks == []


def test_new_items_are_part_of_the_plan_with_their_source_below_their_line():
    items = [("Consider anticoagulation for AF.", ["Last Holter"]), ("Consider statin for LDL 4.1.", ["LDL"])]
    assert ebm.tagged_items(items) == ["Consider anticoagulation for AF. [N1]", "Consider statin for LDL 4.1. [N2]"]
    # The LLM merged N2 into an old item and put N1 first
    plan = ["Consider anticoagulation for AF. [N1]", "Echo in 24 months; consider statin for LDL 4.1. [N2]"]
    text = ebm.result_text(plan, [f"{ebm.CHECK_PREFIX} HR 48."], False, new_items=items)
    assert text.splitlines() == [f"{ebm.CHECK_PREFIX} HR 48.", "", "Consider anticoagulation for AF.",
                                 f"{ebm.STATUS_PREFIX}   from: Last Holter",
                                 "Echo in 24 months; consider statin for LDL 4.1.", f"{ebm.STATUS_PREFIX}   from: LDL"]
    assert ebm.plan_from_result_box(text) == ("Consider anticoagulation for AF.\n"
                                              "Echo in 24 months; consider statin for LDL 4.1.")


def test_a_new_item_whose_tag_was_dropped_lists_its_source_after_the_plan():
    items = [("Consider statin for LDL 4.1.", ["LDL"])]
    text = ebm.result_text(["Echo in 24 months.", "Consider statin for LDL 4.1."], [], False, new_items=items)
    assert text.splitlines()[-1] == f"{ebm.STATUS_PREFIX}   from (added item): LDL"
    assert "[N" not in ebm.plan_from_result_box(text)


def test_tags_are_not_counted_as_numbers_or_characters():
    whole = ["Echo in 24 months.", "Consider statin for LDL 4.1. [N1]"]
    plan, _ = ebm.format_plan(whole, "Assess with an echo in 24 months.\nConsider a statin for LDL 4.1. [N1]")
    assert plan == ["Assess with an echo in 24 months.", "Consider a statin for LDL 4.1. [N1]"]
    assert ebm.saved_length("Echo. [N1]") == len("Echo.")


def test_the_format_prompt_rewrites_old_and_new_items_as_one_plan():
    assert "old and new items together, is rewritten as one" in ebm.FORMAT_PROMPT
    assert "no repeated item, nothing wrong, and no sentence that does not read clearly" in ebm.FORMAT_PROMPT
    assert "Keep each tag such as [N1]" in ebm.SHORTEN_PROMPT


def test_the_checks_prompt_asks_for_new_and_check_points():
    assert "Start each point with NEW or CHECK" in ebm.CHECKS_PROMPT and "Never give a drug dose" in ebm.CHECKS_PROMPT


def test_safety_concerns_are_new_plan_items_and_missing_data_stays_a_check():
    prompt = ebm.CHECKS_PROMPT
    assert "or a safety concern with the plan or the current\n  medications" in prompt
    assert '"Consider reducing bisoprolol\n  for HR 48"' in prompt
    assert "CHECK for missing or old chart data" in prompt


def test_prompts_ask_for_clear_logical_sentences():
    for prompt in (ebm.FORMAT_PROMPT, ebm.SHORTEN_PROMPT, ebm.CHECKS_PROMPT):
        assert "one clear, logical sentence" in prompt


_AV_PLAN = ["Assess low-grade AV block with an echo and stress test at the next opportunity.", "Patient requires OAC"]


def test_a_rewording_or_shortening_that_drops_a_time_in_words_is_not_used():
    plan, _ = ebm.format_plan(_AV_PLAN, "Echo, stress test for low-grade AV block\nOAC req")
    assert plan == _AV_PLAN
    assert ebm.shorter_plan(_AV_PLAN, "Echo, stress test for low-grade AV block\nOAC req") == _AV_PLAN
    kept = "Assess low-grade AV block with echo, stress test at next opportunity.\nPatient requires OAC"
    assert ebm.shorter_plan(_AV_PLAN, kept) == kept.splitlines()


def test_points_repeating_the_plan_are_dropped_but_safety_concerns_stay():
    checks = [f"{ebm.CHECK_PREFIX} Echo from 2000 is outdated for the planned assessment. (from: Last Echo)",
              f"{ebm.CHECK_PREFIX} No creatinine in the chart for the planned Ramipril. (from: Last Echo)"]
    items = [("Assess need for OAC for persistent atrial fibrillation.", ["ECG"]),
             ("Consider alternative to OAC or dose adjustment for severe renal failure (eGFR 6).", ["eGFR"]),
             ("Consider lipid-lowering therapy for Lp(a) 296.", ["Lp(a)"])]
    kept_checks, kept_items = ebm.drop_repeats(checks, items, "\n".join(_AV_PLAN))
    assert kept_checks == checks[1:]
    assert [s for s, _ in kept_items] == [items[1][0], items[2][0]]


def test_prompts_keep_readability_and_leave_out_repeats():
    assert "readability comes before length" in ebm.FORMAT_PROMPT and "must be at most" not in ebm.FORMAT_PROMPT
    assert "never cut an\n  item to a few words" in ebm.SHORTEN_PROMPT
    assert "Never write a NEW point about a drug or test the plan already mentions" in ebm.CHECKS_PROMPT


def test_a_plan_too_long_is_cut_at_whole_lines_and_the_rest_shown_unsaved():
    plan = [f"Consider item number {i} of the plan, to be done in {i} months. [N{i}]" if i == 5 else
            f"Consider item number {i} of the plan, to be done in {i} months." for i in range(1, 8)]
    kept, cut = ebm.cut_to_fit(plan)
    assert ebm.fits(kept) and not ebm.fits(kept + cut[:1]) and kept + cut == plan
    items = [("x", [])] * 4 + [("Consider item number 5.", ["LDL"])]
    text = ebm.result_text(kept, [], False, ebm.cut_note(plan, cut), new_items=items, cut=cut)
    assert ebm.plan_from_result_box(text) == "\n".join(kept)
    assert ebm.saved_length(ebm.plan_from_result_box(text)) <= ebm.APLAN_MAX_CHARS
    assert ebm.CUT_HEADER in text and f"{ebm.STATUS_PREFIX}   from: LDL" in text
    full = text.split(ebm.CUT_HEADER)[1].splitlines()[1:]
    assert [line for line in full if not line.startswith(f"{ebm.STATUS_PREFIX}   from")] == \
        [f"{ebm.STATUS_PREFIX}   {ebm.untag(line)}" for line in plan]
    assert text.index("\n".join(kept)) < text.index(ebm.CUT_HEADER)
    assert text.count("from (added item)") == 4 and text.count(f"{ebm.STATUS_PREFIX}   from: LDL") == 1
    assert f"the last {len(cut)} lines are cut off" in text


def test_a_plan_that_fits_is_not_cut():
    assert ebm.cut_to_fit(["Echo in 24 months."]) == (["Echo in 24 months."], [])
    assert ebm.cut_note(["Echo in 24 months."], []) == []


@pytest.mark.parametrize("plan,item", [
    ("Start Norvasc 2.5 mg daily", "Consider adding a second antihypertensive agent for BP 169/79"),
    ("Increase Coversyl to 8 mg daily", "Consider adding an antihypertensive for BP 150/90"),
    ("Start Norvasc 2.5 mg daily", "Consider amlodipine for BP 169/79"),  # the same drug by its generic name
    ("counselling for depression/stress.", "Consider treating depression as noted in PMH"),
    ("Start Champix for smoking cessation", "Consider smoking cessation counselling"),
    ("Mediterranean-PREDIMED", "Consider a Mediterranean diet for LDL 3.25"),
])
def test_new_items_repeating_a_planned_topic_are_dropped(plan, item):
    assert ebm.drop_repeats([], [(item, ["X"])], plan)[1] == []


def test_a_new_item_on_a_new_topic_or_a_safety_concern_is_kept():
    assert ebm.drop_repeats([], [("Consider lipid-lowering therapy for LDL 3.25", ["LDL"])],
                            "Start Norvasc 2.5 mg daily")[1] != []
    assert ebm.drop_repeats([], [("Consider reducing bisoprolol for HR 48", ["HR"])],
                            "Increase Bisoprolol to 5 mg daily")[1] != []
    # "lipid-lowering" is not a safety word: a repeat of a planned statin is dropped
    assert ebm.drop_repeats([], [("Consider lipid-lowering therapy for LDL 3.25", ["LDL"])],
                            "Consider intermediate dose statin")[1] == []
    # "stress test" is not the depression topic
    assert ebm.drop_repeats([], [("Consider counselling for anxiety", ["PMH"])],
                            "Assess with a stress test in 24 months")[1] != []


def test_prompts_keep_the_tense():
    for prompt in (ebm.FORMAT_PROMPT, ebm.SHORTEN_PROMPT):
        assert "Keep the tense" in prompt and "never turn it into an\n  instruction" in prompt


@pytest.mark.parametrize("item", ["Consider an ARB such as losartan for the dilated aortic root",
                                  "Consider bisoprolol for the aortic root and HR 80"])
def test_a_new_item_naming_another_antihypertensive_is_kept(item):
    assert ebm.drop_repeats([], [(item, ["VA"])], "Start Norvasc 2.5 mg daily")[1] != []
