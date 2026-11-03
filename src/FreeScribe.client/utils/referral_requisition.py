"""
New-patient referral letters -> requisition eForm (fid 716).
"""

import difflib
import json
import re

REFERRAL_REQUISITION_FID = 716

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
REFERRAL_MAX_PAGES = 3
_NOTE_HEADER = re.compile(r"\[\s*\d{1,2}-[A-Za-z]{3}-\d{4}\s*\.?:\s*([^\]]*)\]")


def indication_options(form_json: dict) -> dict:
    """Test id -> list of {"id": stored value, "label": text shown} from referral_form.json."""
    options = {}
    for test, key in _JSON_KEYS.items():
        block = (form_json or {}).get(key, {}).get("indications") or {}
        options[test] = [o for o in block.get("options", []) if o.get("id") and o.get("label")]
    return options


def latest_referral_query(demo_no) -> str:
    """The patient's most recent document with "referral" in its type or description."""
    return f"""
        SELECT cd.document_no, d.doctype, d.docdesc, d.observationdate
        FROM ctl_document AS cd
        JOIN document AS d ON cd.document_no = d.document_no
        WHERE cd.module = "demographic"
          AND cd.module_id = {int(demo_no)}
          AND (LOWER(d.doctype) LIKE '%referral%' OR LOWER(d.docdesc) LIKE '%referral%')
          AND (d.status IS NULL OR d.status <> 'D')
        ORDER BY d.observationdate DESC, cd.document_no DESC
        LIMIT 1;
    """


def patient_documents_query(demo_no, limit: int = 15) -> str:
    """The patient's most recent documents of any type, to show why none was taken as the referral."""
    return f"""
        SELECT cd.document_no, d.doctype, d.docdesc, d.observationdate, d.status
        FROM ctl_document AS cd
        JOIN document AS d ON cd.document_no = d.document_no
        WHERE cd.module = "demographic"
          AND cd.module_id = {int(demo_no)}
        ORDER BY d.observationdate DESC, cd.document_no DESC
        LIMIT {int(limit)};
    """


def describe_document(row: dict) -> str:
    """A document row as "Referral - Letter from Dr. X (2026-10-15)", to show which one was used."""
    name = " - ".join(str(row.get(k)).strip() for k in ("doctype", "docdesc") if str(row.get(k) or "").strip())
    return f"{name or 'Document'} ({row.get('observationdate') or 'no date'})"


def encounter_reason(note_texts: list) -> str:
    """The appointment reason in the current encounter note's header, "[29-Oct-2026 .: <reason>]"."""
    for text in reversed(note_texts or []):
        match = _NOTE_HEADER.search(str(text or ""))
        if match and match.group(1).strip():
            return " ".join(match.group(1).split())
    return ""


# Tests named in an appointment reason such as "STRESS ECHO - DR. X" or "ECHO-ECG". A stress echo is
# matched first and removed, so its "ECHO" is not also taken as an echo.
_REASON_STRESS_ECHO = r"\bstress[\s-]*echo\w*"
_REASON_TESTS = {
    "consult": r"\bconsult\w*",
    "ecg": r"\b(ecg|ekg|electrocardiog\w*)\b",
    "echo": r"\b(echo\w*|tte)\b",
    "est": r"\b(stress[\s-]*test\w*|treadmill|exercise[\s-]*(stress[\s-]*)?test\w*|est|ett|gxt)\b",
    "holter": r"\bholter\b",
}
_REASON_HOLTER_DURATIONS = {
    "24h": r"\b24\s*-?\s*(h|hr|hrs|hours?)\b", "48h": r"\b48\s*-?\s*(h|hr|hrs|hours?)\b",
    "72h": r"\b(72\s*-?\s*(h|hr|hrs|hours?)|3\s*-?\s*days?)\b",
    "2w": r"\b(2\s*-?\s*(w|wk|wks|weeks?)|14\s*-?\s*days?)\b",
}


