"""
"EBM" prompt: the clinic's EBM eForm (rules written in JavaScript) is run in a hidden frame and its action plan is
shown unchanged, with points for the doctor to check that an LLM finds by comparing it with the patient's chart.
Populate saves the plan (without those points) to the APLAN measurement by submitting the EBM eForm, the same way
it is saved by hand. The EBM form never opens on screen.
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

CHECKS_PROMPT = """You are a cardiologist checking the action plan the clinic's EBM rules produced for a patient against
the patient's chart. Do not rewrite the plan: it is kept as it is.

RULE-BASED ACTION PLAN:
{RULE_PLAN}

PATIENT CHART (fields of the EBM form; "Pertinent Negatives" lists what the patient does not have):
{CHART}

List up to 5 points the doctor should check before saving the plan, most important first:
- a problem in the chart the plan does not address (e.g. a test that is due, an untreated condition);
- a safety concern with the plan or the current medications (e.g. a slow heart rate on a beta-blocker, an allergy
  to a recommended drug, an abnormal lab value);
- items of the plan that conflict with or repeat each other;
- missing or old chart data that an item of the plan depends on.
Each point is one sentence that names the chart finding it is based on (a value, a date or a diagnosis). Never
write vague points such as "monitor ..." or "continue current medications". Do not write the patient's name.
Reply with one point per line and nothing else. If there is nothing to check, reply with NONE."""

FORMAT_PROMPT = """Rewrite this cardiology action plan in the clinic's style. Getting the content right comes first:
every item of the plan must still be there with the same meaning, nothing wrong and nothing left out.
- Keep every item. Keep each drug name, dose, test and time exactly. Do not add any test, drug, dose or time.
- Keep how strong each item is: "Consider" stays "Consider", "Recommend" stays "Recommend".
- Write the purpose of a test and the test as one item, joined with "with": "Assess <purpose> with <test> <time>",
  e.g. "Assess exertional chest tightness with an echo at the next opportunity". Never split them with ";" or
  write the test as a separate item.
- One item per line, plain text, no bullets. Start each item with a verb such as "Assess", "Check", "Consider",
  "Recommend" or "Start", never with "We will".
- Use concise wording (BP, LDL, f/u, mo, yr are fine) and try to stay within {MAX} characters in total, but never
  leave out an item or change its meaning to fit.

PLAN:
{PLAN}

Reply with the rewritten plan only."""

# The editable prompts (Prompt window: EBM -> Checks / Format); these are the defaults.
PROMPT_SECTIONS = {"Checks": CHECKS_PROMPT, "Format": FORMAT_PROMPT}

# Lines of the result box written by AI-Scribe itself (status and checks for the doctor), never saved to APLAN.
STATUS_PREFIX = "[EBM]"
CHECK_PREFIX = f"{STATUS_PREFIX} Check:"
MAX_CHECKS = 5
RULES_STOPPED_CHECK = (f"{CHECK_PREFIX} The EBM rules stopped early because of an error in the EBM form; "
                       "some items may be missing.")
NO_RULE_PLAN_CHECK = f"{CHECK_PREFIX} The EBM rules gave no action plan."


def chart_text(chart: list) -> str:
    """The form's fields as "label: value" lines."""
    return "\n".join(f"{label.rstrip(':')}: {' '.join(str(value).split())}" for label, value in chart)


