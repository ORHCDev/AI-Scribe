"""
"Compare Action Plan" prompt: two action plans for the open patient, side by side, and the doctor picks one.

Plan A is the EBM prompt's action plan (the EBM form rules), made by the EBM prompt's own code, unchanged.
Plan B is the evidence chatbot's 255-character summary (EvidenceWorkflow's metadata["evidence_summary"])
of its answer to QUESTION, asked in the chat window so the question and the full answer stay there.
Populate opens a window with both plans; the chosen one (edited or not) is saved to APLAN the same way
the EBM prompt saves its plan.
"""

from utils import ebm

COMPARE_PROMPT = "Compare Action Plan"
QUESTION = "What are the recommended next management steps for this patient?"
EVIDENCE_WORKFLOW = "evidence_search"
PREFIX = "[Compare]"

# Plan B states
RUNNING, READY, FAILED = "running", "ready", "failed"


def new_state(demo_no) -> dict:
    """Plan B for a new compare run on this patient: not ready yet."""
    return {"demo_no": str(demo_no), "status": RUNNING, "plan_b": "", "reason": ""}


def plan_b_from_result(workflow_type, result, demo_no) -> tuple[str, str]:
    """(plan B, "") from the chatbot's answer, or ("", why there is none)."""
    if result is None:
        return "", "the chatbot gave no answer"
    if workflow_type != EVIDENCE_WORKFLOW:
        return "", f"the chatbot answered with {workflow_type or 'no workflow'} instead of evidence search"
    metadata = getattr(result, "metadata", None) or {}
    summary = " ".join(str(metadata.get("evidence_summary") or "").split())
    if not summary:
        return "", "the evidence answer has no summary"
    if str(metadata.get("evidence_demo_no") or "").strip() != str(demo_no):
        # The chatbot reads the patient from Oscar itself: never offer one patient's plan for another
        return "", "the evidence answer was made for another patient"
    return summary, ""


def plan_b_text(state: dict, demo_no) -> tuple[str, str]:
    """(plan B, "") for the patient now open, or ("", why it cannot be offered)."""
    if not state or state.get("demo_no") != str(demo_no):
        return "", "no evidence plan was made for this patient; click Generate Note first"
    if state.get("status") == RUNNING:
        return "", "the evidence plan is still being made (see the chat window)"
    if state.get("status") != READY:
        return "", f"no evidence plan: {state.get('reason') or 'it failed'}"
    return state.get("plan_b") or "", ""


def plan_a_text(result_box_text: str) -> tuple[str, str]:
    """(plan A, "") from the result box, or ("", why there is none)."""
    plan = ebm.plan_from_result_box(result_box_text)
    if not plan:
        return "", "no EBM plan in the result box (still running, or the rules gave none)"
    return plan, ""


PLAN_B_HEADER = f"{ebm.STATUS_PREFIX} ───── Plan B: evidence summary (pick A or B at Populate) ─────"


def plan_b_lines(state: dict) -> list:
    """Plan B's section of the result box: its status, or the plan. Every line starts with [EBM], so
    saving plan A from the result box never saves it."""
    status = (state or {}).get("status")
    if status == READY:
        plan = state.get("plan_b") or ""
        return [f"{ebm.STATUS_PREFIX}   {plan}", f"{ebm.STATUS_PREFIX}   ({length_label(plan)})"]
    if status == FAILED:
        return [f"{ebm.STATUS_PREFIX}   No plan B: {state.get('reason') or 'it failed'}"]
    return [f"{ebm.STATUS_PREFIX}   Asking the evidence chatbot... (see the chat window)"]


def with_plan_b(box_text: str, lines: list) -> str:
    """The result box with plan B's section (replaced if already there) at the bottom."""
    text = (box_text or "").rstrip("\n")
    at = text.find(PLAN_B_HEADER)
    if at != -1:
        text = text[:at].rstrip("\n")
    return "\n\n".join(part for part in (text, "\n".join([PLAN_B_HEADER] + list(lines))) if part)


def length_label(plan: str) -> str:
    """How much of APLAN the plan takes, e.g. "212/255 characters"."""
    n = ebm.saved_length(plan or "")
    label = f"{n}/{ebm.APLAN_MAX_CHARS} characters"
    if n > ebm.APLAN_MAX_CHARS:
        label += " - too long: Oscar keeps only the start"
    return label
