"""
Medication eForm (0.1Rfx) auto-fill logic used after a consult upload.
"""

import json
import re

from utils.rx_med_options import RX_MED_OPTIONS
from utils.rx_med_update import MED_UPDATE_JS

RESET_BUTTON_TEXT = "new or dose change"

# Prescription body textarea on the medication eForm (filled after the reset button is clicked).
RX_FIELD = "druglist_generic"

# Medication actions the prescription body understands, plus common LLM synonyms for them.
# Matched on word stems so tense/form does not matter: the note prompt often writes the PLAN in
# the past tense ("I increased furosemide ...") and the model may echo "increased"/"started".
ACTION_STEMS = (
    ("titrate up", "increase"), ("uptitrat", "increase"), ("increas", "increase"),
    ("titrate down", "decrease"), ("downtitrat", "decrease"), ("decreas", "decrease"),
    ("reduc", "decrease"), ("lower", "decrease"),
    ("start", "start"), ("add", "start"), ("initiat", "start"), ("begin", "start"),
    ("began", "start"), ("commenc", "start"), ("new", "start"),
    ("stop", "stop"), ("discontinu", "stop"), ("hold", "stop"), ("held", "stop"),
    ("cease", "stop"), ("ceasing", "stop"),
)


def normalize_action(value) -> str | None:
    """Map an LLM action word ("Increased", "started", "discontinue", ...) to
    start/increase/decrease/stop, or None if it is not one of those."""
    word = str(value or "").strip().lower()
    for stem, action in ACTION_STEMS:
        if word.startswith(stem):
            return action
    return None


# Wording that makes a medication change a recommendation or a possibility rather than something
# prescribed at this visit; such changes must not open the medication form.
_NOT_ORDERED_PATTERN = (r"\b(recommend\w*|suggest\w*|consider\w*|could|may|might|would|should|"
                        r"if|unless|defer\w*|discuss\w*|benefit\w*|candidate|option\w*|"
                        r"in the future|at follow[- ]?up)\b")


def keyword_flags(text: str) -> dict:
    """Keyword check: looks for medication-change verbs, and for a lab action plus a lab test
    name. Fast but cannot tell whether the verb refers to a medication (e.g. 'start a stress
    test' would match). A medication verb only counts in a sentence that is not a recommendation,
    suggestion or condition ("I recommend starting ...", "consider ...", "if BP stays high ...").
    Returns {"medication": bool, "labs": bool}."""
    t = str(text or "").lower()
    med_pattern = (r"\b(start\w*|stop\w*|discontinu\w*|increas\w*|decreas\w*|reduc\w*|switch\w*|"
                   r"titrat\w*|initiat\w*|wean\w*|hold\b|add(ed|ing|s)?\b)")
    lab_action_pattern = (
        r"\b(order|ordered|obtain|obtained|check|checked|repeat|recheck|"
        r"measure|monitor|draw|complete|perform|do|get|request|requested)\w*\b"
    )
    lab_test_pattern = (
        r"\b(lab|labs|laboratory|bloodwork|blood\s+work|blood\s+test\w*|"
        r"blood\s+panel\w*|cbc|bmp|cmp|lipid\w*|cholesterol|"
        r"creatinine|egfr|electrolytes?|potassium|sodium|"
        r"glucose|a1c|hba1c|tsh|thyroid|lft\w*|"
        r"liver\s+function|renal\s+function|kidney\s+function|"
        r"bnp|nt-probnp|troponin|inr|ptt?|ferritin|iron\s+studies|"
        r"urinalysis|urine\s+test\w*)\b"
    )
    sentences = re.split(r"(?<=[.;!?])\s+|\n+", t)
    medication = any(re.search(med_pattern, s) and not re.search(_NOT_ORDERED_PATTERN, s) for s in sentences)
    return {
        "medication": medication,
        "labs": bool(re.search(lab_action_pattern, t) and re.search(lab_test_pattern, t)),
    }


