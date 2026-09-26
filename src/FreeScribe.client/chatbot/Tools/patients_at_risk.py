from chatbot.Tools.Tool import tool, ToolReturn as tr
from chatbot.Tools.utils import period_parser



"""@tool(
    category="patients_at_risk",
    description=(
        "Returns a list of patients who have an ejection fraction less than the specified amount, up to a maximum "
        "of 100 patients (most recent first). The user may specify a time period over which to narrow the search. "
        "If no time period is specified, default to the prior 6 months. This tool is relevant when the user asks "
        "about patients who have an ejection fraction, or EF, less than a specific amount."
    ),
    context=(
        "Here are the names, demographic numbers and EF values of the patients. Output all three fields in a table format."
    ),
    parameters={
        "EF_pct": "Ejection fraction percentage to filter for patient's with an EF less than it.",
        "period": "Optional. An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. I.e. '6m' would indicate 6 months."
    }
)"""
def ejection_fraction_less_than(db_conn, EF_pct : float, period : str = "6m") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patients that have an ejection fraction of less than EF_pct.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    EF_pct : float
        Ejection fraction percentage to filter for patient's with an EF less than it.

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.

    Returns
    -------
    A list of dictionaries of patients that have an ejection fraction of less than EF_pct.
    """

    date = period_parser(period)

    MAX_RESULTS = 100

    query = f"""
    SELECT *
    FROM measurements
    WHERE type = "EF_B"
    AND DATE(dateObserved) > '{date}'
    AND dataField < {float(EF_pct)}
    ORDER BY dateObserved DESC
    LIMIT {MAX_RESULTS + 1};
    """

    res = db_conn.query_database(query)

    truncated = len(res) > MAX_RESULTS
    res = res[:MAX_RESULTS]

    mapped_results = []
    for entry in res:
        name_query = f"""
        SELECT first_name, last_name
        FROM demographic
        WHERE demographic_no = {entry["demographicNo"]}
        """

        name_results = db_conn.query_database(name_query)

        if name_results:
            first_name = name_results[0]["first_name"]
            last_name = name_results[0]["last_name"]
            patient_name = f"{first_name} {last_name}".title()
        else:
            patient_name = "Unknown"

        mapped_results.append({
            "demographic_number": entry["demographicNo"],
            "patient_name": patient_name,
            "ef_value": entry["dataField"],
            "date_observed": entry["dateObserved"]
        })

    if truncated:
        label = f"First {MAX_RESULTS} patients with EF < {EF_pct}; more results exist"
    else:
        label = f"Patients with EF < {EF_pct}"

    return tr(
        label=label,
        send_to_ai=True,
        query_results=mapped_results,
        save_results=mapped_results
    )





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
    category="patients_at_risk",
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

    MAX_RESULTS = 15

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
    LIMIT {MAX_RESULTS + 1};
    """

    res = db_conn.query_database(query)
    truncated = len(res) > MAX_RESULTS
    res = res[:MAX_RESULTS]

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
            "value": entry["dataField"],
            "date_observed": entry["dateObserved"],
        })

    if truncated:
        label = f"Top {MAX_RESULTS} patients with {desc} (showing the closest matches)"
    else:
        label = f"Patients with {desc} ({len(mapped_results)} found)"
    return tr(
        label=label,
        send_to_ai=True,
        query_results=mapped_results,
        save_results=mapped_results
    )


def patients_with_rising_BNP_trend(db_conn) -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have a rising BNP trend.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    Returns
    -------
    A list of dictionaries of patient's that have a rising BNP trend.
    """


def patients_with_ventricular_arrhythmias(db_conn) -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have ventricular_arrhythmias.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.
    """  


def patients_with_recurrent_hospitalizations(db_conn, period : str) -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have recurrent hospitalizations in the last X days/months/years.

        Params
    ------
    db_conn : SOQ | OscarDB
        Database connection

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.

    Returns
    -------
    A list of dictionaries of patient's that have recurrent hospitalizations in the last X days/months/years.
    """


def patients_with_hypertension(db_conn) -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have hypertension.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.
    """  


def smokers(db_conn, period : str = "6m") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that are smokers.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.


    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """  

def diabetic(db_conn, period : str = "6m") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that are diabetic.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.


    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """  



def obese(db_conn, period : str = "6m") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that are obese.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.


    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """  

def sleep_apnea(db_conn, period : str = "6m") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have sleep apnea.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.


    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """  