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


# Drug names for the keyword fallback: generic names from the Rx form's standard lines plus common
# brand names and drug-class words.
_BRANDS_AND_CLASSES = (
    "lasix eliquis xarelto pradaxa lixiana lipitor crestor zocor pravachol altace coversyl mavik atacand "
    "diovan micardis avapro cozaar losartan enalapril quinapril olmetec olmesartan entresto aldactone "
    "inspra monocor coreg lopressor toprol norvasc adalat cardizem isoptin jardiance forxiga dapagliflozin "
    "empagliflozin canagliflozin invokana plavix brilinta brillinta effient aspirin asa coumadin lanoxin "
    "cordarone multaq lancora ivabradine nitroglycerin nitroglycerine nitro isosorbide statin statins "
    "anticoagulant anticoagulation diuretic diuretics hydrochlorothiazide hctz lovastatin"
).split()
_DRUG_WORDS = sorted({
    w for line in RX_MED_OPTIONS
    for w in [re.split(r"[\s/,]", line.strip())[0].lower()]
    if len(w) > 3 and w.isalpha()
} | set(_BRANDS_AND_CLASSES))
_DRUG_PATTERN = (r"\b(" + "|".join(map(re.escape, _DRUG_WORDS)) +
                 r"|medications?|meds|dose|dosage|dosing|\d+(\.\d+)?\s*mg|beta[- ]blockers?|"
                 r"ace[- ]?inhibitors?|arbs?)\b")


