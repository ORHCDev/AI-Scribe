"""
"EBM" prompt: the clinic's EBM eForm (rules written in JavaScript) is run in a hidden frame and its action plan is
shown unchanged, with points for the doctor to check that an LLM finds by comparing it with the patient's chart.
Populate saves the plan (without those points) to the APLAN measurement by submitting the EBM eForm, the same way
it is saved by hand. The EBM form never opens on screen.
"""

import re

from utils.referral_requisition import fill_prompt

EBM_FORM_FID = 757
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

List at most 3 points, and only points that would change what the doctor does, most important first:
- a problem in the chart the plan does not address (e.g. atrial fibrillation with no anticoagulant in the
  medications, a test that is due, an untreated condition);
- a safety concern with the plan or the current medications (e.g. a slow heart rate on a beta-blocker, an allergy
  to a recommended drug, an abnormal lab value);
- missing or old chart data that an item of the plan depends on.
Start each point with NEW or CHECK:
- NEW for a problem in the chart the plan does not address, or a safety concern with the plan or the current
  medications. Write it as one more item of the action plan, in the plan's own style: start with "Consider",
  "Assess" or "Check", then what to do and why, in concise wording (BP, HR, LDL, AF, f/u, mo, yr are fine), e.g.
  "Consider lipid-lowering therapy for Lp(a) 296 and premature CAD in the family" or "Consider reducing bisoprolol
  for HR 48". Never give a drug dose. The item must be one clear, logical sentence: what to do, then why.
- CHECK for missing or old chart data that an item of the plan depends on: one sentence that says what is missing,
  e.g. "No creatinine in the chart for the planned Ramipril".
A point that only describes the chart is not a point.
Do not list normal results, or a test or treatment the plan already asks for.
Never write a NEW point about a drug or test the plan already mentions (e.g. the plan says OAC is required: no point
about starting or assessing OAC), unless it is a safety concern about it, such as its dose or a contraindication.
Never write a CHECK about old or missing data for a test the plan already asks for: that test will update it.
Write one point per problem: two findings about the same problem (e.g. a positive stress test and ischemia on a stress
echo) are one point.
Items of the plan that repeat or conflict with each other are handled when the plan is written: do not list them.
After NEW or CHECK, give the names of the chart fields the point comes from in square brackets, separated by ";"
and written exactly as they appear before the ":" in the chart, then the point with their value or date, e.g.
"NEW [Last Holter; Current Medications] Consider anticoagulation for AF on the last Holter (2025-03-14)" or
"NEW [Heart Rate; Current Medications] Consider reducing bisoprolol for HR 48". Only flag a
value as abnormal if it is outside the normal range. Fewer points are better than doubtful ones: leave out anything
you are not sure of. Never write vague points such as "monitor ..." or "continue current medications". Do not write
the patient's name.
Reply with one point per line and nothing else. If there is nothing worth checking, reply with NONE."""

FORMAT_PROMPT = """Rewrite this cardiology action plan in the clinic's style. Getting the content right comes first:
every item of the plan must still be there with the same meaning, nothing wrong and nothing left out.
- Lines ending with a tag such as [N1] are items added from the chart. They are part of the plan like every other
  item: the whole plan, old and new items together, is rewritten as one. Keep the tag at the end of the line that
  has that item (when two items become one line, that line keeps the tag); never write a tag on any other line.
- Keep every item, except that two items asking for the same thing become one, and of two items that conflict
  (e.g. two different ischemia tests) keep the one that fits better. Leave out nothing else.
- Keep each drug name, dose, test and time exactly. Do not add any test, drug, dose or time.
- Keep the name of every test: "s echo" means stress echo, so write "stress echo". Never turn one test into
  another (e.g. a stress echo into an echo, or a stress test into a stress echo).
- Keep how strong each item is: "Consider" stays "Consider", "Recommend" stays "Recommend".
- When an item gives the purpose of a test, write the purpose and the test as one item, joined with "with":
  "Assess <purpose> with <test> <time>", e.g. "Assess exertional chest tightness with an echo at the next
  opportunity". Never split them with ";" or write the test as a separate item.
- If an item gives no purpose, do not add one: "Assess with an echo in 12 mo" stays as it is. Never add a reason,
  diagnosis or finding that the plan does not state.
