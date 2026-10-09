"""
Medication eForm (0.1Rfx) auto-fill logic used after a consult upload.
"""

import json
import re

from utils.rx_med_options import RX_MED_OPTIONS

RESET_BUTTON_TEXT = "new or dose change"

# Prescription body textarea on the medication eForm (filled after the reset button is clicked).
RX_FIELD = "druglist_generic"

# Medication actions the prescription body understands, plus common LLM synonyms for them.
ACTIONS = {
    "start": "start", "add": "start", "initiate": "start", "begin": "start",
    "increase": "increase", "titrate up": "increase", "uptitrate": "increase",
    "decrease": "decrease", "reduce": "decrease", "titrate down": "decrease", "downtitrate": "decrease",
    "stop": "stop", "discontinue": "stop", "hold": "stop",
}


def keyword_flags(text: str) -> dict:
    """Keyword check: looks for medication-change verbs, and for a lab action plus a lab test
    name. Fast but cannot tell whether the verb refers to a medication (e.g. 'start a stress
    test' would match). Returns {"medication": bool, "labs": bool}."""
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
    return {
        "medication": bool(re.search(med_pattern, t)),
        "labs": bool(re.search(lab_action_pattern, t) and re.search(lab_test_pattern, t)),
    }


def as_flag(value) -> bool:
    """Coerce an LLM JSON value to bool. bool("false") is True, so strings are matched explicitly."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "1")


def clean_med_changes(raw) -> list[dict]:
    """Keep only well-formed {"action", "name", "text"} entries from the LLM output, mapping
    action synonyms (e.g. "discontinue") onto start/increase/decrease/stop."""
    changes = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        action = ACTIONS.get(str(item.get("action", "")).strip().lower())
        name = str(item.get("name", "") or "").strip()
        text = str(item.get("text", "") or "").strip().rstrip(",").strip()
        if action is None or not name:
            continue
        if action != "stop" and not text:
            continue
        changes.append({"action": action, "name": name, "text": text})
    return changes


def build_med_prompt(plan: str) -> str:
    """Prompt asking for the plan's medication changes (in the eForm's wording) and a labs flag."""
    options = "\n".join(f"- {o}" for o in RX_MED_OPTIONS)
    return (
        "You are reviewing the PLAN section of a cardiology note. Return JSON in exactly this format:\n"
        '{"medication": [{"action": "start|increase|decrease|stop", "name": "drug name", '
        '"text": "prescription line"}], "labs": true or false}\n\n'
        '"medication" lists every medication the plan STARTS, STOPS, or CHANGES THE DOSE of. '
        "Continuing an existing medication unchanged does NOT count. Tests, imaging, procedures, "
        "lifestyle advice, and appointments do NOT count. Use an empty list if there are none. "
        "A switch from one drug to another is a stop of the old drug plus a start of the new one.\n"
        '- "name" is the drug name exactly as it begins "text" (e.g. "Furosemide" for '
        '"Furosemide 80 mg daily"); for "stop", the drug name as written in the plan.\n'
        '- "text" is the new prescription line (drug, dose, frequency). If the drug and dose match '
        "an entry in the STANDARD LINES below, copy that entry exactly, including any LU code. "
        "Otherwise write it as 'Drug dose frequency'. Never invent a dose that is not in the plan. "
        'For "stop", "text" may be empty.\n\n'
        '"labs" is true only if the plan orders or requests laboratory blood or urine tests (e.g. '
        "bloodwork, CBC, electrolytes, creatinine/eGFR, lipids, A1C, TSH, BNP, troponin, INR, "
        "urinalysis). Imaging, ECG, echo, Holter, and stress tests do NOT count.\n\n"
        f"STANDARD LINES:\n{options}\n\n"
        f"PLAN:\n{plan}\n\n"
        "Return ONLY the JSON object, with no other text."
    )


def parse_med_response(resp: str) -> dict:
    """Parse the model's reply into {"open": bool, "changes": list, "labs": bool}.
    "open" is True whenever the model reported any medication change, even one that could not
    be turned into a prescription line, so the form still opens (unfilled) for the clinician.
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
    raw = parsed.get("medication")
    return {
        "open": isinstance(raw, list) and len(raw) > 0,
        "changes": clean_med_changes(raw),
        "labs": as_flag(parsed.get("labs", False)),
    }


def extract_med_changes(plan: str, send_fn) -> dict:
    """One LLM call via `send_fn(prompt) -> str`; see parse_med_response for the result.
    Raises on a failed call or unusable output so the caller can fall back to keywords."""
    return parse_med_response(send_fn(build_med_prompt(plan)))


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
        flags = keyword_flags(scope)
        return {"medication": {"open": flags["medication"], "changes": []}, "labs": flags["labs"]}

    try:
        med = extract_med_changes(scope, send_fn)
    except Exception as e:
        print(f"eForm LLM gate failed, falling back to keyword: {e}")
        flags = keyword_flags(scope)
        med = {"open": flags["medication"], "changes": [], "labs": flags["labs"]}
    return {"medication": {"open": med["open"], "changes": med["changes"]}, "labs": med["labs"]}


def format_rx_lines(changes: list[dict]) -> str:
    """Render medication changes as prescription-body text in the eForm's own style
    ('Start X', 'Increase X to ...'), one per line, comma-separated like the form's menu."""
    lines = []
    for c in changes:
        action, name, text = c["action"], c["name"], c["text"]
        if action == "stop":
            lines.append(f"Stop {name}")
        elif action == "start":
            lines.append(f"Start {text}")
        else:
            verb = action.capitalize()
            if text.lower().startswith(name.lower()):
                lines.append(f"{verb} {name} to {text[len(name):].strip()}")
            else:
                lines.append(f"{verb} to {text}")
    return ",\n".join(lines) + ("," if lines else "")


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


def prepare_med_form(driver, wait, changes: list[dict] | None) -> dict:
    """On the medication eForm in the driver's current window: wait for it to finish loading
    (so its own onload scripts cannot overwrite what is filled in), click the reset button, then
    write the changes into the prescription body. Only the prescription body is filled: the
    current-meds list is written back to the chart on submit, so it is left for the clinician.
    Nothing is submitted. Returns {"reset": str, "fill": str | None, "rx_text": str | None}."""
    target = RESET_BUTTON_TEXT.lower()
    wait.until(lambda d: d.execute_script(_FIND_RESET_JS, target))
    reset = driver.execute_script(_CLICK_RESET_JS, target)
    fill = rx_text = None
    if changes and reset != "button-not-found":
        rx_text = format_rx_lines(changes)
        fill = driver.execute_script(_FILL_JS, RX_FIELD, rx_text)
    return {"reset": reset, "fill": fill, "rx_text": rx_text}
