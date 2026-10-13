import re
from datetime import datetime, timedelta

from chatbot.Tools.Tool import tool, ToolReturn as tr
from chatbot.Tools.utils import period_parser

_MAX_RESULTS = 100

_MEASUREMENT_TYPES = {
    "ef": "EF_B", "ejection fraction": "EF_B", "ef_b": "EF_B", "lvef": "EF_B",
    "bp": "BP", "blood pressure": "BP", "sbp": "BP", "systolic": "BP", "systolic bp": "BP",
    "hr": "HR", "heart rate": "HR", "pulse": "HR",
    "weight": "WT", "wt": "WT", "bmi": "BMI", "bsa": "BSA",
    "a1c": "A1C", "hba1c": "A1C",
    "ldl": "LDL", "hdl": "HDL", "tg": "TG", "triglycerides": "TG",
    "cholesterol": "TCHL", "tchl": "TCHL", "total cholesterol": "TCHL",
    "egfr": "EGFR", "crcl": "CRCL", "creatinine clearance": "CRCL",
    "hgb": "HGB", "hemoglobin": "HGB", "hct": "HCT", "hematocrit": "HCT",
    "inr": "INR", "fbs": "FBS", "glucose": "FBS",
    "sodium": "NAPL", "na": "NAPL", "potassium": "KPL", "k": "KPL",
}

_COMPARISONS = {
    "less than": "<", "<": "<", "lt": "<", "below": "<", "under": "<",
    "at most": "<=", "<=": "<=", "le": "<=", "no more than": "<=",
    "greater than": ">", ">": ">", "gt": ">", "above": ">", "over": ">",
    "at least": ">=", ">=": ">=", "ge": ">=", "no less than": ">=",
    "equal to": "=", "equals": "=", "=": "=", "eq": "=", "==": "=",
    "between": "between", "within": "between", "in range": "between",
}


def _names_for(db_conn, demo_numbers) -> dict:
    """Return {demographic_no: 'First Last'} for the given numbers in one query."""
    demos = [str(d) for d in demo_numbers if str(d).strip()]
    if not demos:
        return {}
    rows = db_conn.query_database(f"""
    SELECT demographic_no, first_name, last_name
    FROM demographic
    WHERE demographic_no IN ({", ".join(demos)})
        AND first_name NOT IN ('Test', 'Tester')
        AND last_name NOT IN ('Test', 'Tester')
        AND first_name NOT REGEXP '^Test[0-9]+$'
        AND last_name NOT REGEXP '^Test[0-9]+$';
    """)
    return {
        str(r["demographic_no"]): f"{r['first_name']} {r['last_name']}".title()
        for r in rows
    }


