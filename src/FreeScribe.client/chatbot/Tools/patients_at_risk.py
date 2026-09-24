from chatbot.Tools.Tool import tool, ToolReturn as tr
from chatbot.Tools.utils import period_parser



@tool(
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
)
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