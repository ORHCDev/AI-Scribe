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
    WHERE demographic_no IN ({", ".join(demos)});
    """)
    return {
        str(r["demographic_no"]): f"{r['first_name']} {r['last_name']}".title()
        for r in rows
    }


@tool(
    category="cross_patient_data",
    description=(
        "Returns patients whose MOST RECENT value of a numeric measurement satisfies a comparison, "
        "up to 100 patients. Use for cohort questions like 'patients with EF less than 40', 'patients "
        "with LDL greater than 3.5', 'patients with an A1C between 6 and 8', 'EF equal to 55', "
        "'patients with systolic BP over 140'. Supports numeric measurements such as EF, BP, HR, "
        "weight, BMI, BSA, A1C, LDL, HDL, TG, cholesterol, EGFR, CRCL, HGB, HCT, INR, FBS, sodium, "
        "potassium. For BP the systolic value is used. Compares each patient's latest value across "
        "all patients; not for a single patient's history."
    ),
    context=(
        "Here are the patients (name, demographic number, value, date) whose latest measurement matches. "
        "Output all fields in a table format."
    ),
    parameters={
        "measurement": "The numeric measurement, e.g. 'EF', 'LDL', 'A1C'.",
        "comparison": "One of: less than, at most, greater than, at least, equal to, between (or symbols < <= > >= =).",
        "value": "The threshold value (or the lower bound when comparison is between).",
        "value2": "Optional. The upper bound, required only when comparison is between.",
    }
)
def patients_by_measurement(db_conn, measurement : str, comparison : str, value : float, value2 : float = None) -> list[dict]:
    """
    Returns patients whose most recent value of a numeric measurement satisfies the comparison.
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
    WHERE m.type = '{mtype}'
      AND m.dataField REGEXP {num_regexp}
      AND {cond}
    ORDER BY {num} ASC
    LIMIT {_MAX_RESULTS + 1};
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
            "value": entry["dataField"],
            "date_observed": entry["dateObserved"],
        })

    if truncated:
        label = f"Top {_MAX_RESULTS} patients with {desc} (showing the closest matches)"
    else:
        label = f"Patients with {desc} ({len(mapped_results)} found)"
    return tr(
        label=label,
        send_to_ai=True,
        query_results=mapped_results,
        save_results=mapped_results
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
    GROUP BY
        d.demographic_no,
        d.last_name,
        d.first_name,
        d.provider_no
    ORDER BY
        d.last_name,
        d.first_name
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
        "types": ("MEDS",),
        "prefix": "new entry: ",
        "label": "medication",
    },
}


@tool(
    category="cross_patient_data",
    description=(
        "Unified population-level lookup that returns active patients matching any combination of cardiac "
        "conditions and/or medications within a recent time period in a single call. Prefer this over calling "
        "condition_lookup and medication_lookup separately, especially when the question combines a condition "
        "with a medication (e.g. 'patients with heart failure on metoprolol'). Supply at least one of conditions "
        "or medications; when both are supplied, only patients matching every provided criterion are returned. "
        "Searches cardiac history measurement entries (type 'CARD'/'CARD1') and medication entries (type 'MEDS'), "
        "aggregates the matching entry text and observation dates for each patient, and returns patient identifiers "
        "(first and last name), provider number, the matching entries, and their dates grouped by patient. Only "
        "active patients are included, and only entries recorded on or after the calculated start date based on the "
        "provided period are considered. This tool is most relevant for cohort identification, combined "
        "condition/medication audits, quality improvement initiatives, and clinical reporting."
    ),
    context=(
        "Population-level lookup of patients matching one or more cardiac conditions and/or medications over a "
        "recent time window. Output all fields in a table format."
    ),
    parameters={
        "conditions": "Optional. List of cardiac condition names or partial names to search for in cardiac history entries.",
        "medications": "Optional. List of medication names or partial names to search for in medication entries.",
        "period": "Required. Time window to search within, expressed as a duration such as '6m', '30d', or '1y'.",
    }
)
def cross_patient_lookup(
    db_conn,
    period: str,
    conditions: list[str] | None = None,
    medications: list[str] | None = None
):
    """
    Queries and returns a report of patients matching the given conditions and/or medications.

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

    Returns
    -------
    ToolReturn
        Aggregated condition and/or medication entries grouped by patient.
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
        )
        if normalized
    }

    if not sources:
        return tr(
            label="Cross Patient Lookup",
            send_to_ai=True,
            query_results="No conditions or medications were provided to search for.",
            save_results="No conditions or medications were provided to search for."
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

    select_aggs = []
    match_filters = []
    having_filters = []

    for key, values in sources.items():
        spec = _CROSS_LOOKUP_SOURCES[key]
        types_sql = ", ".join(f"'{mtype}'" for mtype in spec["types"])
        like_filter = " AND ".join(
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

    query = f"""
    SELECT DISTINCT
        d.demographic_no,
        d.last_name,
        d.first_name,
        d.provider_no,
        {", ".join(select_aggs)}
    FROM measurements m
    JOIN demographic d
        ON m.demographicNo = d.demographic_no
    WHERE d.patient_status = 'AC'
    AND m.dateObserved > '{date}'
    AND (
        {" OR ".join(match_filters)}
    )
    GROUP BY
        d.demographic_no,
        d.last_name,
        d.first_name,
        d.provider_no
    HAVING {" AND ".join(having_filters)}
    ORDER BY
        d.last_name,
        d.first_name
    LIMIT {_MAX_RESULTS + 1};
    """

    res = db_conn.query_database(query)

    truncated = len(res) > _MAX_RESULTS
    res = res[:_MAX_RESULTS]

    desc = " and ".join(
        f"{_CROSS_LOOKUP_SOURCES[key]['label']}s {values}" for key, values in sources.items()
    )
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