- One item per line, plain text, no bullets. Start each item that asks for something with a verb such as "Assess",
  "Check", "Consider", "Recommend" or "Start", never with "We will". An item that states a finding or a risk
  (e.g. "High risk of heart failure with preserved ejection fraction") stays a statement; do not add "Assess".
- Each item must read as one clear, logical sentence that another doctor understands on its own: what to do, then
  the finding or reason it is for, in that order. Do not join unrelated things in one item, and do not leave a
  sentence half-finished or with words in the wrong order.
- The final plan must have no repeated item, nothing wrong, and no sentence that does not read clearly.
- Use concise wording (BP, HR, LDL, AF, HF, f/u, mo, yr are fine) and try to stay within {MAX} characters in
  total, but readability comes before length: keep each item's verb (e.g. "Assess", "Send for", "Start") and every
  time written in words (e.g. "at the next opportunity", "next available", "today"). Never leave out an item, cut it
  to a few words, or change its meaning to fit.

PLAN:
{PLAN}

Reply with the rewritten plan only."""

# The editable prompts (Prompt window: EBM -> Checks / Format); these are the defaults.
PROMPT_SECTIONS = {"Checks": CHECKS_PROMPT, "Format": FORMAT_PROMPT}

# Lines of the result box written by AI-Scribe itself (status and checks for the doctor), never saved to APLAN.
STATUS_PREFIX = "[EBM]"
CHECK_PREFIX = f"{STATUS_PREFIX} Check:"
MAX_CHECKS = 3
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


# New items (from the checks) go into the plan tagged [N1], [N2], ... so that after the LLM rewrites the whole plan,
# each one's chart fields can be shown under the line that has it.
_TAG = r"\s*[\[(]N(\d+)[\])]"


def tagged_items(new_items: list) -> list:
    """The new items' sentences tagged [N1], [N2], ... (in order), to go into the plan."""
    return [f"{sentence} [N{i}]" for i, (sentence, _) in enumerate(new_items, 1)]


def untag(text: str) -> str:
    return re.sub(_TAG, "", text or "")


def saved_length(plan: str) -> int:
    """How many characters of APLAN the plan takes once saved (without the [N1] tags)."""
    return len(untag(plan).replace("\r\n", "\n").replace("\n", "\r\n"))


def fits(lines: list) -> bool:
    return saved_length("\n".join(lines)) <= APLAN_MAX_CHARS


def build_format_prompt(lines: list, template: str | None = None) -> str:
    return fill_prompt(template or FORMAT_PROMPT, MAX=str(APLAN_MAX_CHARS), PLAN="\n".join(lines))


def _numbers(text: str) -> set:
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


# Tests named in a plan, so a rewording that turns one test into another (e.g. "s echo" into "echo") is caught.
# Stress echo is matched (and removed) first, so its "echo" and "stress" are not counted again.
_STRESS_ECHO = r"\b(?:s\.?\s?echo\w*|stress[\s-]*echo\w*)"
_TESTS = {"echo": r"\b(?:echo\w*|tte)\b", "ecg": r"\b(?:ecg|ekg|electrocardiog\w*)\b", "holter": r"\bholter\b",
          "stress test": r"\b(?:stress[\s-]*test\w*|treadmill|exercise[\s-]*test\w*|est)\b",
          "mibi": r"\b(?:mibi|sestamibi|persantine|nuclear|myocardial perfusion)\b",
          "ct": r"\b(?:ct|cta|calcium scor\w*)\b", "mri": r"\b(?:mri|cmr|cardiac magnetic)\b",
          "pyrophosphate": r"\bpyrophosphate\b"}


def _tests(text: str) -> set:
    text = (text or "").lower()
    found = {"stress echo"} if re.search(_STRESS_ECHO, text) else set()
    text = re.sub(_STRESS_ECHO, " ", text)
    return found | {test for test, pattern in _TESTS.items() if re.search(pattern, text)}


# Times written in words ("at the next opportunity", "today"): a rewording or shortening that drops one is not used.
_TIME_WORDS = (r"\b(next (?:opportunity|available|visit|appointment)|today|now|asap|as soon as possible|urgent\w*|"
               r"(?:coming|next few) (?:days|weeks|months|year)|annual\w*|yearly|every year)\b")


def _time_phrases(text: str) -> set:
    return {" ".join(m.group(0).lower().split()) for m in re.finditer(_TIME_WORDS, text or "", re.IGNORECASE)}


