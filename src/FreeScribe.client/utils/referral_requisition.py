"""
New-patient referral letters -> requisition eForm (fid 716).
"""

import ast
import difflib
import json
import re

from utils.med_eform import holter_periods_in_text, normalize_holter_period

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


def tests_from_reason(reason: str) -> dict:
    """{"tests": [...], "contrast": bool, "holter_duration": str | None} named in the appointment reason,
    in form order. Only these tests are ticked; the referral document only gives their indications."""
    text = (reason or "").lower()
    found = set()
    if re.search(_REASON_STRESS_ECHO, text):
        found.add("stecho")
        text = re.sub(_REASON_STRESS_ECHO, " ", text)
    found |= {test for test, pattern in _REASON_TESTS.items() if re.search(pattern, text)}
    durations = holter_periods_in_text(text)
    duration = durations[0] if len(durations) == 1 else None
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
our requisition form, another clinic's form, or a free-text letter).

DOCUMENT (OCR text):
{referral_text}

END OF DOCUMENT.

The tests below are already booked. For each of them, find in the DOCUMENT above why it is needed.

Tests:
{tests_block}

For each test, work in this order:
1. "evidence": copy, word for word, the sentence or phrase of the DOCUMENT (at most 20 words) that gives
   the reason: an "Indication" line, "Reason for referral", "Clinical information", "History", or the
   body of a letter. Use the reason given for that test; if none is given for it, the document's overall
   reason (the symptoms / history it describes). The evidence must be the DOCUMENT's words, never an
   option's words. If the document gives no reason, "evidence" is null.
2. "indication": the option above that says the same thing as your evidence, copied exactly. If no option
   says the same thing as the evidence, write the evidence's reason in a few of the document's own words
   instead; never pick an option about a symptom or condition the evidence does not mention. If
   "evidence" is null, "indication" is null.
- For "consult", "indication" is the reason for referral (short), or null.
- "holter_duration": one of "24h", "48h", "72h", "2w" if the document marks a Holter duration, else null.
  Days are not weeks: "2 days" is "48h"; only "2 weeks" / "14 days" is "2w".

