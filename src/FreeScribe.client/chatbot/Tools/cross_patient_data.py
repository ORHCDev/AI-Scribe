from chatbot.Tools.Tool import tool, ToolReturn as tr
from chatbot.Tools.utils import period_parser

_MAX_RESULTS = 15

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
    mtype = _MEASUREMENT_TYPES.get(str(measurement).strip().lower(), str(measurement).strip().upper())
    op = _COMPARISONS.get(str(comparison).strip().lower(), "<")

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

    mapped_results = []
    for entry in res:
        name_query = f"""
        SELECT first_name, last_name
        FROM demographic
        WHERE demographicNo = {entry["demographicNo"]}
        """
        name_results = db_conn.query_database(name_query)
        if name_results:
            patient_name = f"{name_results[0]['first_name']} {name_results[0]['last_name']}".title()
        else:
            patient_name = "Unknown"
        mapped_results.append({
            "demographic_number": entry["demographicNo"],
            "patient_name": patient_name,
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


@tool(
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

    mapped_results = []
    for entry in res:
        name_query = f"""
        SELECT first_name, last_name
        FROM demographic
        WHERE demographic_no = {entry["demographicNo"]}
        """
        name_results = db_conn.query_database(name_query)
        if name_results:
            patient_name = f"{name_results[0]['first_name']} {name_results[0]['last_name']}".title()
        else:
            patient_name = "Unknown"
        mapped_results.append({
            "demographic_number": entry["demographicNo"],
            "patient_name": patient_name,
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

    demographic_numbers = [
        result["demographicNo"]
        for result in condition_results
    ]
    if not demographic_numbers:
        return tr(
            label=f"Patients with {condition} taking {medication} (0 found)",
            send_to_ai=True,
            query_results=[],
            save_results=[]
        )

    patient_filter = ", ".join(str(demo_no) for demo_no in demographic_numbers)

    med_query = f"""
    SELECT
        m.demographicNo,
        GROUP_CONCAT(
            m.dataField
            ORDER BY m.dateObserved
            SEPARATOR '\\n'
        ) AS medication_entries,
        DATE(MAX(m.dateObserved)) AS medication_date
    FROM measurements m
    WHERE m.type = 'MEDS'
    AND m.demographicNo IN ({patient_filter})
    AND LOWER(m.dataField) LIKE LOWER('%{medication}%')
    GROUP BY m.demographicNo;
    """

    medication_results = db_conn.query_database(med_query)

    medication_patients = {
        result["demographicNo"]: result
        for result in medication_results
    }

    mapped_results = []

    for result in condition_results:
        demo_no = result["demographicNo"]

        if demo_no not in medication_patients:
            continue

        name_query = f"""
        SELECT first_name, last_name
        FROM demographic
        WHERE demographic_no = {demo_no}
        """

        name_results = db_conn.query_database(name_query)

        if name_results:
            patient_name = (
                f"{name_results[0]['first_name']} "
                f"{name_results[0]['last_name']}"
            ).title()
        else:
            patient_name = "Unknown"

        mapped_results.append(patient_name)

    truncated = len(mapped_results) > _MAX_RESULTS
    mapped_results = mapped_results[:_MAX_RESULTS]

    if truncated:
        label = f"Top {_MAX_RESULTS} patients with {condition} taking {medication}"
    else:
        label = (
            f"Patients with {condition} taking {medication} "
            f"({len(mapped_results)} found)"
        )

    return tr(
        label=label,
        send_to_ai=True,
        query_results=mapped_results,
        save_results=mapped_results
    )