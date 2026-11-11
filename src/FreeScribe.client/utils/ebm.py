"""
"EBM" prompt: the clinic's EBM eForm (rules written in JavaScript) is run in a hidden frame, an LLM reviews its
action plan against the patient's chart, and Populate saves the result to the APLAN measurement by submitting the
EBM eForm, the same way it is saved by hand. The EBM form never opens on screen.
"""

import re

from utils.referral_requisition import fill_prompt

EBM_FORM_FID = 719
EBM_FORM_NAME = "0.1EBMp"

# Fields of the EBM form not sent to the LLM: identifiers, the billing helper, and earlier plans (PLAN, MPLAN,
# FPLAN and the saved action plan), which the LLM would otherwise copy into the new plan.
CHART_SKIP = {"Name", "dob", "postal", "todate", "billsheet", "bills", "bills1", "bills3", "bills4", "bills6",
              "consult", "dd", "subject", "searchbox", "actionplan", "history7", "history16", "history17"}

# Loads the EBM form in a hidden frame of the main Oscar window (same site, so its fields can be read and its
# scripts run), waits for its own onload (chart summaries, history keywords), then:
#  - "run": clicks "Run EBM Algorithms" (TotalScore) and returns the rule action plan and the chart fields;
#  - "save": runs TotalScore too (so the other values it fills are saved as they are by hand), replaces the
#    action plan with arguments[2], and clicks Submit; resolves once the frame has loaded the saved page.
# The action plan box is emptied first: it opens with the patient's saved APLAN, which must not be taken as the
# rules' plan when TotalScore stops before writing one. Errors thrown by the form's own scripts are caught and
# returned, as the form has a few.
EBM_FRAME_JS = """
var url = arguments[0], mode = arguments[1], plan = arguments[2], skip = arguments[3];
var done = arguments[arguments.length - 1];
var frame = document.createElement("iframe");
frame.style.display = "none";
var loads = 0, errors = [], finished = false;
var finish = function (result) {
    if (finished) { return; }
    finished = true;
    result.errors = errors;
    setTimeout(function () { frame.remove(); }, 0);
    done(result);
};
frame.onload = function () {
    loads += 1;
    if (loads > 1) { return finish({saved: true}); }
    var w = frame.contentWindow, d = frame.contentDocument;
    var ap = d.getElementById("actionplan");
    if (!ap) { return finish({missing: "actionplan"}); }
    ap.value = "";
    try { w.TotalScore(); } catch (e) { errors.push("TotalScore: " + e); }
    if (mode === "run") {
        var chart = [];
        d.querySelectorAll("input, textarea").forEach(function (el) {
            if (!el.id || skip.indexOf(el.id) >= 0 || el.type === "submit" || el.type === "button") { return; }
            var value = (el.type === "checkbox" || el.type === "radio") ? (el.checked ? "yes" : "") : el.value;
            if (!value || !String(value).trim()) { return; }
            var label = d.querySelector('label[for="' + el.id + '"]');
            chart.push([(label && label.textContent.trim()) || el.id, String(value).trim()]);
        });
        return finish({plan: ap.value, chart: chart});
    }
    ap.removeAttribute("disabled");
    ap.value = plan;
    var submit = d.querySelector('input[type=submit][name=SubmitButton]');
    if (!submit) { return finish({missing: "SubmitButton"}); }
    submit.click();
    setTimeout(function () { if (loads < 2) { finish({saved: false}); } }, 60000);
};
frame.src = url;
document.body.appendChild(frame);
"""

ACTION_PLAN_PROMPT = """You are a cardiologist reviewing the action plan the clinic's EBM rules produced for a patient,
using the patient's chart below.

RULE-BASED ACTION PLAN:
{RULE_PLAN}

PATIENT CHART (fields of the EBM form; "Pertinent Negatives" lists what the patient does not have):
{CHART}

Write the final action plan:
- Keep each item of the rule-based plan that the chart supports.
- Leave out an item the chart contradicts, e.g. a drug the patient is allergic to or already takes at that dose,
  a test done recently, or a condition the patient does not have.
- Add an item only when the chart clearly calls for it and the rule-based plan missed it. Never give a drug dose
  the rule-based plan or the chart does not support.
- Plain text only: one item per line, in full sentences, no markdown, no asterisks, no bullets, no headings.
- Do not write the patient's name or any explanation of your changes.
Reply with the action plan only."""

# The editable prompt (Prompt window: EBM -> Action Plan); this is the default.
PROMPT_SECTIONS = {"Action Plan": ACTION_PLAN_PROMPT}

# First line(s) of the result box written by AI-Scribe itself, not part of the plan.
STATUS_PREFIX = "[EBM]"


def chart_text(chart: list) -> str:
    """The form's fields as "label: value" lines."""
    return "\n".join(f"{label.rstrip(':')}: {' '.join(str(value).split())}" for label, value in chart)


def build_action_plan_prompt(rule_plan: str, chart: list, template: str | None = None) -> str:
    return fill_prompt(template or ACTION_PLAN_PROMPT,
                       RULE_PLAN=(rule_plan or "").strip() or "(the rules gave no action plan)",
                       CHART=chart_text(chart) or "(no chart data)")


def clean_action_plan(text: str) -> str:
    """The LLM's plan as plain text lines: no code fences, <br> tags (the EBM form writes some), markdown marks,
    bullets or numbering, no blank runs."""
    text = re.sub(r"```\w*", "", text or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    lines = []
    for line in text.splitlines():
        line = line.replace("**", "").replace("__", "")
        line = re.sub(r"^\s*(#+|[-*•]|\d+[.)])\s+", "", line).strip()
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()


def plan_from_result_box(text: str) -> str:
    """The plan in the result box, without AI-Scribe's own status lines."""
    lines = (text or "").strip().splitlines()
    while lines and (lines[0].startswith(STATUS_PREFIX) or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


def latest_aplan_query(demo_no) -> str:
    return (f"SELECT dataField, dateEntered FROM measurements WHERE demographicNo = {int(demo_no)} "
            "AND type = 'APLAN' ORDER BY dateEntered DESC, id DESC LIMIT 1")