# Drugs a NEW point may repeat from the plan (tests are matched with _tests).
_DRUGS = {"oac": r"\b(?:oac|doac|noac|anticoag\w*|apixaban|eliquis|rivaroxaban|xarelto|edoxaban|lixiana|dabigatran|"
                 r"pradaxa|warfarin|coumadin)\b",
          "lipid": r"\b(?:statins?|lipid[- ]lowering|rosuvastatin|crestor|atorvastatin|lipitor|ezetimibe|pcsk9\w*|"
                   r"repatha|praluent)\b",
          "sglt2": r"\b(?:sglt-?2\w*|dapa|dapagliflozin|forxiga|empagliflozin|jardiance)\b",
          "aspirin": r"\b(?:asa|aspirin)\b"}
# A NEW point about a drug or test the plan has is kept only as a safety concern about it.
_SAFETY_WORDS = (r"\b(reduc\w*|lower\w*|adjust\w*|alternative\w*|stop\w*|hold\w*|avoid\w*|switch\w*|dose|dosing|"
                 r"contraindicat\w*|caution\w*|bleed\w*|interact\w*|allerg\w*)\b")
# A CHECK about old or missing data for a test the plan asks for is dropped: the test will update it.
_STALE_WORDS = r"\b(outdated|out of date|old|older|missing|no recent|not recent|due|overdue|from (?:19|20)\d{2})\b"


def _topics(text: str) -> set:
    text = (text or "").lower()
    return _tests(text) | {drug for drug, pattern in _DRUGS.items() if re.search(pattern, text)}


def drop_repeats(checks: list, new_items: list, plan_text: str) -> tuple[list, list]:
    """The checks and new items without those repeating the plan: a NEW item about a drug or test the plan already
    has (e.g. "Assess need for OAC" when the plan says OAC is required), unless it is a safety concern about it,
    and a CHECK about old or missing data for a test the plan asks for ("Echo from 2000 is outdated")."""
    plan_topics, plan_tests = _topics(plan_text), _tests(plan_text)
    items = [(sentence, fields) for sentence, fields in new_items
             if not (_topics(sentence) & plan_topics) or re.search(_SAFETY_WORDS, sentence, re.IGNORECASE)]
    kept = []
    for check in checks:
        sentence = re.sub(r"\s*\(from: [^)]*\)$", "", check[len(CHECK_PREFIX):])
        if not (_tests(sentence) & plan_tests and re.search(_STALE_WORDS, sentence, re.IGNORECASE)):
            kept.append(check)
    if len(items) < len(new_items) or len(kept) < len(checks):
        print(f"[EBM] left out {len(new_items) - len(items)} new items and {len(checks) - len(kept)} checks "
              "that repeat the plan")
    return kept, items


def length_note(plan_lines: list) -> list:
    """A note for the doctor when the plan is longer than the 255 characters Oscar keeps of APLAN."""
    length = saved_length("\n".join(plan_lines))
    if length <= APLAN_MAX_CHARS:
        return []
    return [f"{CHECK_PREFIX} The plan is {length} characters; Oscar keeps only the first {APLAN_MAX_CHARS} of APLAN."]


CUT_HEADER = f"{STATUS_PREFIX} ───── Full plan before the cut at {APLAN_MAX_CHARS} characters (not saved) ─────"


def cut_to_fit(plan_lines: list) -> tuple[list, list]:
    """(lines saved, lines cut off): whole lines from the top while the plan fits in the 255 characters Oscar keeps
    of APLAN (at least the first line, which Oscar then cuts itself)."""
    kept = []
    for line in plan_lines:
        if not fits(kept + [line]):
            break
        kept.append(line)
    kept = kept or list(plan_lines[:1])
    return kept, list(plan_lines[len(kept):])


def cut_note(plan_lines: list, cut: list) -> list:
    """A note for the doctor when lines were cut off to fit APLAN."""
    if not cut:
        return []
    return [f"{CHECK_PREFIX} The plan was {saved_length(chr(10).join(plan_lines))} characters; Oscar keeps only "
            f"{APLAN_MAX_CHARS} of APLAN, so the last {len(cut)} lines are cut off. The full plan is shown at the "
            "bottom (not saved); to keep a cut line, copy it into the plan without its [EBM] prefix and delete another."]