def keyword_flags(text: str) -> dict:
    """Keyword check: looks for medication-change verbs, and for a lab action plus a lab test
    name. Fast but cannot tell whether the verb refers to a medication (e.g. 'start a stress
    test' would match), so a change verb only counts in a sentence that also names a drug or says
    "medication"/"dose"/"mg". A medication verb only counts in a sentence that is not a recommendation,
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
    # A change verb only counts when the same sentence is about a medication (a drug name, or words like
    # "medication"/"dose"/"mg"), so "start a stress test" / "stop smoking" / "increase activity" do not.
    medication = any(re.search(med_pattern, s) and re.search(_DRUG_PATTERN, s)
                     and not re.search(_NOT_ORDERED_PATTERN, s) for s in sentences)
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
        '"est": true or false, "holter": "24h" | "48h" | "72h" | "2w" | null, '
        '"indications": {"ecg": str, "echo": str, "stecho": str, "est": str, "holter": str}} }\n\n'
        '"medication" lists every medication the plan STARTS, STOPS, or CHANGES THE DOSE of. '
        "Continuing an existing medication unchanged does NOT count. Renewing or refilling a current "
        "medication at the same dose does NOT count, nor does asking the patient whether they need renewals. "
        "Changes the patient made on their own, or changes from before this visit (history), do NOT count. "
        "Tests, imaging, procedures, "
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
        'Each test below should be true ONLY if the plan explicitly asks for it to be done (ordered, booked, arranged, '
        'or to be done at/before the next visit). Tests that were done today or before this visit, results that are '
        'reported or reviewed (e.g. "ECG today shows sinus rhythm", "Echo last year showed EF 55%"), tests already '
        'arranged by someone else or done elsewhere, and tests the plan says are not needed are all false.\n'
        '"consult" refers to a cardiology consultation, and should be true if and only if one is desired.\n'
        '"ecg" refers to an electrocardiogram, and should be true if and only if one is desired.\n'
        '"echo" refers to an echo doppler, and should be true if and only if one is desired It should be false if only a '
        'stress echocardiogram is desired, since these two diagnostics are not the same.\n'
        '"contrastecho" can only be true if echo is true. It should be true when a contrast echocardiogram in specific '
        'is desired, and false if only a regular echocardiogram is desired.\n'
        '"stecho" refers to a stress echocardiogram, and should be true if and only if the plan explicitly asks for a '
        '"stress echo" / "stress echocardiogram" as one test. "Stress test and echo", "treadmill test and echo" or '
        '"exercise stress test and echocardiogram" mean two separate tests: "est" true AND "echo" true, "stecho" false.\n'
        '"contrast" can only be true if stecho is true. It should be true when a contrast stress echocardiogram in specific '
        'is desired, and false if only a regular stress echocardiogram is desired.\n'
        '"est" refers to an exercise stress test, and should be true if and only if one is desired.\n'
        '"holter" refers to a holter monitor, and should refer to the desired monitoring period if and only if one is '
        'desired. The value for holter MUST be one of "24h", "48h", "72h", "2w" or null. It must NOT be a boolean value. '
        'Note that the plan may mention something like "3 days", for example, which must be appropriately translated '
        'into "72h".\n'
        '"indications" gives, for each test set to true above (ecg, echo, stecho, est, holter), a brief clinical '
        'reason for that test taken from the plan (e.g. "reassess LV function after MI", "palpitations"). Use only '
        'what the plan says; leave a test out of "indications" if the plan gives no reason for it. Do not invent one.\n\n'
        f"STANDARD LINES:\n{options}\n\n"
        f"PLAN:\n{plan}\n\n"
        "Return ONLY the JSON object, with no other text."
    )


_RENEWAL_PATTERN = r"\b(renew\w*|refill\w*|re-?prescrib\w*|continu\w*|same dose|unchanged|as before)\b"
_CHANGE_VERB_PATTERN = (r"\b(start\w*|initiat\w*|begin|began|add(ed|ing|s)?|increas\w*|decreas\w*|reduc\w*|"
                        r"uptitrat\w*|titrat\w*|switch\w*|chang\w*|stop\w*|discontinu\w*|hold|held)\b")


def is_renewal_only(item, plan: str | None) -> bool:
    """True when every PLAN sentence that mentions this entry's drug only renews / refills / continues it
    and none of them changes it, e.g. "I renewed his metoprolol 25 mg BID". Such an entry is a renewal the
    model mislabelled as a start or dose change, and must not open the medication form. Stops are left
    alone, and an entry whose drug is not found in the PLAN is kept (nothing to judge it by)."""
    if not plan or not isinstance(item, dict):
        return False
    if str(item.get("action", "")).strip().lower().startswith(("stop", "discontinu", "hold", "held")):
        return False
    names = {str(item.get("name") or "").strip().lower()}
    names.add(str(item.get("text") or "").strip().split(" ")[0].lower())
    names = {n for n in names if len(n) > 2}
    if not names:
        return False
    sentences = [x.lower() for x in re.split(r"(?<=[.;!?])\s+|\n+", plan) if x.strip()]
    mentioning = [x for x in sentences if any(n in x for n in names)]
    if not mentioning:
        return False
    return all(re.search(_RENEWAL_PATTERN, x) and not re.search(_CHANGE_VERB_PATTERN, x) for x in mentioning)


# Requisition eForm (fid 698) checkbox ids, in form order, and the ones with an indication box ("<id>-input").
REQUISITION_TESTS = ("consult", "ecg", "echo", "contrastecho", "stecho", "contrast", "est", "holter")
REQUISITION_INDICATION_TESTS = ("ecg", "echo", "stecho", "est", "holter")
_HOLTER_PERIODS = {"24h": "24h", "24hr": "24h", "1d": "24h", "48h": "48h", "48hr": "48h", "2d": "48h",
                   "72h": "72h", "72hr": "72h", "3d": "72h", "2w": "2w", "2wk": "2w", "14d": "2w"}
_STRESS_ECHO_PATTERN = r"\bstress[\s-]*echo"

# How each requisition test is written in a PLAN (contrast options go with their base test).
_REQUISITION_TEST_PATTERNS = {
    "consult": r"\b(consult\w*|follow[- ]?up|f/u|see\b.{0,20}\bback|return\w*|appointment|clinic visit)",
    "ecg": r"\b(ecg|ekg|electrocardiog\w*)\b",
    "echo": r"\b(echo\w*|tte)\b",
    "stecho": _STRESS_ECHO_PATTERN,
    "est": r"\b(stress test\w*|treadmill|exercise (stress |tolerance )?test\w*|est|gxt)\b",
    "holter": r"\b(holter|monitor\w*)\b",
}
# A sentence asking for a test to be done ...
_TEST_REQUEST_PATTERN = (r"\b(arrang\w*|book\w*|order\w*|schedul\w*|request\w*|repeat\w*|obtain\w*|refer\w*|"
                         r"requisition\w*|recommend\w*|need\w*|require\w*|will|plan\w*|get|undergo|"
                         r"due|next (visit|year|time|appointment)|in \d+\s*(day|week|month|year)s?|"
                         r"in (one|two|three|six|twelve) (day|week|month|year)s?|annual\w*|yearly)\b")
# ... versus one reporting a test already done / reviewed (results, history, done today).
_TEST_RESULT_PATTERN = (r"\b(show\w*|reveal\w*|demonstrat\w*|confirm\w*|was|were|is|are|normal|unremarkable|"
                        r"done|completed|performed|reviewed|previous\w*|prior|last|recent\w*|ago|today|earlier|"
                        r"already)\b")
# A sentence saying the test is not needed, or is already arranged (no new requisition needed).
_TEST_DECLINED_PATTERN = (r"\b(no need|not need\w*|not required|no further|unnecessary|declin\w*|not indicated|"
                          r"already (been )?(arranged|booked|scheduled|ordered|done|completed))\b")


# A clause that continues the previous one's test ("...; repeat in 1 year"), not some other plan item.
_TEST_CONTINUATION_PATTERN = (r"\s*(and |we |i )?(will |to )?(repeat|recheck|redo|reassess|re-assess|arrange|book|order|"
                              r"schedule|be repeated|in \d+\s*(day|week|month|year)s?)\b")


def _sentences(plan: str) -> list[str]:
    return [x.lower() for x in re.split(r"(?<=[.;!?])\s+|\n+", plan or "") if x.strip()]


def is_test_requested(test: str, plan: str | None) -> bool:
    """True when a PLAN sentence mentioning `test` asks for it to be done, e.g. "Repeat echo in 1 year",
    "Arrange 48 h Holter", or a bare order line such as "Holter 48h." A test only mentioned in sentences
    reporting results / history ("ECG today shows sinus rhythm", "Echo last year EF 55%") or saying it is
    not needed is not requested. True when there is no PLAN to judge by."""
    pattern = _REQUISITION_TEST_PATTERNS.get(test)
    if not plan or not pattern:
        return True
    sentences = _sentences(plan)
    for i, sentence in enumerate(sentences):
        if not re.search(pattern, sentence) or re.search(_TEST_DECLINED_PATTERN, sentence):
            continue
        if re.search(_TEST_REQUEST_PATTERN, sentence) or not re.search(_TEST_RESULT_PATTERN, sentence):
            return True
        # "Echo from 2024 showed EF 40%; repeat in 1 year." - the next clause names no test of its own
        following = sentences[i + 1] if i + 1 < len(sentences) else ""
        if (following and re.match(_TEST_CONTINUATION_PATTERN, following)
                and not re.search(_TEST_DECLINED_PATTERN, following)
                and not any(re.search(p, following) for p in _REQUISITION_TEST_PATTERNS.values())):
            return True
    return False


def normalize_holter_period(value) -> str | None:
    """The model's holter value as one of "24h" / "48h" / "72h" / "2w", or None when it is not one of them."""
    key = re.sub(r"[\s-]+", "", str(value or "").lower())
    key = re.sub(r"(hours?|hrs?)$", "h", key)
    key = re.sub(r"(days?)$", "d", key)
    key = re.sub(r"(weeks?|wks?)$", "w", key)
    return _HOLTER_PERIODS.get(key)