@tool(
    category="cross_patient_data",
    description=(
        "Returns active patients whose MOST RECENT value of a numeric measurement satisfies a comparison, "
        "up to 100 patients. Use for cohort questions like 'patients with EF less than 40', 'patients "
        "with LDL greater than 3.5', 'patients with an A1C between 6 and 8', 'EF equal to 55', "
        "'patients with systolic BP over 140', or with a time window such as 'patients with EF between "
        "25 and 30 over the last month'. Supports numeric measurements such as EF, BP, HR, "
        "weight, BMI, BSA, A1C, LDL, HDL, TG, cholesterol, EGFR, CRCL, HGB, HCT, INR, FBS, sodium, "
        "potassium. For BP the systolic value is used. Compares each patient's latest value across "
        "all patients; when a period is given, only patients whose latest value was recorded within "
        "that period are included. Not for a single patient's history."
    ),
    context=(
        "Here are the patients (name, demographic number, value, date) whose latest measurement matches. "
        "Output all fields in a table format, including each patient's value and date observed."
    ),
    parameters={
        "measurement": "The numeric measurement, e.g. 'EF', 'LDL', 'A1C'.",
        "comparison": "One of: less than, at most, greater than, at least, equal to, between (or symbols < <= > >= =).",
        "value": "The threshold value (or the lower bound when comparison is between).",
        "value2": "Optional. The upper bound, required only when comparison is between.",
        "period": "Optional. Only include patients whose latest value was recorded within this time window, "
                  "expressed as a duration such as '30d', '1m', '6m', or '1y'. Omit when no time window is asked for.",
    }
)
def patients_by_measurement(db_conn, measurement : str, comparison : str, value : float, value2 : float = None,
                            period : str = None) -> list[dict]:
    """
    Returns active patients whose most recent value of a numeric measurement satisfies the comparison,
    optionally limited to patients whose latest value was recorded within the given period.
    """
    # Validate inputs so a typo or bad argument is reported clearly instead of
    # silently running a query that returns nothing (a false "no patients found").
    key = str(measurement).strip().lower()
    valid_codes = set(_MEASUREMENT_TYPES.values())
    if key in _MEASUREMENT_TYPES:
        mtype = _MEASUREMENT_TYPES[key]
    elif str(measurement).strip().upper() in valid_codes:
        mtype = str(measurement).strip().upper()
    else:
        msg = (
            f"Unrecognized measurement '{measurement}'. Supported measurements: "
            f"{', '.join(sorted(valid_codes))}."
        )
        return tr(label="Unrecognized measurement", send_to_ai=True,
                  query_results=msg, save_results=msg)

    comp_key = str(comparison).strip().lower()
    if comp_key not in _COMPARISONS:
        msg = (
            f"Unrecognized comparison '{comparison}'. Use one of: less than, at most, "
            f"greater than, at least, equal to, between (or < <= > >= =)."
        )
        return tr(label="Unrecognized comparison", send_to_ai=True,
                  query_results=msg, save_results=msg)
    op = _COMPARISONS[comp_key]

    try:
        float(value)
        if value2 is not None:
            float(value2)
    except (ValueError, TypeError):
        msg = f"The threshold value(s) must be numeric; got value={value!r}, value2={value2!r}."
        return tr(label="Invalid value", send_to_ai=True,
                  query_results=msg, save_results=msg)

    if mtype == "BP":
        num = "CAST(SUBSTRING_INDEX(m.dataField, '/', 1) AS DECIMAL(10,2))"
        num_regexp = "'^[0-9]+/[0-9]+'"
    else:
        num = "CAST(m.dataField AS DECIMAL(10,2))"
        num_regexp = "'^[0-9]+([.][0-9]+)?$'"

    if op == "between" and value2 is not None:
        lo, hi = float(value), float(value2)
        if lo > hi:
            lo, hi = hi, lo
        cond = f"{num} BETWEEN {lo} AND {hi}"
        desc = f"{mtype} between {lo} and {hi}"
    else:
        if op == "between":
            op = ">="
        cond = f"{num} {op} {float(value)}"
        desc = f"{mtype} {op} {float(value)}"

    # m.dateObserved is each patient's latest date, so this keeps only patients whose
    # latest value falls inside the window (not any value inside the window).
    date_filter = ""
    if period:
        start_date = period_parser(str(period).strip())
        if not start_date:
            msg = f"Could not parse period '{period}'. Use a duration such as '30d', '6m', or '1y'."
            return tr(label="Invalid period", send_to_ai=True,
                      query_results=msg, save_results=msg)
        date_filter = f"AND m.dateObserved >= '{start_date}'"
        desc += f" recorded since {start_date}"

    query = f"""
    SELECT m.demographicNo, m.dataField, DATE(m.dateObserved) AS dateObserved
    FROM measurements m
    JOIN (
        SELECT demographicNo, MAX(dateObserved) AS maxDate
        FROM measurements
        WHERE type = '{mtype}'
        GROUP BY demographicNo
    ) latest
      ON m.demographicNo = latest.demographicNo AND m.dateObserved = latest.maxDate
    JOIN demographic d
      ON m.demographicNo = d.demographic_no
    WHERE m.type = '{mtype}'
      AND d.patient_status = 'AC'
      {date_filter}
      AND m.dataField REGEXP {num_regexp}
      AND {cond}
    LIMIT {_MAX_RESULTS + 1};
    """

    res = db_conn.query_database(query)

    names = _names_for(db_conn, [entry["demographicNo"] for entry in res])
    mapped_results = []
    for entry in res:
        patient_name = names.get(str(entry["demographicNo"]), False)
        if patient_name: mapped_results.append({
            "demographic_number": entry["demographicNo"],
            "patient_name": patient_name,
            "value": entry["dataField"],
            "date_observed": entry["dateObserved"],
        })
    mapped_results.sort(key=lambda x: x["patient_name"].lower())
    
    truncated = len(mapped_results) > _MAX_RESULTS
    truncated_results = mapped_results[:_MAX_RESULTS]

    if truncated:
        label = f"Top {_MAX_RESULTS} patients with {desc} (listed alphabetically)"
    else:
        label = f"Patients with {desc} ({len(truncated_results)} found)"
    return tr(
        label=label,
        send_to_ai=True,
        query_results=truncated_results,
        save_results=truncated_results
    )