def format_plan(lines: list, formatted_reply: str | None) -> tuple[list, list]:
    """(plan lines, notes for the doctor). The LLM's rewording (FORMAT_PROMPT) is used when it has no number (dose,
    time) and no test the rules' plan did not have (it may drop a repeated or conflicting item); otherwise the rules'
    wording is used. The only note is one saying the plan is longer than Oscar keeps."""
    if not lines:
        return [], []
    formatted = [concise_line(" ".join(line.split()))
                 for line in clean_action_plan(formatted_reply or "").splitlines() if line.strip()]
    new, old = untag("\n".join(formatted)), untag("\n".join(lines))
    if (formatted and _numbers(new) <= _numbers(old) and _tests(new) <= _tests(old)
            and _time_phrases(old) <= _time_phrases(new)):
        return formatted, length_note(formatted)
    if formatted:
        print("[EBM] the LLM's rewording added a dose, time or test, or dropped a time; using the rules' wording")
    return lines, length_note(lines)


SHORTEN_PROMPT = """This cardiology action plan is {LENGTH} characters, but Oscar keeps only {MAX} (each line break
counts as 2). Shorten it to at most {MAX} characters.
- Keep every item and its meaning. Keep each drug name, dose, test and time exactly (the same numbers), every
  time written in words (e.g. "at the next opportunity", "next available", "today"), each item's verb (e.g.
  "Assess", "Send for", "Start"), and "Consider" / "Recommend" as they are. Do not add anything, and never cut an
  item to a few words.
- Shorten only the wording: abbreviations (BP, HR, LDL, AF, HF, f/u, mo, yr, wk), no filler words, no "the" or "a"
  where the meaning stays clear.
- Each item must read as one clear, logical sentence that another doctor understands on its own: what to do, then
  the finding or reason it is for, in that order. Do not join unrelated things in one item, and do not leave a
  sentence half-finished or with words in the wrong order.
- One item per line, plain text, no bullets. Keep each tag such as [N1] at the end of the line that has its item.
- The shortened plan must have no repeated item, nothing wrong, and no sentence that does not read clearly.

PLAN:
{PLAN}

Reply with the shortened plan only."""


def build_shorten_prompt(lines: list) -> str:
    plan = "\n".join(lines)
    return fill_prompt(SHORTEN_PROMPT, LENGTH=str(saved_length(plan)), MAX=str(APLAN_MAX_CHARS), PLAN=plan)


def shorter_plan(lines: list, reply: str | None) -> list:
    """The LLM's shortened plan (SHORTEN_PROMPT) when it is shorter and keeps exactly the numbers (doses, times) and
    tests of the plan and every time written in words, so no item was dropped or changed; otherwise the plan as it
    was."""
    shortened = [concise_line(" ".join(line.split()))
                 for line in clean_action_plan(reply or "").splitlines() if line.strip()]
    new, old = untag("\n".join(shortened)), untag("\n".join(lines))
    if (shortened and saved_length(new) < saved_length(old)
            and _numbers(new) == _numbers(old) and _tests(new) == _tests(old)
            and _time_phrases(old) <= _time_phrases(new)):
        return shortened
    if shortened:
        print("[EBM] the shortened plan was not shorter or changed a dose, time or test; keeping the longer plan")
    return lines


def rule_plan_lines(rule_plan: str) -> list:
    """The rules' action plan one item per line, without "We will" openings, <br> tags, blank lines or repeats."""
    lines, seen = [], set()
    for line in re.sub(r"<br\s*/?>", "\n", rule_plan or "", flags=re.IGNORECASE).splitlines():
        line = concise_line(" ".join(line.split()))
        if line and line.lower() not in seen:
            seen.add(line.lower())
            lines.append(line)
    return lines


def _field_key(name: str) -> str:
    return " ".join(str(name).rstrip(":").split()).lower()


def check_fields(line: str, chart: list | None) -> tuple:
    """A point's "[Field; Field] sentence" split into the sentence and the named fields that are in the chart,
    written as the chart writes them. Without a chart every named field is kept."""
    match = re.match(r"^\[([^\]]*)\]\s*", line)
    if not match:
        return line, []
    names = [n.strip() for n in match.group(1).split(";") if n.strip()]
    if chart is not None:
        labels = {_field_key(label): str(label).rstrip(":").strip() for label, *_ in chart}
        names = [labels[_field_key(n)] for n in names if _field_key(n) in labels]
    return line[match.end():].strip(), list(dict.fromkeys(names))