def requisition_from_response(req_raw, plan: str | None = None) -> dict:
    """The requisition part of the model's reply, checked against the form and the clinic's rules:
    - only the form's own checkbox ids are kept (case-insensitive), in form order;
    - a stress echo is only kept when the PLAN says "stress echo"; otherwise it is an exercise stress
      test, plus a regular echo if the PLAN mentions one ("stress test and echo" is EST + echo);
    - contrast echo needs echo, contrast stress echo needs stress echo;
    - a Holter always comes with an ECG;
    - the form is only opened when at least one box is ticked."""
    if not isinstance(req_raw, dict):
        req_raw = {}
    raw = {str(k).strip().lower(): v for k, v in req_raw.items()}

    holter_raw = raw.get("holter")
    holter_period = normalize_holter_period(holter_raw)
    ticked = {t for t in REQUISITION_TESTS if t != "holter" and as_flag(raw.get(t))}
    # Any holter value but false / null asks for one, even a period the form has no option for.
    if holter_period or as_flag(holter_raw) or (
            isinstance(holter_raw, str) and holter_raw.strip().lower() not in ("", "false", "no", "null", "none")):
        ticked.add("holter")

    if "stecho" in ticked and plan and not re.search(_STRESS_ECHO_PATTERN, plan, re.IGNORECASE):
        print('[requisition eForm] PLAN has no "stress echo"; ticking exercise stress test instead of stress echo')
        ticked -= {"stecho", "contrast"}
        ticked.add("est")
        if is_test_requested("echo", plan):
            ticked.add("echo")
    if plan:
        for test in sorted(ticked & set(_REQUISITION_TEST_PATTERNS), key=REQUISITION_TESTS.index):
            if not is_test_requested(test, plan):
                print(f'[requisition eForm] "{test}" not ticked: the PLAN only mentions it as a result / history, '
                      f'not as a test to be done')
                ticked.discard(test)
    if "echo" not in ticked:
        ticked.discard("contrastecho")
    if "stecho" not in ticked:
        ticked.discard("contrast")
    if "holter" in ticked:
        ticked.add("ecg")

    indications_raw = raw.get("indications")
    indications = {}
    if isinstance(indications_raw, dict):
        for k, v in indications_raw.items():
            k = str(k).strip().lower()
            if k in REQUISITION_INDICATION_TESTS and k in ticked and isinstance(v, str) and v.strip():
                indications[k] = v.strip()

    period = raw.get("period")
    period = str(period).strip() if period is not None and str(period).strip() else None
    diagnostics = [t for t in REQUISITION_TESTS if t in ticked]
    return {
        "requisition": bool(diagnostics),
        "requisition_period": period,
        "requisition_period_reason": raw.get("period_reason"),
        "requisition_diagnostics": diagnostics,
        "requisition_indications": indications,
        "holter_period": holter_period if "holter" in ticked else None,
    }


