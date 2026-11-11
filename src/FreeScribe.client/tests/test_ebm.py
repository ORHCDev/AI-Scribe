"""
Logic of the "EBM" prompt (no LLM, no Oscar): prompt building, cleaning the LLM's plan, the result box.
"""

from pathlib import Path

import yaml

from utils import ebm

CHART = [["Chief complaint:", "atrial fibrillation"], ["Patient Age:", "71"], ["Pertinent Negatives", " DIABETES"]]


def test_prompt_has_the_rule_plan_and_the_chart():
    prompt = ebm.build_action_plan_prompt("Start Coversyl 4 mg daily", CHART)
    assert "Start Coversyl 4 mg daily" in prompt
    assert "Chief complaint: atrial fibrillation" in prompt and "Patient Age: 71" in prompt


def test_prompt_without_a_rule_plan_says_so():
    assert "(the rules gave no action plan)" in ebm.build_action_plan_prompt("  ", CHART)


def test_edited_prompt_is_used_and_a_deleted_placeholder_is_added_at_the_end():
    prompt = ebm.build_action_plan_prompt("PLAN", CHART, "Review this plan: {RULE_PLAN}")
    assert prompt.startswith("Review this plan: PLAN")
    assert "CHART:\nChief complaint: atrial fibrillation" in prompt


def test_identifiers_and_billing_are_not_sent():
    assert {"Name", "dob", "billsheet", "actionplan"} <= ebm.CHART_SKIP


def test_earlier_plans_are_not_sent():
    assert {"history7", "history16", "history17", "actionplan"} <= ebm.CHART_SKIP


def test_clean_action_plan_removes_markdown_bullets_and_fences():
    raw = "```\n**Action plan**\n- Start Coversyl 4 mg daily.\n\n\n2. We will assess with an echo.\n```"
    assert ebm.clean_action_plan(raw) == "Action plan\nStart Coversyl 4 mg daily.\n\nWe will assess with an echo."


def test_plan_from_result_box_drops_status_lines():
    box = f"{ebm.STATUS_PREFIX} Action plan saved to APLAN.\n\nStart Coversyl 4 mg daily.\nEcho in 1 year."
    assert ebm.plan_from_result_box(box) == "Start Coversyl 4 mg daily.\nEcho in 1 year."
    assert ebm.plan_from_result_box(f"{ebm.STATUS_PREFIX} Running the EBM rules...") == ""


def test_latest_aplan_query_needs_a_number():
    assert "demographicNo = 42" in ebm.latest_aplan_query("42") and "'APLAN'" in ebm.latest_aplan_query(42)


def test_default_prompts_yaml_has_the_same_ebm_prompt():
    data = yaml.safe_load((Path(__file__).resolve().parents[1] / "prompts" / "default_prompts.yaml").read_text("utf-8"))
    assert data["EBM"]["Sections"]["Action Plan"].strip() == ebm.ACTION_PLAN_PROMPT.strip()


def test_clean_action_plan_turns_br_tags_into_lines():
    assert ebm.clean_action_plan("Repeat K+ in 3 months.<br><br>Echo in 1 year.<BR/>") == \
        "Repeat K+ in 3 months.\n\nEcho in 1 year."