def build_checks_prompt(rule_plan: str, chart: list, template: str | None = None) -> str:
    return fill_prompt(template or CHECKS_PROMPT,
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


# Oscar keeps at most 255 characters of a measurement; the textarea sends each line break as \r\n.
APLAN_MAX_CHARS = 255
_WE_OPENINGS = ((r"^we (?:will )?(?:also )?recommend(?:ed)?\b\s*", "Recommend "),
                (r"^we (?:also )?discussed\b\s*", "Discussed "),
                (r"^we will (?:also )?", ""))


def concise_line(line: str) -> str:
    """A plan item without its "We will ..." opening: "We will consider switching ..." -> "Consider switching ...",
    "We recommend ..." -> "Recommend ...". The rest of the item is not changed."""
    for pattern, replacement in _WE_OPENINGS:
        new = re.sub(pattern, replacement, line, count=1, flags=re.IGNORECASE)
        if new != line:
            return new[:1].upper() + new[1:]
    return line


def saved_length(plan: str) -> int:
    """How many characters of APLAN the plan takes once saved."""
    return len((plan or "").replace("\r\n", "\n").replace("\n", "\r\n"))


def fits(lines: list) -> bool:
    return saved_length("\n".join(lines)) <= APLAN_MAX_CHARS


def build_format_prompt(lines: list, template: str | None = None) -> str:
    return fill_prompt(template or FORMAT_PROMPT, MAX=str(APLAN_MAX_CHARS), PLAN="\n".join(lines))


def _numbers(text: str) -> set:
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


def length_note(plan_lines: list) -> list:
    """A note for the doctor when the plan is longer than the 255 characters Oscar keeps of APLAN."""
    length = saved_length("\n".join(plan_lines))
    if length <= APLAN_MAX_CHARS:
        return []
    return [f"{CHECK_PREFIX} The plan is {length} characters; Oscar keeps only the first {APLAN_MAX_CHARS} of APLAN."]


def format_plan(lines: list, formatted_reply: str | None) -> tuple[list, list]:
    """(plan lines, notes for the doctor). The LLM's rewording (FORMAT_PROMPT) is used when it has the same numbers
    (doses, times) as the rules' plan, none new and none lost, with the rules' wording shown as notes; otherwise
    the rules' wording is used. A note says when the plan is longer than Oscar keeps; nothing is left out."""
    if not lines:
        return [], []
    formatted = [concise_line(" ".join(line.split()))
                 for line in clean_action_plan(formatted_reply or "").splitlines() if line.strip()]
    if formatted and _numbers("\n".join(formatted)) == _numbers("\n".join(lines)):
        if formatted == lines:
            return formatted, length_note(formatted)
        return formatted, length_note(formatted) + [f"{CHECK_PREFIX} Reworded by the LLM; the rules' plan was:"] + \
            [f"{CHECK_PREFIX} Rules: {line}" for line in lines]
    notes = [f"{CHECK_PREFIX} The LLM's rewording changed a dose or time, so the rules' wording is shown."] \
        if formatted else []
    return lines, length_note(lines) + notes


def rule_plan_lines(rule_plan: str) -> list:
    """The rules' action plan one item per line, without "We will" openings, <br> tags, blank lines or repeats."""
    lines, seen = [], set()
    for line in re.sub(r"<br\s*/?>", "\n", rule_plan or "", flags=re.IGNORECASE).splitlines():
        line = concise_line(" ".join(line.split()))
        if line and line.lower() not in seen:
            seen.add(line.lower())
            lines.append(line)
    return lines


def checks_from_reply(text: str) -> list:
    """The LLM's points (at most MAX_CHECKS) as CHECK_PREFIX lines; none when it replied NONE."""
    checks = []
    for line in clean_action_plan(text).splitlines():
        line = re.sub(r"^\s*(\[EBM\]\s*)?check:\s*", "", line, flags=re.IGNORECASE).strip()
        if line and line.strip(".").upper() != "NONE":
            checks.append(f"{CHECK_PREFIX} {line}")
    return checks[:MAX_CHECKS]


def result_text(plan: list, checks: list, rules_stopped: bool, notes: list = ()) -> str:
    """The result box: the checks and notes for the doctor first, then the plan that Populate saves."""
    top = (([RULES_STOPPED_CHECK] if rules_stopped else []) + list(checks) + list(notes)
           + ([] if plan else [NO_RULE_PLAN_CHECK]))
    return "\n".join(top + ([""] if top and plan else []) + plan)


def plan_from_result_box(text: str) -> str:
    """The plan in the result box: every line AI-Scribe wrote itself (status, checks) is left out."""
    lines = [line for line in (text or "").splitlines() if not line.startswith(STATUS_PREFIX)]
    return "\n".join(lines).strip()


def latest_aplan_query(demo_no) -> str:
    return (f"SELECT dataField, dateEntered FROM measurements WHERE demographicNo = {int(demo_no)} "
            "AND type = 'APLAN' ORDER BY dateEntered DESC, id DESC LIMIT 1")