def parse_med_response(resp: str, plan: str | None = None) -> dict:
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
    if isinstance(med_raw, list) and plan:
        # Code-side guard: the prompt says renewals are not changes, but do not rely on the model alone.
        renewals = [item for item in med_raw if is_renewal_only(item, plan)]
        for item in renewals:
            print(f"[med eForm] skipped renewal (no change to the medication in the PLAN): {item!r}")
        med_raw = [item for item in med_raw if item not in renewals]
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

    # Requisition. A missing / null / non-object "requisition" means no requisition, so the medication
    # and lab results from the same reply are still used instead of failing the whole parse.
    requisition = requisition_from_response(parsed.get("requisition"), plan)

    return {
        # Recommendations alone do not open the form.
        "open": len(med_ordered) > 0,
        "changes": clean_med_changes(med_raw),
        "labs": labs_required,
        "lab_period": lab_period,
        "lab_checkboxes": None,
        **requisition,
    }


def extract_med_changes(plan: str, send_fn) -> dict:
    """One LLM call via `send_fn(prompt) -> str`; see parse_med_response for the result.
    Raises on a failed call or unusable output so the caller can fall back to keywords."""
    prompt = build_med_prompt(plan)
    print(f"[med eForm] calling LLM ({len(plan)} chars of PLAN)")
    resp = send_fn(prompt)
    print(f"[med eForm] LLM replied: {str(resp)[:300]!r}")
    parsed_resp = parse_med_response(resp, plan)
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
        "requisition_diagnostics": med.get("requisition_diagnostics") or [],
        "requisition_indications": med.get("requisition_indications") or {},
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