'''@tool(
    category="cross_patient_data",
    description=(
        "Returns all patients who are experiencing one or two specific cardiac conditions."
    ),
    context=(
        "Here is the list of patients "
    ),
    parameters={
        "condition1": "the first cardiac condition to check for",
        "condition2": "(Optional) the second cardiac condition to check for"
    }
)
def condition_condition_lookup(db_conn, condition1 : str, condition2: str = None) -> list[dict]:
    regex_condition = f"""
        CONCAT(
            COALESCE(MAX(CASE WHEN type = 'CARD' THEN dataField END), ''),
            COALESCE(MAX(CASE WHEN type = 'CARD1' THEN dataField END), '')
        ) REGEXP '{condition1}'
    """

    if condition2 is not None:
        regex_condition += f"""
            AND CONCAT(
                COALESCE(MAX(CASE WHEN type = 'CARD' THEN dataField END), ''),
                COALESCE(MAX(CASE WHEN type = 'CARD1' THEN dataField END), '')
            ) REGEXP '{condition2}'
        """

    query = f"""
    SELECT
        m.demographicNo,
        MAX(CASE WHEN m.type = 'CARD' THEN m.dataField END) AS CARD,
        MAX(CASE WHEN m.type = 'CARD1' THEN m.dataField END) AS CARD1,
        DATE(m.dateObserved) AS latest_date
    FROM measurements m
    JOIN (
        SELECT
            demographicNo,
            MAX(DATE(dateObserved)) AS latest_date
        FROM measurements
        WHERE type IN ('CARD', 'CARD1')
        GROUP BY demographicNo
    ) latest
        ON latest.demographicNo = m.demographicNo
        AND latest.latest_date = DATE(m.dateObserved)
    WHERE m.type IN ('CARD', 'CARD1')
    GROUP BY
        m.demographicNo,
        DATE(m.dateObserved)
    HAVING {regex_condition};
    """

    res = db_conn.query_database(query)
    truncated = len(res) > _MAX_RESULTS
    res = res[:_MAX_RESULTS]

    names = _names_for(db_conn, [entry["demographicNo"] for entry in res])
    mapped_results = []
    for entry in res:
        mapped_results.append({
            "demographic_number": entry["demographicNo"],
            "patient_name": names.get(str(entry["demographicNo"]), "Unknown"),
            "value": (
                (entry["CARD"] or "") +
                (entry["CARD1"] or "")
            ),
            "date_observed": entry["latest_date"],
        })
        
    desc = condition1
    if condition2: desc += f"and {condition2}"
    if truncated:
        label = f"Top {_MAX_RESULTS} patients with {desc}"
    else:
        label = f"Patients with {desc} ({len(mapped_results)} found)"
    return tr(
        label=label,
        send_to_ai=True,
        query_results=mapped_results,
        save_results=mapped_results
    )


@tool(
    category="cross_patient_data",
    description=(
        "Returns all patients who have a specific cardiac condition and are currently "
        "taking a specific medication."
    ),
    context=(
        "Here is the list of patients with the specified cardiac condition who are currently taking the specified medication."
    ),
    parameters={
        "condition": "the cardiac condition to check for",
        "medication": "the medication to check for"
    }
)
def condition_medication_lookup(db_conn, condition: str, medication: str) -> list[dict]:
    query = f"""
    SELECT
        m.demographicNo,
        MAX(CASE WHEN m.type = 'CARD' THEN m.dataField END) AS CARD,
        MAX(CASE WHEN m.type = 'CARD1' THEN m.dataField END) AS CARD1,
        DATE(m.dateObserved) AS latest_date
    FROM measurements m
    JOIN (
        SELECT
            demographicNo,
            MAX(DATE(dateObserved)) AS latest_date
        FROM measurements
        WHERE type IN ('CARD', 'CARD1')
        GROUP BY demographicNo
    ) latest
        ON latest.demographicNo = m.demographicNo
        AND latest.latest_date = DATE(m.dateObserved)
    WHERE m.type IN ('CARD', 'CARD1')
    GROUP BY
        m.demographicNo,
        DATE(m.dateObserved)
    HAVING CONCAT(
        COALESCE(MAX(CASE WHEN type = 'CARD' THEN dataField END), ''),
        COALESCE(MAX(CASE WHEN type = 'CARD1' THEN dataField END), '')
    ) REGEXP '{condition}';
    """

    condition_results = db_conn.query_database(query)

    condition_map = {result["demographicNo"]: result for result in condition_results}
    if not condition_map:
        return tr(
            label=f"Patients with {condition} taking {medication} (0 found)",
            send_to_ai=True,
            query_results=[],
            save_results=[]
        )

    patient_filter = ", ".join(str(demo_no) for demo_no in condition_map)

    # Of the condition matches, keep only those on the medication (one query, set only).
    med_query = f"""
    SELECT DISTINCT m.demographicNo
    FROM measurements m
    WHERE m.type = 'MEDS'
    AND m.demographicNo IN ({patient_filter})
    AND LOWER(m.dataField) LIKE LOWER('%{medication}%');
    """
    med_results = db_conn.query_database(med_query)
    matched = [r["demographicNo"] for r in med_results if r["demographicNo"] in condition_map]

    truncated = len(matched) > _MAX_RESULTS
    matched = matched[:_MAX_RESULTS]
    if not matched:
        return tr(
            label=f"Patients with {condition} taking {medication} (0 found)",
            send_to_ai=True,
            query_results=[],
            save_results=[]
        )

    # Single batched name lookup instead of one query per patient.
    name_filter = ", ".join(str(demo_no) for demo_no in matched)
    name_rows = db_conn.query_database(f"""
    SELECT demographic_no, first_name, last_name
    FROM demographic
    WHERE demographic_no IN ({name_filter});
    """)
    names = {
        r["demographic_no"]: f"{r['first_name']} {r['last_name']}".title()
        for r in name_rows
    }

    mapped_results = []
    for demo_no in matched:
        cond = condition_map.get(demo_no, {})
        mapped_results.append({
            "demographic_number": demo_no,
            "patient_name": names.get(demo_no, "Unknown"),
            "condition": (cond.get("CARD") or "") + (cond.get("CARD1") or ""),
            "date_observed": cond.get("latest_date"),
        })

    if truncated:
        label = f"Top {_MAX_RESULTS} patients with {condition} taking {medication}"
    else:
        label = f"Patients with {condition} taking {medication} ({len(mapped_results)} found)"

    return tr(
        label=label,
        send_to_ai=True,
        query_results=mapped_results,
        save_results=mapped_results
    )'''


