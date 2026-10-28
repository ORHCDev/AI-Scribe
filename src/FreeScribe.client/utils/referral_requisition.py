"""
New-patient referral letters -> requisition eForm (fid 716).

When AI-Scribe starts, "REFERRAL LETTER" documents uploaded to patients the day before (who have
no requisition eForm yet) are OCR'd, the LLM reads which tests the referring doctor asked
for and the "Indication for the test" lines, and the requisition eForm is opened filled in for the
doctor to check and submit. Each indication is set to the form's matching dropdown option when one
fits, otherwise to the referral's own wording (e.g. "family history of sarcoid").

This module holds the parts that do not need Oscar or the UI: the SQL, the prompt, and turning the
LLM's answer into the fields to fill.
"""

import difflib
import json
import re
from datetime import date, timedelta

REFERRAL_REQUISITION_FID = 716
REFERRAL_DOCTYPE = "REFERRAL LETTER"
# Requisition eForms that count as "already written" for the patient (716 and the older 698).
REQUISITION_FIDS = (716, 698)

# Test checkbox id -> (name shown to the LLM, indication input id or None)
REFERRAL_TESTS = {
    "consult": ("Cardiology consultation", None),
    "ecg": ("Electrocardiogram (ECG)", "ecg-input"),
    "echo": ("Echo Doppler (echocardiogram)", "echo-input"),
    "stecho": ("Stress echocardiogram", "stecho-input"),
    "est": ("Exercise stress test (treadmill)", "est-input"),
    "holter": ("Holter monitor", "holter-input"),
}
# Free-text reason box of the consultation section.
CONSULT_REASON_ID = "referral-reason"
HOLTER_DURATIONS = {"24h": "24hr", "48h": "48hr", "72h": "72hr", "2w": "2wk"}
# Sub-options that tick their own checkbox next to the parent test.
CONTRAST_OPTIONS = {"echo": "contrastecho", "stecho": "contrast"}

# referral_form.json keys (procedure names) for each test id
_JSON_KEYS = {
    "consult": "cardiology consultation",
    "ecg": "electrocardiogram",
    "echo": "echo doppler",
    "stecho": "stress echocardiogram",
    "est": "exercise stress test",
    "holter": "holter monitor",
}
_OPTION_MATCH_RATIO = 0.9


# How many days back a missed check is caught up (e.g. AI-Scribe not opened over a long weekend).
MAX_CATCH_UP_DAYS = 7


def days_to_check(last_checked: date | None, today: date) -> tuple[date, date] | None:
    """Upload days to check when AI-Scribe starts, as (first day, last day), or None.

    Every day after `last_checked` up to yesterday (at most MAX_CATCH_UP_DAYS back; only yesterday
    the very first time). Today is left for tomorrow, when all of its uploads are in."""
    yesterday = today - timedelta(days=1)
    first = yesterday if last_checked is None else last_checked + timedelta(days=1)
    first = max(first, today - timedelta(days=MAX_CATCH_UP_DAYS))
    return (first, yesterday) if first <= yesterday else None


def patient_provider_query(demo_no) -> str:
    """The patient's MRP provider number (for opening the encounter page)."""
    return f"SELECT provider_no FROM demographic WHERE demographic_no = {int(demo_no)} LIMIT 1;"


def new_referral_documents_query(since: str, until: str | None = None) -> str:
    """Referral letters attached to a patient and uploaded at or after `since` and before `until`
    (both 'YYYY-MM-DD HH:MM:SS')."""
    for stamp in (since, until):
        if stamp is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", stamp):
            raise ValueError(f"Bad timestamp: {stamp!r}")
    until_clause = f"AND d.updatedatetime < '{until}'" if until else ""
    return f"""
        SELECT cd.document_no, cd.module_id AS demographic_no, d.updatedatetime
        FROM ctl_document AS cd
        JOIN document AS d ON cd.document_no = d.document_no
        WHERE cd.module = "demographic"
          AND cd.module_id > 0
          AND UPPER(TRIM(d.doctype)) = '{REFERRAL_DOCTYPE}'
          AND (d.status IS NULL OR d.status <> 'D')
          AND d.updatedatetime >= '{since}'
          {until_clause}
        ORDER BY d.updatedatetime ASC, cd.document_no ASC;
    """


def requisition_exists_query(demo_no) -> str:
    """Any submitted requisition eForm (716 or 698) for the patient."""
    fids = ", ".join(str(f) for f in REQUISITION_FIDS)
    return f"""
        SELECT fdid FROM eform_data
        WHERE demographic_no = {int(demo_no)} AND fid IN ({fids}) AND status = 1
        LIMIT 1;
    """


def indication_options(form_json: dict) -> dict:
    """Test id -> list of {"id": stored value, "label": text shown} from referral_form.json."""
    options = {}
    for test, key in _JSON_KEYS.items():
        block = (form_json or {}).get(key, {}).get("indications") or {}
        options[test] = [o for o in block.get("options", []) if o.get("id") and o.get("label")]
    return options