Reply with valid JSON only, no other text. Do not put double quotes (") inside the text values:
{{"indications": {{"<test id>": {{"evidence": "<words copied from the DOCUMENT or null>",
                                  "indication": "<option or short reason or null>"}}}},
  "holter_duration": null,
  "explanation": "<one sentence: the referral's reason>"}}
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
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        # Some models answer with Python-style quotes / True / None, which is not JSON.
        try:
            data = ast.literal_eval(text[start:end + 1])
        except (ValueError, SyntaxError):
            raise ValueError(f"LLM response is not valid JSON ({e})") from e
    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")
    return data


def correction_prompt(prompt: str, unsupported: dict) -> str:
    """`prompt` again, telling the LLM which indications had no words from the document behind them."""
    rejected = "\n".join(f'- "{test}": "{indication}"' for test, indication in unsupported.items())
    return (f"{prompt}\n\nYour previous answer gave these indications, but the words you gave as evidence "
            f"are not in the DOCUMENT (an option's words are not evidence):\n{rejected}\nRead the DOCUMENT again "
            "for these tests only. First copy the DOCUMENT's own words that give the reason as \"evidence\", "
            "then choose the indication that says the same thing, or write the reason in the document's words "
            "when no option does. If the document gives no reason for a test, its evidence and indication are "
            "null. Reply with the same JSON format, for these tests only.")


def merge_correction(raw: str, corrected_raw: str, tests) -> str:
    """The first answer with the indications of `tests` taken from the corrected answer, as JSON."""
    data, corrected = _load_json_object(raw), _load_json_object(corrected_raw)
    indications = data.get("indications") if isinstance(data.get("indications"), dict) else {}
    fixes = corrected.get("indications") if isinstance(corrected.get("indications"), dict) else {}
    fixes = {str(k).strip().lower(): v for k, v in fixes.items()}
    indications = {str(k).strip().lower(): v for k, v in indications.items()}
    for test in tests:
        indications[test] = fixes.get(test)
    data["indications"] = indications
    return json.dumps(data)


def option_check_prompt(result: dict) -> str | None:
    """Asks whether each dropdown option chosen says the same thing as the document's words behind it,
    or None when no indication came from the dropdown."""
    chosen = {t: v for t, (v, from_dropdown) in result["indications"].items() if from_dropdown}
    if not chosen:
        return None
    lines = "\n".join(f'- "{t}": option: "{v}"\n  document words: "{result["evidence"].get(t, "")}"'
                      for t, v in chosen.items())
    return f"""Each test below has an indication option chosen for it from a cardiology referral, and the words of
the referral the option was chosen from.

{lines}

For each test, decide whether the option names the same condition, symptom or reason as the document words.
A different, broader or only related condition is not the same. If it is not the same, give "free_text": the
reason in a few of the document's own words (at most 10 words, no patient age or name); otherwise null.

Reply with valid JSON only, no other text. Do not put double quotes (") inside the text values:
{{"<test id>": {{"same": true or false, "free_text": "<reason in the document's words or null>"}}}}
"""


def apply_option_check(result: dict, raw: str) -> list:
    """Replaces each dropdown option the check says does not match its evidence with free text (the check's
    words, else the evidence) in `result`, field included. Returns the tests changed; the rejected options are
    kept in result["rejected_options"]."""
    data = {str(k).strip().lower(): v for k, v in _load_json_object(raw).items()}
    result.setdefault("rejected_options", {})
    changed = []
    for test, (value, from_dropdown) in list(result["indications"].items()):
        verdict = data.get(test)
        # Only an explicit "not the same" changes the indication; a missing or unclear answer keeps it
        if not from_dropdown or not isinstance(verdict, dict) \
                or str(verdict.get("same")).strip().lower() not in ("false", "no"):
            continue
        free_text = str(verdict.get("free_text") or "").strip()
        if free_text.lower() in ("", "null", "none"):
            free_text = " ".join(str(result["evidence"].get(test, "")).split()[:15])
        if not free_text:
            continue
        result["rejected_options"][test] = value
        result["indications"][test] = (free_text, False)
        field_id = REFERRAL_TESTS[test][1] or CONSULT_REASON_ID
        for field in result["fields"]:
            if field["type"] == "text" and field["id"] == field_id:
                field["value"] = free_text
        changed.append(test)
    return changed


RETRY_JSON_INSTRUCTION = ("\n\nYour previous reply was not valid JSON. Reply again with ONLY the JSON object, "
                          'and do not use double quotes (") inside any text value.')


_EVIDENCE_MATCH_RATIO = 0.8


def evidence_in_document(evidence, document_text: str) -> bool:
    """True when `evidence` is in the document, ignoring case / punctuation, with a little room
    for the LLM tidying the OCR ("foramene" -> "foramen"): some stretch of the document of about
    the same length is at least 80% the same."""
    parts = [p for p in re.split(r"\.{3,}|\u2026", str(evidence or "")) if _norm(p)]
    if len(parts) > 1:
        # "previous hx of TIA ... Patent foramene ovale": each part must be in the document
        return all(evidence_in_document(p, document_text) for p in parts)
    target, document = _norm(str(evidence or "")), _norm(document_text)
    if len(target) < 3:
        return False
    if target in document:
        return True
    matcher = difflib.SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(target)
    for start in [0] + [m.end() for m in re.finditer(r" ", document)]:
        matcher.set_seq1(document[start:start + len(target) + 5])
        if matcher.real_quick_ratio() >= _EVIDENCE_MATCH_RATIO and matcher.ratio() >= _EVIDENCE_MATCH_RATIO:
            return True
    return False


def parse_referral_response(raw: str, form_json: dict, booked: dict, document_text: str | None = None) -> dict:
    """LLM answer + `booked` (from tests_from_reason) -> {"fields": [...], "tests": [...],
    "indications": {test: (value, from_dropdown)}, "evidence": {test: quote}, "unsupported": {test: indication},
    "explanation": str}. Only the booked tests are ticked, whatever the LLM answers. Each field is
    {"type": "check"|"text", "id", "value"} in fill order: a test's checkbox (and contrast / Holter
    duration) before its indication. With `document_text`, an indication is only filled when its evidence
    is found in the document; otherwise it is left out and listed in "unsupported"."""
    data = _load_json_object(raw)
    given = data.get("indications") or {}
    if not isinstance(given, dict):
        given = {}
    given = {str(k).strip().lower(): v for k, v in given.items()}
    options = indication_options(form_json)

    fields, tests, indications, evidence, unsupported = [], [], {}, {}, {}
    for test in booked.get("tests") or []:
        if test not in REFERRAL_TESTS:
            continue
        input_id = REFERRAL_TESTS[test][1]
        tests.append(test)
        fields.append({"type": "check", "id": test, "value": True})
        if booked.get("contrast") and test in CONTRAST_OPTIONS:
            fields.append({"type": "check", "id": CONTRAST_OPTIONS[test], "value": True})
        indication, quote = given.get(test), (data.get("evidence") or {}).get(test) \
            if isinstance(data.get("evidence"), dict) else None
        if isinstance(indication, dict):
            indication, quote = indication.get("indication"), indication.get("evidence")
        if isinstance(indication, str) and indication.strip().lower() not in ("", "null", "none") \
                and document_text is not None and not evidence_in_document(quote, document_text):
            unsupported[test] = indication.strip()
        elif isinstance(indication, str) and indication.strip().lower() not in ("", "null", "none"):
            if document_text is not None:
                evidence[test] = " ".join(str(quote).split())
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
                booked.get("holter_duration") or normalize_holter_period(data.get("holter_duration")))
            if duration:
                fields.append({"type": "check", "id": duration, "value": True})

    return {
        "fields": fields,
        "tests": tests,
        "indications": indications,
        "evidence": evidence,
        "unsupported": unsupported,
        "explanation": str(data.get("explanation") or "").strip(),
    }


def reset_fields(booked: dict) -> list:
    """Fields that undo what the new form carries over from the patient's last requisition: tests (and
    contrast / Holter durations) the appointment does not name are unticked, and every indication box is
    emptied. Filled before parse_referral_response's fields; ids the form does not have are skipped."""
    tests = set(booked.get("tests") or [])
    unticks = [t for t in REFERRAL_TESTS if t not in tests]
    unticks += [c for t, c in CONTRAST_OPTIONS.items() if not (t in tests and booked.get("contrast"))]
    unticks += list(HOLTER_DURATIONS.values())
    boxes = [input_id for _, input_id in REFERRAL_TESTS.values() if input_id] + [CONSULT_REASON_ID]
    return ([{"type": "check", "id": i, "value": False, "reset": True} for i in unticks]
            + [{"type": "text", "id": i, "value": "", "reset": True} for i in boxes])


# Ticks (click, so the form's onclick runs) and fills fields by id in the open eForm window.
# Errors thrown by the form's own onclick handlers do not stop the rest.
FILL_FIELDS_JS = """
    var result = {done: [], missing: []};
    arguments[0].forEach(function (f) {
        var el = document.getElementById(f.id);
        if (!el) { if (!f.reset) { result.missing.push(f.id); } return; }
        if (f.type === "check" && f.value === false) {
            if (el.checked) { try { el.click(); } catch (e) {} }
            el.checked = false;
        } else if (f.type === "check") {
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