def as_flag(value) -> bool:
    """Coerce an LLM JSON value to bool. bool("false") is True, so strings are matched explicitly."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "1")


def is_ordered(item) -> bool:
    """False when the model says the change is only recommended/suggested/conditional.
    A missing "ordered" field counts as ordered."""
    return not isinstance(item, dict) or "ordered" not in item or as_flag(item.get("ordered"))


def clean_med_changes(raw) -> list[dict]:
    """Keep only well-formed {"action", "name", "text"} entries from the LLM output, mapping
    action synonyms (e.g. "discontinue") onto start/increase/decrease/stop. Entries the model marks
    "ordered": false (recommendations, suggestions, conditional changes) are dropped."""
    changes = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        if not is_ordered(item):
            print(f"[med eForm] skipped recommendation (not prescribed at this visit): {item!r}")
            continue
        action = normalize_action(item.get("action"))
        name = str(item.get("name", "") or "").strip()
        text = str(item.get("text", "") or "").strip().rstrip(",").strip()
        if action is None or not name:
            print(f"[med eForm] dropped LLM entry with unusable action/name: {item!r}")
            continue
        if action != "stop" and not text:
            print(f"[med eForm] dropped LLM entry with no prescription line: {item!r}")
            continue
        changes.append({"action": action, "name": name, "text": text})
    return changes


def build_med_prompt(plan: str) -> str:
    """Prompt asking for the plan's medication changes (in the eForm's wording) and a labs flag."""
    options = "\n".join(f"- {o}" for o in RX_MED_OPTIONS)
    return (
        "You are reviewing the PLAN section of a cardiology note. Return JSON in exactly this format:\n"
        '{"medication": [{"action": "start|increase|decrease|stop", "name": "drug name", '
        '"text": "prescription line", "ordered": true or false}], "labs": {"required": true or false, '
        '"period": string (such as "7d", "2w", "1m", etc)} }\n\n'
        '"medication" lists every medication the plan STARTS, STOPS, or CHANGES THE DOSE of. '
        "Continuing an existing medication unchanged does NOT count. Tests, imaging, procedures, "
        "lifestyle advice, and appointments do NOT count. Use an empty list if there are none. "
        "A switch from one drug to another is a stop of the old drug plus a start of the new one.\n"
        '- "ordered" is true only if the plan actually makes or prescribes the change at this visit '
        '(e.g. "Start metoprolol 25 mg BID", "I increased furosemide to 80 mg daily", "Amlodipine '
        'was stopped"). It is false if the change is only recommended, suggested, advised for someone '
        'else to do, conditional, or for the future (e.g. "I recommend starting ...", "consider '
        'increasing ...", "may benefit from ...", "if BP remains high, start ...", "defer to family '
        'doctor", "could be started at follow-up").\n'
        '- "name" is the drug name exactly as it begins "text" (e.g. "Furosemide" for '
        '"Furosemide 80 mg daily"); for "stop", the drug name as written in the plan.\n'
        '- "text" is the new prescription line (drug, dose, frequency). If the drug and dose match '
        "an entry in the STANDARD LINES below, copy that entry exactly, including any LU code. "
        "Otherwise write it as 'Drug dose frequency'. Never invent a dose that is not in the plan. "
        'For "stop", "text" may be empty.\n\n'
        '"labs"["required"] is true only if the plan orders or requests laboratory blood or urine tests (e.g. '
        "bloodwork, CBC, electrolytes, creatinine/eGFR, lipids, A1C, TSH, BNP, troponin, INR, "
        "urinalysis). Imaging, ECG, echo, Holter, and stress tests do NOT count.\n\n"
        'If "labs"["required"] is true, then "labs"["period"] should represent when the lab work is requested '
        'to be completed. For example, if the note says "complete in 2 months", the value should be "2m". '
        'If "labs"["required"] is false, "labs"["period"] should simply be null.\n\n'
        f"STANDARD LINES:\n{options}\n\n"
        f"PLAN:\n{plan}\n\n"
        "Return ONLY the JSON object, with no other text."
    )


def parse_med_response(resp: str) -> dict:
    """Parse the model's reply into {"open": bool, "changes": list, "labs": bool, "lab_period": str | None}.
    "open" is True whenever the model reported a medication change prescribed at this visit, even
    one that could not be turned into a prescription line, so the form still opens (unfilled) for
    the clinician. Changes that are only recommended/suggested do not open it.
    Raises ValueError on output with no usable JSON object."""
    resp = str(resp or "").strip()
    match = re.search(r"\{.*\}", resp, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON in response: {resp[:200]!r}")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        # Some models write Python-style True/False; the response is not lowercased as a whole
        # because that would also lowercase the drug names.
        try:
            parsed = json.loads(re.sub(r"\b(True|False)\b", lambda m: m.group(1).lower(), match.group(0)))
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON in response: {resp[:200]!r}") from e
    if not isinstance(parsed, dict):
        raise ValueError(f"no usable JSON in response: {resp[:200]!r}")
    
    # Medication changes
    raw = parsed.get("medication")
    ordered = [item for item in raw if is_ordered(item)] if isinstance(raw, list) else []

    # Lab requirements
    labs_data = parsed.get("labs")
    if isinstance(labs_data, dict):
        labs_required = as_flag(labs_data.get("required", False))
        lab_period = labs_data.get("period") if labs_required else None

        if lab_period is not None:
            lab_period = str(lab_period).strip() or None
    else:
        # Handle older version where labs was simply a boolean flag
        labs_required = as_flag(labs_data)
        lab_period = None

    return {
        # Recommendations alone do not open the form.
        "open": len(ordered) > 0,
        "changes": clean_med_changes(raw),
        "labs": labs_required,
        "lab_period": lab_period
    }


def extract_med_changes(plan: str, send_fn) -> dict:
    """One LLM call via `send_fn(prompt) -> str`; see parse_med_response for the result.
    Raises on a failed call or unusable output so the caller can fall back to keywords."""
    prompt = build_med_prompt(plan)
    print(f"[med eForm] calling LLM ({len(plan)} chars of PLAN)")
    resp = send_fn(prompt)
    print(f"[med eForm] LLM replied: {str(resp)[:300]!r}")
    return parse_med_response(resp)


def analyze_plan_for_eforms(scope: str, send_fn, mode: str = "llm") -> dict:
    """Work out which eForms to open after a consult upload and what to pre-fill them with.
    `scope` is the PLAN section (or the whole consult if no PLAN heading was found).
    `mode` is "llm" or "keyword".

    Returns
    -------
    {"medication": {"open": bool, "changes": [{"action", "name", "text"}, ...]},
     "labs": bool}
    "changes" may be empty while "open" is True (e.g. keyword fallback), in which case the
    medication form is opened without pre-filling."""
    scope = str(scope or "").strip()
    if not scope:
        return {"medication": {"open": False, "changes": []}, "labs": False}

    if mode != "llm":
        print(f"[med eForm] mode={mode!r}: keyword check only, no LLM call, form will not be pre-filled")
        flags = keyword_flags(scope)
        return {"medication": {"open": flags["medication"], "changes": []}, "labs": flags["labs"]}

    try:
        med = extract_med_changes(scope, send_fn)
    except Exception as e:
        print(f"eForm LLM gate failed, falling back to keyword: {e}")
        flags = keyword_flags(scope)
        med = {"open": flags["medication"], "changes": [], "labs": flags["labs"]}
    return {
        "medication": {"open": med["open"], "changes": med["changes"]}, 
        "labs": med["labs"], 
        "lab_period": med["lab_period"]
    }


def format_rx_lines(changes: list[dict]) -> str:
    """Render medication changes as prescription-body text in the form's own style: each entry
    followed by ", " exactly as the form's drug menu inserts it.

    New meds are written as the regimen ("Metoprolol 25 mg BID", as the form's drug menu inserts
    them), dose changes as "Increase/Decrease X to <dose>" (as the form's increase/decrease dose
    checkboxes write them), and stopped meds as "Stop X". The form opened by prepare_med_form gets a
    fixed "Update Med List" (utils/rx_med_update.py) that turns these into CURRENT MEDS entries holding
    only the updated regimen ("Furosemide 80 mg daily") and removes stopped meds."""
    return "".join(f"{e}, " for e in rx_entries(changes))


def rx_entries(changes: list[dict]) -> list[str]:
    """The prescription-body entries for `changes`, before joining (see format_rx_lines)."""
    entries = []
    for c in changes:
        action, name, text = c["action"], c["name"], c["text"]
        if action == "stop":
            entries.append(f"Stop {name}")
        elif action == "start":
            entries.append(text)
        else:
            entries.append(f"{action.capitalize()} {_drug_to_dose(text)}")
    return entries


def _drug_to_dose(text: str) -> str:
    """'Furosemide 80 mg daily' -> 'Furosemide to 80 mg daily': "to" goes before the dose, i.e. the
    first number ("Diltiazem CD 240 mg daily" -> "Diltiazem CD to 240 mg daily"). Lines without a
    number are left as they are."""
    m = re.match(r"^(.*?\D)\s+(\d.*)$", text)
    if not m:
        return text
    return f"{m.group(1)} to {m.group(2)}"


_FIND_RESET_JS = ("var t=arguments[0];"
                  "return document.readyState==='complete' && "
                  "Array.from(document.querySelectorAll('input,button,a')).some(function(x){"
                  "return (x.value||x.textContent||'').trim().toLowerCase().indexOf(t)>=0;});")
_CLICK_RESET_JS = ("var t=arguments[0];"
                   "var b=Array.from(document.querySelectorAll('input,button,a')).find(function(x){"
                   "return (x.value||x.textContent||'').trim().toLowerCase().indexOf(t)>=0;});"
                   "if(b){b.click();return (b.tagName+' '+(b.value||b.textContent||'')).trim().slice(0,60);}"
                   "return 'button-not-found';")
_FILL_JS = ("var el=document.getElementById(arguments[0]);"
            "if(!el){return 'field-not-found';}"
            "el.value=arguments[1];return 'filled';")


# Scripts run through execute_script are wrapped in a function, so the declaration has to be
# assigned to window explicitly for the button's onclick="med_update();" to find it.
_PATCH_MED_UPDATE_JS = (MED_UPDATE_JS + "\nwindow.med_update = med_update;\n"
                        "window.med_update.aiScribeFixed = true;\nreturn 'fixed version installed';")


def prepare_med_form(driver, wait, changes: list[dict] | None) -> dict:
    """On the medication eForm in the driver's current window: wait for it to finish loading
    (so its own onload scripts cannot overwrite what is filled in), click the reset button, then
    write the changes into the prescription body. Only the prescription body is filled: the
    current-meds list is written back to the chart on submit, so it is left for the clinician.
    It also swaps in the fixed "Update Med List" (utils/rx_med_update.py) for this window only,
    so when the clinician clicks it, CURRENT MEDS is updated with the new regimens in the same format
    and stopped meds are removed. The form template in Oscar is not changed.
    Nothing is submitted.
    Returns {"reset": str, "fill": str | None, "rx_text": str | None, "update_med_list": str}."""
    target = RESET_BUTTON_TEXT.lower()
    print(f"[med eForm] waiting for reset button in window titled {driver.title!r} ({driver.current_url[:80]})")
    wait.until(lambda d: d.execute_script(_FIND_RESET_JS, target))
    reset = driver.execute_script(_CLICK_RESET_JS, target)
    update_med_list = driver.execute_script(_PATCH_MED_UPDATE_JS)
    print(f"[med eForm] Update Med List -> {update_med_list}")
    fill = rx_text = None
    if not changes:
        print("[med eForm] no changes to fill (LLM found none it could turn into prescription lines)")
    if changes and reset != "button-not-found":
        rx_text = format_rx_lines(changes)
        fill = driver.execute_script(_FILL_JS, RX_FIELD, rx_text)
    return {"reset": reset, "fill": fill, "rx_text": rx_text, "update_med_list": update_med_list}