def _source(fields: list) -> str:
    return "; ".join(fields) if fields else "no chart field named"


def points_from_reply(text: str, chart: list | None = None) -> tuple[list, list]:
    """(checks, new items) from the LLM's points, at most MAX_CHECKS in all; none when it replied NONE.
    A "NEW" point (a problem the plan does not address, or a safety concern), written as a plan item, becomes a
    (sentence, chart fields) new item, shown in the plan and saved. Any other point ("CHECK": missing or old data,
    or no type) is a CHECK_PREFIX line for the doctor, ending with the chart fields it comes from, never saved."""
    checks, items = [], []
    for line in clean_action_plan(text).splitlines():
        line = re.sub(r"^\s*(\[EBM\]\s*)?check:\s*", "", line, flags=re.IGNORECASE).strip()
        kind = re.match(r"^(NEW|CHECK)\b\s*:?\s*", line, flags=re.IGNORECASE)
        is_new = bool(kind) and kind.group(1).upper() == "NEW"
        line = line[kind.end():].strip() if kind else line
        if not line or line.strip(".").upper() == "NONE":
            continue
        sentence, fields = check_fields(line, chart)
        if not sentence or len(checks) + len(items) >= MAX_CHECKS:
            continue
        if is_new:
            items.append((concise_line(sentence), fields))
        else:
            checks.append(f"{CHECK_PREFIX} {sentence} (from: {_source(fields)})")
    return checks, items


def checks_from_reply(text: str, chart: list | None = None) -> list:
    """The checks of points_from_reply (the new items left out)."""
    return points_from_reply(text, chart)[0]


ORIGINAL_HEADER = f"{STATUS_PREFIX} ───── Rules' original wording (for comparison, not saved) ─────"


def result_text(plan: list, checks: list, rules_stopped: bool, notes: list = (), original: list = (),
                new_items: list = (), cut: list = ()) -> str:
    """The result box: the checks and notes for the doctor first, then the plan that Populate saves (old and new
    items together), each line with a new item's tag followed by that item's chart fields (not saved), then the
    original wording when the LLM reworded it (every [EBM] line is left out by Populate). The fields of a new item
    whose tag the LLM dropped are listed after the plan. When lines were cut off to fit APLAN, the plan shown is the
    cut one, and the full plan (with the cut lines) follows as [EBM] lines, not saved."""
    top = (([RULES_STOPPED_CHECK] if rules_stopped else []) + list(checks) + list(notes)
           + ([] if plan else [NO_RULE_PLAN_CHECK]))
    def with_sources(lines, prefix=""):
        shown.clear()
        out = []
        for line in lines:
            out.append(prefix + untag(line).strip())
            for number in dict.fromkeys(int(n) for n in re.findall(_TAG, line)):
                if 1 <= number <= len(new_items) and number not in shown:
                    shown.add(number)
                    out.append(f"{STATUS_PREFIX}   from: {_source(new_items[number - 1][1])}")
        return out

    shown = set()
    full = [CUT_HEADER] + with_sources(list(plan) + list(cut), f"{STATUS_PREFIX}   ") if cut else []
    body = with_sources(plan)
    tagged = {int(n) for line in list(plan) + list(cut) for n in re.findall(_TAG, line)}
    body += [f"{STATUS_PREFIX}   from (added item): {_source(fields)}"
             for number, (_, fields) in enumerate(new_items, 1) if number not in tagged and plan]
    plain = [untag(line).strip() for line in list(plan) + list(cut)]
    bottom = [ORIGINAL_HEADER] + [f"{STATUS_PREFIX}   {line}" for line in original] if original and plain != list(original) else []
    bottom = full + ([""] if full and bottom else []) + bottom
    return "\n".join(top + ([""] if top and body else []) + body + ([""] if bottom else []) + bottom)


def plan_from_result_box(text: str) -> str:
    """The plan in the result box: every line AI-Scribe wrote itself (status, checks) is left out."""
    lines = [line for line in (text or "").splitlines() if not line.startswith(STATUS_PREFIX)]
    return "\n".join(lines).strip()


def latest_aplan_query(demo_no) -> str:
    return (f"SELECT dataField, dateEntered FROM measurements WHERE demographicNo = {int(demo_no)} "
            "AND type = 'APLAN' ORDER BY dateEntered DESC, id DESC LIMIT 1")
