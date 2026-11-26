"""
Logic of the "Compare Action Plan" prompt (no LLM, no Oscar, no UI): plan A from the result box,
plan B from the evidence chatbot's answer, and when either one can be offered.
"""

from types import SimpleNamespace

from utils import compare_plan, ebm


def answer(summary="Increase rosuvastatin to 20 mg daily.", demo="123", **extra):
    return SimpleNamespace(metadata={"evidence_summary": summary, "evidence_demo_no": demo, **extra})


def test_plan_b_is_the_evidence_summary():
    assert compare_plan.plan_b_from_result("evidence_search", answer(), "123") == \
        ("Increase rosuvastatin to 20 mg daily.", "")


def test_plan_b_is_one_line_without_extra_spaces():
    plan, _ = compare_plan.plan_b_from_result("evidence_search", answer("Add  ezetimibe\n10 mg. "), "123")
    assert plan == "Add ezetimibe 10 mg."


def test_no_plan_b_from_another_workflow():
    plan, reason = compare_plan.plan_b_from_result("oscar_search", answer(), "123")
    assert plan == "" and "oscar_search" in reason


def test_no_plan_b_without_a_summary():
    plan, reason = compare_plan.plan_b_from_result("evidence_search", answer(summary=""), "123")
    assert plan == "" and "no summary" in reason


def test_no_plan_b_for_another_patient():
    plan, reason = compare_plan.plan_b_from_result("evidence_search", answer(demo="999"), "123")
    assert plan == "" and "another patient" in reason


def test_no_plan_b_without_an_answer():
    assert compare_plan.plan_b_from_result("evidence_search", None, "123")[0] == ""


def test_plan_b_offered_only_when_ready_for_the_open_patient():
    state = compare_plan.new_state(123)
    assert "still being made" in compare_plan.plan_b_text(state, "123")[1]
    state.update(status=compare_plan.READY, plan_b="Plan B")
    assert compare_plan.plan_b_text(state, "123") == ("Plan B", "")
    assert compare_plan.plan_b_text(state, "456")[0] == ""
    assert compare_plan.plan_b_text({}, "123")[0] == ""
    state.update(status=compare_plan.FAILED, reason="the chatbot failed")
    assert compare_plan.plan_b_text(state, "123") == ("", "no evidence plan: the chatbot failed")


def test_plan_a_is_the_result_box_without_ebm_lines():
    box = f"{ebm.STATUS_PREFIX} Check: no LDL in 12 months\nStart Crestor 10 mg daily\nRecheck lipids in 3 months\n"
    assert compare_plan.plan_a_text(box) == ("Start Crestor 10 mg daily\nRecheck lipids in 3 months", "")


def test_no_plan_a_while_the_rules_run():
    box = f"{ebm.STATUS_PREFIX} Running the EBM rules and checking them against the chart...\n"
    plan, reason = compare_plan.plan_a_text(box)
    assert plan == "" and reason


def test_length_label_counts_like_aplan():
    assert compare_plan.length_label("a\nb") == f"4/{ebm.APLAN_MAX_CHARS} characters"  # newline saved as \r\n
    assert "too long" in compare_plan.length_label("x" * (ebm.APLAN_MAX_CHARS + 1))
