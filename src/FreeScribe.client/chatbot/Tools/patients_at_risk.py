from chatbot.Tools.Tool import tool, ToolReturn as tr
from chatbot.Tools.utils import period_parser



@tool(
    category="patients_at_risk",
    description="Fetches and returns patient's who have an ejection fraction less than the given amount.",
    context="Here are the patient's who have an EF percent less than given:",
    parameters={
        "EF_pct": "Ejection fraction percentage to filter for patient's with an EF less than it.",
        "period": "An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. I.e. '6m' would indicate 6 months."
    }
)
def ejection_fraction_less_than(db_conn, EF_pct : float, period : str = "6mo") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have an ejection fraction of less than EF_pct.

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
    A list of dictionaries of patient's that have an ejection fraction of less than EF_pct.
    """

    date = period_parser(period)

    query = f"""
    SELECT *
    FROM measurements
    WHERE type = "EF_B"
      AND DATE(dateObserved) > '{date}'
      AND dataField < '{float(EF_pct)}
    ORDER BY dateObserved DESC;
    """

    res = db_conn.query_database(query)
    return tr(
        label=f"Patient's with EF < {EF_pct}",
        send_to_ai=True,
        query_results=res,
        save_results=res
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