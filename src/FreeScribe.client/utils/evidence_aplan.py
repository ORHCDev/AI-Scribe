"""
Evidence workflow -> APLAN2 eForm (initial version)
"""

import re

APLAN2_FORM_FID = 0
APLAN2_FORM_NAME = "0.1APLAN2p"
APLAN2_FIELD_ID = "APLAN2"
APLAN2_SUBMIT_NAME = "SubmitButton"

APLAN2_MAX_CHARS = 255


DEFAULT_SUMMARY_PROMPT = """\
Write a concise recommendation-only note for the patient's chart from the answer below.

ANSWER:
{answer}

The summary is saved as an APLAN2 action-plan note.
- State only the recommendation: what to do for the patient.
- Leave out the supporting evidence, study names, effect sizes, numbers from
  trials, caveats and citations; the chat answer keeps those.
- Use the patient's relevant context from the answer when it changes the
  recommendation. Do not add any fact that is not in the answer.
- Plain text only: no markdown, bullets, headings or patient name.
- Stay within {MAX} characters.
Reply with the summary only."""


def build_summary_prompt(answer: str, template: str | None = None) -> str:
    """The summary prompt with the evidence answer and the character limit."""
    return (template or DEFAULT_SUMMARY_PROMPT).format(
        answer=(answer or "").strip() or "(no answer)",
        MAX=str(APLAN2_MAX_CHARS),
    )


def clean_summary(text: str) -> str:
    """The LLM's summary as one plain-text line, without code fences, markdown
    marks, bullets or numbering."""
    text = re.sub(r"```\w*", "", text or "")
    text = text.replace("**", "").replace("__", "")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(#+|[-*•]|\d+[.)])\s+", "", line).strip()
        if line:
            lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def fit_summary(text: str, max_chars: int = APLAN2_MAX_CHARS) -> str:
    """The cleaned summary, cut at a word boundary when it is over `max_chars`."""
    summary = clean_summary(text)
    if max_chars <= 0 or len(summary) <= max_chars:
        return summary[:max_chars] if max_chars > 0 else ""
    if max_chars <= 3:
        return summary[:max_chars]
    cut = summary[:max_chars - 3].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}..." if cut else summary[:max_chars]


def latest_aplan2_query(demo_no) -> str:
    return (f"SELECT dataField, dateEntered FROM measurements WHERE demographicNo = {int(demo_no)} "
            "AND type = 'APLAN2' ORDER BY dateEntered DESC, id DESC LIMIT 1")


APLAN2_FRAME_JS = """
var url = arguments[0], fieldId = arguments[1], text = arguments[2], submitName = arguments[3];
var done = arguments[arguments.length - 1];
var frame = document.createElement("iframe");
frame.style.display = "none";
var loads = 0, finished = false;
var finish = function (result) {
    if (finished) { return; }
    finished = true;
    setTimeout(function () { frame.remove(); }, 0);
    done(result);
};
frame.onload = function () {
    loads += 1;
    if (loads > 1) { return finish({saved: true}); }
    var d = frame.contentDocument;
    var field = d.getElementById(fieldId) || d.querySelector('[name="' + fieldId + '"]');
    if (!field) { return finish({missing: fieldId}); }
    field.removeAttribute("disabled");
    field.value = text;
    var submit = d.querySelector('input[type=submit][name="' + submitName + '"]')
        || d.getElementById(submitName) || d.querySelector('input[type=submit]');
    if (!submit) { return finish({missing: submitName}); }
    submit.click();
    setTimeout(function () { if (loads < 2) { finish({saved: false}); } }, 60000);
};
frame.src = url;
document.body.appendChild(frame);
"""