@tool(
    category="cross_patient_data",
    description=(
        "Returns a report of active patients who have cardiac history entries matching one or more specified "
        "conditions within a defined recent time period. The tool searches cardiac history measurement entries "
        "(type = 'CARD' or 'CARD1') and aggregates the matching history text entries and observation dates for each "
        "patient. Results include patient identifiers (first and last name), provider number, history entry text, and "
        "corresponding observation dates, grouped by patient. Only active patients are included, and only entries "
        "recorded on or after the calculated start date based on the provided period are considered. "
        "This tool is most relevant for population-level condition audits, cohort identification, quality improvement "
        "initiatives, clinical reporting, or identifying patients with specific cardiac conditions such as "
        "'atrial fibrillation', 'heart failure', 'myocardial infarction', or 'valve replacement'."
    ),
    context="Population-level lookup of patients with specific cardiac history conditions over a recent time window",
    parameters={
        "conditions": "List of cardiac condition names or partial names to search for in cardiac history measurement entries",
        "period": "Required. Time window to search within, expressed as a duration such as '6m', '30d', or '1y'",
    }
)
def condition_lookup(db_conn, conditions : list[str], period : str):
    """
    Queries and returns a report of patients that have the given cardiac conditions.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    conditions : list[str]
        List of cardiac conditions to use to find patients that have them.

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """

    if isinstance(conditions, str):
        conditions = [conditions]

    if not conditions:
        return tr(
            label="Condition Lookup",
            send_to_ai=True,
            query_results="No conditions were provided to search for.",
            save_results="No conditions were provided to search for."
        )

    date = period_parser(period)

    list_of_conditions = [str(cond).replace("'", "''") for cond in conditions]
    condition_filter = " AND ".join(
        f"LOWER(m.dataField) LIKE LOWER('%{cond}%')" for cond in list_of_conditions
    )

    MAX_RESULTS = 100

    query = f"""
    SELECT DISTINCT
        d.demographic_no,
        d.last_name,
        d.first_name,
        GROUP_CONCAT(CONCAT('new history: ', m.dataField) ORDER BY m.dateObserved SEPARATOR '\n') AS condition_entries,
        GROUP_CONCAT(CONCAT('new history: ', m.dateObserved) ORDER BY m.dateObserved SEPARATOR '\n') AS date_entries,
        d.provider_no
    FROM measurements m
    JOIN demographic d
        ON m.demographicNo = d.demographic_no
    WHERE m.type IN ('CARD', 'CARD1')
    AND d.patient_status = 'AC'
    AND m.dateObserved > '{date}'
    AND (
        {condition_filter}
        )
    AND d.first_name NOT IN ('Test', 'Tester')
    AND d.last_name NOT IN ('Test', 'Tester')
    AND d.first_name NOT REGEXP '^Test[0-9]+$'
    AND d.last_name NOT REGEXP '^Test[0-9]+$';
    GROUP BY
        d.demographic_no,
        d.last_name,
        d.first_name,
        d.provider_no
    ORDER BY
        d.first_name,
        d.last_name
    LIMIT {MAX_RESULTS + 1};
    """

    res = db_conn.query_database(query)

    truncated = len(res) > MAX_RESULTS
    res = res[:MAX_RESULTS]

    if truncated:
        label = f"First {MAX_RESULTS} patients with {conditions} within {period}; more results exist"
    else:
        label = f"Patients with {conditions} within {period} ({len(res)} found)"

    return tr(
        label=label,
        send_to_ai=True,
        query_results=res,
        save_results=res
    )