def build_referral_prompt(referral_text: str, form_json: dict) -> str:
    options = indication_options(form_json)
    lines = []
    for test, (name, input_id) in REFERRAL_TESTS.items():
        lines.append(f'- "{test}": {name}')
        if input_id and options.get(test):
            lines.append("  indication options:")
            lines.extend(f"    * {o['label']}" for o in options[test])
    tests_block = "\n".join(lines)
    return f"""You are reading an OCR scan of a cardiology referral letter / requisition sent by a referring doctor.
Find which tests the referring doctor is asking our clinic to do, and the indication for each.

Rules:
- Only include a test if the referral asks for it: its box is marked (OCR may show a filled box as
  "■", "@", "®", "M", "Hl", "%" and an empty box as "□", "O", "0", "[]", "("), or the referral
  writes an indication / request for it. Do not include tests that are only mentioned as past results.
- "stecho" only when the referral asks for a stress ECHO; a plain stress / treadmill test is "est".
- For each test, "indication" is ONE of the listed options copied exactly when one clearly matches
  the referral's reason; otherwise a short reason in the referral's own words (e.g. "family history
  of sarcoid"). Use the reason written for that test; if the test has none, use the referral's
  overall reason. Use null if the referral gives no reason at all.
- "holter_duration": one of "24h", "48h", "72h", "2w" if a Holter duration is marked, else null.
- "contrast": true only if the referral marks the contrast option for echo / stress echo.
- For "consult", "indication" is the reason for referral (short), or null.

Tests:
{tests_block}

Reply with JSON only, no other text:
{{"tests": {{"<test id>": {{"indication": "<option or short reason or null>", "contrast": false}}}},
  "holter_duration": null,
  "explanation": "<one sentence: what the referral asks for>"}}

Referral (OCR text):
{referral_text}
"""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def match_indication(indication: str, options: list) -> tuple[str, bool]:
    """(value to write, True if it is one of the dropdown options). Matches the option label or
    stored value, ignoring case/punctuation; a near-identical label (OCR/LLM typos) also counts."""
    target = _norm(indication)
    if not target:
        return "", False
    for o in options:
        if target in (_norm(o["label"]), _norm(o["id"])):
            return o["id"], True
    best, best_ratio = None, 0.0
    for o in options:
        ratio = difflib.SequenceMatcher(None, target, _norm(o["label"])).ratio()
        if ratio > best_ratio:
            best, best_ratio = o, ratio
    if best and best_ratio >= _OPTION_MATCH_RATIO:
        return best["id"], True
    return indication.strip(), False


def _load_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object in the LLM response")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")
    return data


def parse_referral_response(raw: str, form_json: dict) -> dict:
    """LLM answer -> {"fields": [...], "tests": [...], "indications": {test: (value, from_dropdown)},
    "explanation": str}. Each field is {"type": "check"|"text", "id", "value"} in fill order:
    a test's checkbox (and contrast / Holter duration) before its indication."""
    data = _load_json_object(raw)
    requested = data.get("tests") or {}
    if isinstance(requested, list):
        requested = {t: {} for t in requested}
    requested = {str(k).strip().lower(): (v if isinstance(v, dict) else {}) for k, v in requested.items()}
    options = indication_options(form_json)

    fields, tests, indications = [], [], {}
    for test, (_name, input_id) in REFERRAL_TESTS.items():
        if test not in requested:
            continue
        info = requested[test]
        tests.append(test)
        fields.append({"type": "check", "id": test, "value": True})
        if info.get("contrast") is True and test in CONTRAST_OPTIONS:
            fields.append({"type": "check", "id": CONTRAST_OPTIONS[test], "value": True})
        indication = info.get("indication")
        if isinstance(indication, str) and indication.strip().lower() not in ("", "null", "none"):
            if input_id:
                value, from_dropdown = match_indication(indication, options.get(test, []))
            else:
                value, from_dropdown = indication.strip(), False
            fields.append({"type": "text", "id": input_id or CONSULT_REASON_ID, "value": value})
            indications[test] = (value, from_dropdown)
        if test == "holter":
            # After the indication: the duration radio's onclick appends ". 24 hour study. " to it.
            duration = HOLTER_DURATIONS.get(str(data.get("holter_duration") or "").strip().lower())
            if duration:
                fields.append({"type": "check", "id": duration, "value": True})

    return {
        "fields": fields,
        "tests": tests,
        "indications": indications,
        "explanation": str(data.get("explanation") or "").strip(),
    }


# Ticks (click, so the form's onclick runs) and fills fields by id in the open eForm window.
# Errors thrown by the form's own onclick handlers do not stop the rest.
FILL_FIELDS_JS = """
    var result = {done: [], missing: []};
    arguments[0].forEach(function (f) {
        var el = document.getElementById(f.id);
        if (!el) { result.missing.push(f.id); return; }
        if (f.type === "check") {
            if (!el.checked) { try { el.click(); } catch (e) {} }
            if (!el.checked) { el.checked = true; }
        } else {
            el.value = f.value == null ? "" : String(f.value);
            el.dispatchEvent(new Event("change", {bubbles: true}));
        }
        result.done.push(f.id);
    });
    return result;
"""