def tests_from_reason(reason: str) -> dict:
    """{"tests": [...], "contrast": bool, "holter_duration": str | None} named in the appointment reason,
    in form order. Only these tests are ticked; the referral document only gives their indications."""
    text = (reason or "").lower()
    found = set()
    if re.search(_REASON_STRESS_ECHO, text):
        found.add("stecho")
        text = re.sub(_REASON_STRESS_ECHO, " ", text)
    found |= {test for test, pattern in _REASON_TESTS.items() if re.search(pattern, text)}
    duration = next((d for d, pattern in _REASON_HOLTER_DURATIONS.items() if re.search(pattern, text)), None)
    return {
        "tests": [t for t in REFERRAL_TESTS if t in found],
        "contrast": bool(re.search(r"\bcontrast\b", (reason or "").lower())),
        "holter_duration": duration if "holter" in found else None,
    }


def build_referral_prompt(referral_text: str, tests: list, form_json: dict) -> str:
    """Asks only for the indications of `tests` (already chosen from the appointment) from the document."""
    options = indication_options(form_json)
    lines = []
    for test in tests:
        name, input_id = REFERRAL_TESTS[test]
        lines.append(f'- "{test}": {name}')
        if input_id and options.get(test):
            lines.append("  indication options:")
            lines.extend(f"    * {o['label']}" for o in options[test])
    tests_block = "\n".join(lines)
    return f"""You are reading a new patient's cardiology referral DOCUMENT (often an OCR scan, in any format:
our requisition form, another clinic's form, or a free-text letter). The tests below are already booked;
give the indication for each of them from the document.

Rules:
- The reason can be anywhere: an "Indication" line, "Reason for referral", "Clinical information",
  "History", or the body of a letter. Read the whole document.
- For each test, "indication" is ONE of the listed options copied exactly when one clearly matches the
  document's reason; otherwise a short reason in the document's own words (e.g. "family history of
  sarcoid"). Use the reason given for that test; if none is given for it, use the document's overall
  reason (symptoms / history it describes). Use null if there is no reason at all.
- For "consult", "indication" is the reason for referral (short), or null.
- "holter_duration": one of "24h", "48h", "72h", "2w" if the document marks a Holter duration, else null.

Tests:
{tests_block}

Reply with JSON only, no other text:
{{"indications": {{"<test id>": "<option or short reason or null>"}},
  "holter_duration": null,
  "explanation": "<one sentence: the referral's reason>"}}

DOCUMENT (OCR text):
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


def parse_referral_response(raw: str, form_json: dict, booked: dict) -> dict:
    """LLM answer + `booked` (from tests_from_reason) -> {"fields": [...], "tests": [...],
    "indications": {test: (value, from_dropdown)}, "explanation": str}. Only the booked tests are ticked,
    whatever the LLM answers. Each field is {"type": "check"|"text", "id", "value"} in fill order:
    a test's checkbox (and contrast / Holter duration) before its indication."""
    data = _load_json_object(raw)
    given = data.get("indications") or {}
    if not isinstance(given, dict):
        given = {}
    given = {str(k).strip().lower(): v for k, v in given.items()}
    options = indication_options(form_json)

    fields, tests, indications = [], [], {}
    for test in booked.get("tests") or []:
        if test not in REFERRAL_TESTS:
            continue
        input_id = REFERRAL_TESTS[test][1]
        tests.append(test)
        fields.append({"type": "check", "id": test, "value": True})
        if booked.get("contrast") and test in CONTRAST_OPTIONS:
            fields.append({"type": "check", "id": CONTRAST_OPTIONS[test], "value": True})
        indication = given.get(test)
        if isinstance(indication, dict):
            indication = indication.get("indication")
        if isinstance(indication, str) and indication.strip().lower() not in ("", "null", "none"):
            if input_id:
                value, from_dropdown = match_indication(indication, options.get(test, []))
            else:
                value, from_dropdown = indication.strip(), False
            fields.append({"type": "text", "id": input_id or CONSULT_REASON_ID, "value": value})
            indications[test] = (value, from_dropdown)
        if test == "holter":
            # After the indication: the duration radio's onclick appends ". 24 hour study. " to it.
            # The appointment's duration wins over the document's.
            duration = HOLTER_DURATIONS.get(
                booked.get("holter_duration") or str(data.get("holter_duration") or "").strip().lower())
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