_CROSS_LOOKUP_SOURCES = {
    "conditions": {
        "types": ("CARD", "CARD1"),
        "prefix": "new history: ",
        "label": "condition",
    },
    "medications": {
        "types": ("MEDS", "MEDS1"),
        "prefix": "new entry: ",
        "label": "medication",
    },
    "medical_history": {
        "types": ("PMH","PMH1"),
        "prefix": "new entry: ",
        "label": "medical history entry",
    },
}


def _resolve_appointment_range(value: str) -> tuple[str, str] | None:
    """
    Resolve a user-supplied appointment date or range to an inclusive
    ('YYYY-MM-DD', 'YYYY-MM-DD') tuple.

    Accepts a single explicit date, relative terms ('today', 'tomorrow',
    'yesterday', 'this week', 'next week', 'this month', 'next month'), or an
    explicit range such as '2025-06-01 to 2025-06-07' (also 'through', 'until',
    or '/' as the separator).

    Params
    ------
    value : str
        The appointment date or range expression.

    Returns
    -------
    tuple[str, str] | None
        The resolved inclusive start and end dates, or None when unparseable.
    """
    text = str(value).strip()
    lowered = text.lower()

    def fmt(day) -> str:
        return day.strftime("%Y-%m-%d")

    today = datetime.now().date()
    if lowered in ("today", "now"):
        return fmt(today), fmt(today)
    if lowered == "yesterday":
        day = today - timedelta(days=1)
        return fmt(day), fmt(day)
    if lowered == "tomorrow":
        day = today + timedelta(days=1)
        return fmt(day), fmt(day)

    if lowered in ("this week", "current week"):
        start = today - timedelta(days=today.weekday())
        return fmt(start), fmt(start + timedelta(days=6))
    if lowered == "next week":
        start = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return fmt(start), fmt(start + timedelta(days=6))
    if lowered in ("this month", "current month"):
        start = today.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return fmt(start), fmt(end)
    if lowered == "next month":
        start = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return fmt(start), fmt(end)

    parts = re.split(r"\s+to\s+|\s+through\s+|\s+until\s+|\s*/\s*", text, maxsplit=1)
    try:
        if len(parts) == 2:
            start = datetime.strptime(parts[0].strip(), "%Y-%m-%d").date()
            end = datetime.strptime(parts[1].strip(), "%Y-%m-%d").date()
            if start > end:
                start, end = end, start
            return fmt(start), fmt(end)
        day = datetime.strptime(text, "%Y-%m-%d").date()
        return fmt(day), fmt(day)
    except ValueError:
        return None


