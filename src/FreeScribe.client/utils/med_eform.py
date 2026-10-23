"""
Medication eForm (0.1Rfx) auto-fill logic used after a consult upload.
"""

import json
import re

from utils.rx_med_options import RX_MED_OPTIONS
from utils.rx_med_update import MED_UPDATE_JS
from utils.lab_analysis import analyze_plan_for_labs

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
        "requisition": False
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
    """Prompt asking for the plan's medication changes (in the eForm's wording), whether labs are required, and
    whether a requisition is required and, if so, what consultations and diagnostics to perform."""
    options = "\n".join(f"- {o}" for o in RX_MED_OPTIONS)
    return (
        "You are reviewing the PLAN section of a cardiology note. Return JSON in exactly this format:\n"
        '{"medication": [{"action": "start|increase|decrease|stop", "name": "drug name", '
        '"text": "prescription line", "ordered": true or false}], "labs": {"required": true or false, '
        '"period": string (such as "7d", "2w", "1m", etc)}, "requisition": {"period": string (such as "7d", '
        '"2w", "1m", etc) | null, "period_reason": str, "consult": true or false, "ecg": true or false, '
        '"echo": true or false, "contrastecho": true or false, "stecho": true or false, "contrast": true or false, '
        '"est": true or false, "holter": "24h" | "48h" | "72h" | "2w" | null} }\n\n'
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
        '"labs"["required"] is true if the plan orders or requests laboratory blood or urine tests (including, '
        ' but not limited to: bloodwork, CBC, electrolytes (including potassium and magnesium), creatinine/eGFR, '
        'lipids, A1C, TSH, BNP, troponin, INR, urinalysis, LP(a)/lipoprotein A), or indicates a requirement for '
        '"work up". Imaging, ECG, echo, Holter, and stress tests do NOT count. Reviewing, discussing or reporting the '
        'results of previous tests is NOT a request, and neither is only mentioning a diagnosis.\n\n'
        '"labs"["required"] should also be true if any of the following drugs are started/stopped/increased/decreased, '
        'so that a lab can be performed to follow up: amiodarone, digoxin, thiazide medication (HCTZ/hydrochlorothiazide, '
        'Indapamide, chlorthalidone), SGLT 2 medication (dapagliflozin/Forxiga, Canagliflozin, empagliflozin/Jardiance), '
        'statin (lipitor/atorvastatin, Crestor/rosuvastatin, Zocor/simvastatin, Pravachol/pravastatin, lovastatin), '
        'ACe inhibitors or ARBs (Ramipril/Altace, Coversyl/perindopril, Mavik/Trandolapril, Enalapril, Quinapril, '
        'Atacand/Candesartan, Diovan/valsartan, Olmetec/Olmesartan, Micardis/Telmisartan, Losartan). If ANY of those drugs '
        ' are indicated to be started/stopped/increased/decreased in the plan, "labs"["required"] MUST be true. HOWEVER, '
        'it is false if the change is only recommended, suggested, advised for someone '
        'else to do, conditional, or for the future (e.g. "I recommend starting ...", "consider '
        'increasing ...", "may benefit from ...", "if BP remains high, start ...", "defer to family '
        'doctor", "could be started at follow-up").\n\n'
        'If "labs"["required"] is true, then "labs"["period"] should represent when the lab work is requested '
        'to be completed. For example, if the note says "complete in 2 months", the value should be "2m". '
        'If "labs"["required"] is false, "labs"["period"] should simply be null.\n\n'
        '"requisition" should be a dictionary of all the consultations and diagnostics that are required at the next clinic '
        'visit. For example, if the plan states "I\'m gonna bring the patient back in 1 year for an echocardiogram", then '
        '"requisition" should look like: {"period": "1y", "echo": true}. If the plan gives no indication that a subsequent '
        'clinic visit is recommended, then simply have "period" be null.\n'
        'The period will usually be 1 year. If it is not, populate "period_reason" with a brief explanation for why a period '
        'other than 1 year was chosen, if this is detailed in the plan. If it is not, set "period_reason" to null. Note that '
        'this should refer to the actual REASON for the period change. Stating "the patient was advised to book in 6 months" '
        'is NOT a reason.\n'
        '"consult" refers to a cardiology consultation, and should be true if and only if one is desired.\n'
        '"ecg" refers to an electrocardiogram, and should be true if and only if one is desired.\n'
        '"echo" refers to an echo doppler, and should be true if and only if one is desired It should be false if only a '
        'stress echocardiogram is desired, since these two diagnostics are not the same.\n'
        '"contrastecho" can only be true if echo is true. It should be true when a contrast echocardiogram in specific '
        'is desired, and false if only a regular echocardiogram is desired.\n'
        '"stecho" refers to a stress echocardiogram, and should be true if and only if one is desired.\n'
        '"contrast" can only be true if stecho is true. It should be true when a contrast stress echocardiogram in specific '
        'is desired, and false if only a regular stress echocardiogram is desired.\n'
        '"est" refers to an exercise stress test, and should be true if and only if one is desired.\n'
        '"holter" refers to a holter monitor, and should refer to the desired monitoring period if and only if one is '
        'desired. The value for holter MUST be one of "24h", "48h", "72h", "2w" or null. It must NOT be a boolean value. '
        'Note that the plan may mention something like "3 days", for example, which must be appropriately translated '
        'into "72h".\n\n'
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
    med_raw = parsed.get("medication")
    med_ordered = [item for item in med_raw if is_ordered(item)] if isinstance(med_raw, list) else []

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

    # Requisition
    req_raw = parsed.get("requisition")
    if not isinstance(req_raw, dict):
        # Missing / null / non-object "requisition": treat as no requisition, so the medication and
        # lab results from the same reply are still used instead of failing the whole parse.
        req_raw = {}

    return {
        # Recommendations alone do not open the form.
        "open": len(med_ordered) > 0,
        "changes": clean_med_changes(med_raw),
        "labs": labs_required,
        "lab_period": lab_period,
        "lab_checkboxes": None,
        "requisition": req_raw.get("period") is not None,
        "requisition_period": req_raw.get("period"),
        "requisition_period_reason": req_raw.get("period_reason"),
        "requisition_diagnostics": [k for k, v in req_raw.items() if v and k != "period" and k != "period_reason"],
        "holter_period": req_raw.get("holter")
    }


def extract_med_changes(plan: str, send_fn) -> dict:
    """One LLM call via `send_fn(prompt) -> str`; see parse_med_response for the result.
    Raises on a failed call or unusable output so the caller can fall back to keywords."""
    prompt = build_med_prompt(plan)
    print(f"[med eForm] calling LLM ({len(plan)} chars of PLAN)")
    resp = send_fn(prompt)
    print(f"[med eForm] LLM replied: {str(resp)[:300]!r}")
    parsed_resp = parse_med_response(resp)
    # The lab-checkbox call only chooses which boxes to tick; whether the labs eForm opens is decided
    # by "labs.required" above. (It used to open the form whenever any box was picked, so a PLAN that
    # only reviewed previous bloodwork could still pop up the lab requisition.)
    if parsed_resp["labs"]:
        checkboxes = {
            s.strip() for s in analyze_plan_for_labs(plan, send_fn, False)
            if isinstance(s, str) and s.strip()
        }
        parsed_resp["lab_checkboxes"] = checkboxes or None
    else:
        print("[med eForm] labs not required; skipping the lab checkbox analysis")
    return parsed_resp


def analyze_plan_for_eforms(scope: str, send_fn, mode: str = "llm") -> dict:
    """Work out which eForms to open after a consult upload and what to pre-fill them with.
    `scope` is the PLAN section (or the whole consult if no PLAN heading was found).
    `mode` is "llm" or "keyword".

    Returns
    -------
    {"medication": {"open": bool, "changes": [{"action", "name", "text"}, ...]},
     "labs": bool, "lab_period": str | None, "lab_checkboxes": dict | None}
    "changes" may be empty while "open" is True (e.g. keyword fallback), in which case the
    medication form is opened without pre-filling."""
    scope = str(scope or "").strip()
    if not scope:
        return {
            "medication": {"open": False, "changes": []}, 
            "labs": False,
            "lab_period": None,
            "lab_checkboxes": None,
            "requisition": False,
            "requisition_period": None,
            "requisition_period_reason": None, 
            "requisition_diagnostics": [],
            "holter_period": None
        }

    if mode != "llm":
        print(f"[med eForm] mode={mode!r}: keyword check only, no LLM call, form will not be pre-filled")
        flags = keyword_flags(scope)
        return {
            "medication": {"open": flags["medication"], "changes": []}, 
            "labs": flags["labs"],
            "lab_period": None, 
            "lab_checkboxes": None,
            "requisition": flags["requisition"],
            "requisition_period": None,
            "requisition_period_reason": None, 
            "requisition_diagnostics": [],
            "holter_period": None
        }

    try:
        med = extract_med_changes(scope, send_fn)
    except Exception as e:
        print(f"eForm LLM gate failed, falling back to keyword: {e}")
        flags = keyword_flags(scope)
        # No period from keywords; the labs form then uses its default due date.
        med = {
            "open": flags["medication"], 
            "changes": [], 
            "labs": flags["labs"],
            "lab_period": None,
            "lab_checkboxes": None,
            "requisition": flags["requisition"],
            "requisition_period": None,
            "requisition_period_reason": None,
            "requisition_diagnostics": [],
            "holter_period": None
        }
    return {
        "medication": {"open": med["open"], "changes": med["changes"]},
        "labs": med["labs"],
        "lab_period": med.get("lab_period"),
        "lab_checkboxes": med.get("lab_checkboxes"),
        "requisition": med.get("requisition"),
        "requisition_period": med.get("requisition_period"),
        "requisition_period_reason": med.get("requisition_period_reason"),
        "requisition_diagnostics": med.get("requisition_diagnostics"),
        "holter_period": med.get("holter_period")
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