@tool(
    category="cross_patient_data",
    description=(
        "Unified population-level lookup that returns active patients matching any combination of cardiac "
        "conditions, medications, and/or medical history within a recent time period in a single call. When "
        "appointment_date is provided, results are further limited to patients who have an appointment on that "
        "date or within that range and each patient's appointment details are included. Prefer this over calling condition_lookup and "
        "medication_lookup separately, especially when the question combines a condition with a medication "
        "(e.g. 'patients with heart failure on metoprolol') or involves past medical history (e.g. 'patients with "
        "a history of asthma'). Also prefer this single tool over combining a cross-patient lookup with an "
        "appointment tool when the question asks which patients matching a condition, medication, or history were "
        "also seen on a given date (e.g. 'which patients did I see today with heart disease', 'patients with "
        "atrial fibrillation booked today', or 'patients with heart failure seen by Dr. Smith today'). Supply at "
        "least one of conditions, medications, or medical_history; when more than one is supplied, only patients "
        "matching every provided criterion are returned. Searches cardiac history measurement entries (type "
        "'CARD'/'CARD1'), medication entries (type 'MEDS'), and patient medical history entries (type 'PMH'), "
        "aggregates the matching entry text and observation dates for each patient, and returns patient identifiers "
        "(first and last name), provider number, the matching entries, their dates, and any matching appointments "
        "grouped by patient. Only active patients are included, and only entries recorded on or after the calculated "
        "start date based on the provided period are considered. This tool is most relevant for cohort "
        "identification, combined condition/medication/history audits, appointment day-sheet filtering, quality "
        "improvement initiatives, and clinical reporting. For each named condition, medication, or history term, include "
        "every plausible alternate form the EMR might store (abbreviations, synonyms, generic and brand names) in the "
        "corresponding list so entries recorded under an alternate name are not missed; the final answer must state which "
        "alternate terms were assumed."
    ),
    context=(
        "Population-level lookup of patients matching one or more cardiac conditions, medications, and/or medical "
        "history entries over a recent time window, optionally limited to patients with an appointment on a given "
        "date or within a given range. When appointments are included, present each patient with their appointment date, time, and reason. "
        "If alternate condition/medication/history names, abbreviations, or synonyms were searched, state in the answer which alternate terms were assumed. "
        "Output all fields in a table format."
    ),
    parameters={
        "conditions": "Optional. List of cardiac condition names or partial names to search for in cardiac history entries. Expand each condition into every plausible abbreviation and synonym (e.g. 'atrial fibrillation' also 'AF' and 'AFib'; 'myocardial infarction' also 'MI'). Include the original term.",
        "medications": "Optional. List of medication names or partial names to search for in medication entries. Expand each drug into every plausible generic/brand name, abbreviation, and synonym (e.g. 'vincristine' also 'VCR'; 'metoprolol' also 'Lopressor'). Include the original term.",
        "medical_history": "Optional. List of medical history terms or partial names to search for in patient medical history entries (type 'PMH'). Expand each term into every plausible abbreviation and synonym, including the original term.",
        "period": "Required. Time window to search within, expressed as a duration such as '6m', '30d', or '1y'.",
        "appointment_date": "Optional. When set, only patients with an appointment on this date or within this range are returned, along with their appointment details. Accepts 'YYYY-MM-DD', 'today', 'tomorrow', 'yesterday', 'this week', 'next week', 'this month', 'next month', or an explicit range such as '2025-06-01 to 2025-06-07'.",
        "provider_name": "Optional. Filters appointments to a provider, given with or without 'Dr.'. If provided without appointment_date, defaults to today's appointments.",
    }
)
def cross_patient_lookup(
    db_conn,
    period: str,
    conditions: list[str] | None = None,
    medications: list[str] | None = None,
    medical_history: list[str] | None = None,
    appointment_date: str | None = None,
    provider_name: str | None = None
):
    """
    Queries and returns a report of patients matching the given conditions, medications, and/or medical history.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.

    conditions : list[str] | None
        Optional list of cardiac conditions to find patients that have them.

    medications : list[str] | None
        Optional list of medications to find patients that are on them.

    medical_history : list[str] | None
        Optional list of medical history terms to find patients that have them.

    appointment_date : str | None
        Optional appointment date or range as 'YYYY-MM-DD', 'today', 'tomorrow',
        'yesterday', 'this week', 'next week', 'this month', 'next month', or an
        explicit range such as '2025-06-01 to 2025-06-07'. When set, only patients
        with an appointment on that date or within that range are returned and
        their appointment details are included.

    provider_name : str | None
        Optional provider name (with or without 'Dr.') used to filter appointments.
        If provided without appointment_date, today's appointments are used.

    Returns
    -------
    ToolReturn
        Aggregated condition, medication, and/or medical history entries grouped by
        patient, including any matching appointment details.
    """

    def _normalize(values: list[str] | str | None) -> list[str]:
        if not values:
            return []
        if isinstance(values, str):
            values = [values]
        return [str(value).replace("'", "''") for value in values if str(value).strip()]

    sources = {
        key: normalized
        for key, normalized in (
            ("conditions", _normalize(conditions)),
            ("medications", _normalize(medications)),
            ("medical_history", _normalize(medical_history)),
        )
        if normalized
    }

    if not sources:
        return tr(
            label="Cross Patient Lookup",
            send_to_ai=True,
            query_results="No conditions, medications, or medical history were provided to search for.",
            save_results="No conditions, medications, or medical history were provided to search for."
        )

    date = period_parser(period)
    if not date:
        msg = f"Could not parse period '{period}'. Use a duration such as '6m', '30d', or '1y'."
        return tr(
            label="Invalid period",
            send_to_ai=True,
            query_results=msg,
            save_results=msg
        )

    appointment_date = appointment_date.strip() if isinstance(appointment_date, str) else appointment_date
    provider_name = provider_name.strip() if isinstance(provider_name, str) else provider_name

    appointment_join = ""
    appointment_select = ""
    appointment_having = ""
    appointment_start = None
    appointment_end = None

    if appointment_date or provider_name:
        if appointment_date:
            resolved_range = _resolve_appointment_range(appointment_date)
            if not resolved_range:
                msg = (
                    f"Could not parse appointment date '{appointment_date}'. "
                    "Use 'YYYY-MM-DD', 'today', 'tomorrow', 'yesterday', 'this week', "
                    "'next week', 'this month', 'next month', or a range such as "
                    "'2025-06-01 to 2025-06-07'."
                )
                return tr(
                    label="Invalid appointment date",
                    send_to_ai=True,
                    query_results=msg,
                    save_results=msg
                )
            appointment_start, appointment_end = resolved_range
        else:
            appointment_start = appointment_end = datetime.now().strftime("%Y-%m-%d")

        appt_provider_filter = ""
        if provider_name:
            safe_provider = provider_name.replace("'", "''")
            providers = db_conn.query_database(f"""
            SELECT provider_no
            FROM provider
            WHERE CONCAT(first_name, ' ', last_name) = '{safe_provider}'
               OR CONCAT('Dr. ', first_name, ' ', last_name) = '{safe_provider}'
            """)

            if not providers:
                return tr(
                    label=f"Provider not found: {provider_name}",
                    send_to_ai=True,
                    query_results=[],
                    save_results=[]
                )

            provider_ids = [str(provider["provider_no"]) for provider in providers]
            appt_provider_filter = f"AND a.provider_no IN ({','.join(provider_ids)})"

        appointment_join = f"""
    LEFT JOIN (
        SELECT
            a.demographic_no,
            GROUP_CONCAT(
                CONCAT(
                    a.appointment_date, ' ', a.start_time,
                    CASE WHEN a.reason IS NOT NULL AND a.reason <> ''
                         THEN CONCAT(' - ', a.reason) ELSE '' END
                )
                ORDER BY a.start_time SEPARATOR '\\n'
            ) AS appointments
        FROM appointment a
        WHERE a.appointment_date BETWEEN '{appointment_start}' AND '{appointment_end}'
          AND a.demographic_no <> 0
          {appt_provider_filter}
        GROUP BY a.demographic_no
    ) appt ON appt.demographic_no = d.demographic_no"""
        appointment_select = "MAX(appt.appointments) AS appointments"
        appointment_having = "appointments IS NOT NULL"

    select_aggs = []
    match_filters = []
    having_filters = []

    for key, values in sources.items():
        spec = _CROSS_LOOKUP_SOURCES[key]
        types_sql = ", ".join(f"'{mtype}'" for mtype in spec["types"])
        like_filter = " OR ".join(
            f"LOWER(m.dataField) LIKE LOWER('%{value}%')" for value in values
        )
        match = f"(m.type IN ({types_sql}) AND ({like_filter}))"
        match_filters.append(match)
        select_aggs.append(
            f"GROUP_CONCAT(CASE WHEN {match} "
            f"THEN CONCAT('{spec['prefix']}', m.dataField) END "
            f"ORDER BY m.dateObserved SEPARATOR '\n') AS {key}_entries"
        )
        select_aggs.append(
            f"GROUP_CONCAT(CASE WHEN {match} "
            f"THEN CONCAT('{spec['prefix']}', m.dateObserved) END "
            f"ORDER BY m.dateObserved SEPARATOR '\n') AS {key}_dates"
        )
        having_filters.append(f"{key}_entries IS NOT NULL")

    if appointment_having:
        having_filters.append(appointment_having)

    select_parts = [
        "d.demographic_no",
        "d.last_name",
        "d.first_name",
        "d.provider_no",
    ]
    if appointment_select:
        select_parts.append(appointment_select)
    select_parts.extend(select_aggs)

    query = f"""
    SELECT DISTINCT
        {", ".join(select_parts)}
    FROM measurements m
    JOIN demographic d
        ON m.demographicNo = d.demographic_no
    {appointment_join}
    WHERE d.patient_status = 'AC'
    AND m.dateObserved > '{date}'
    AND (
        {" OR ".join(match_filters)}
    )
    AND d.first_name NOT IN ('Test', 'Tester')
    AND d.last_name NOT IN ('Test', 'Tester')
    AND d.first_name NOT REGEXP '^Test[0-9]+$'
    AND d.last_name NOT REGEXP '^Test[0-9]+$';
    GROUP BY
        d.demographic_no,
        d.last_name,
        d.first_name,
        d.provider_no
    HAVING {" AND ".join(having_filters)}
    ORDER BY
        d.first_name,
        d.last_name
    LIMIT {_MAX_RESULTS + 1};
    """

    res = db_conn.query_database(query)

    truncated = len(res) > _MAX_RESULTS
    res = res[:_MAX_RESULTS]

    desc = " and ".join(
        f"{_CROSS_LOOKUP_SOURCES[key]['label']}s {values}" for key, values in sources.items()
    )
    if appointment_select:
        if appointment_start == appointment_end:
            desc += f" with an appointment on {appointment_start}"
        else:
            desc += f" with an appointment between {appointment_start} and {appointment_end}"
        if provider_name:
            desc += f" with {provider_name}"

    if truncated:
        label = f"First {_MAX_RESULTS} patients with {desc} within {period}; more results exist"
    else:
        label = f"Patients with {desc} within {period} ({len(res)} found)"

    return tr(
        label=label,
        send_to_ai=True,
        query_results=res,
        save_results=res
    )
