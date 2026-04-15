from chatbot.Tools.Tool import tool, ToolReturn as tr
from chatbot.Tools.utils import period_parser



def new_referrals(db_conn, period : str) -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that are new referrals in the last X days/months/years.

        Params
    ------
    db_conn : SOQ | OscarDB
        Database connection

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.

    Returns
    -------
    A list of dictionaries of patient's that are new referrals in the last X days/months/years.
    """


def patients_dischared_from_hospital(db_conn, period : str) -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that were dischared from the hospital in the last X days/months/years.

        Params
    ------
    db_conn : SOQ | OscarDB
        Database connection

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.

    Returns
    -------
    A list of dictionaries of patient's that were dischared from the hospital in the last X days/months/years.
    """



def unacknowledged_abnormal_results(db_conn, period : str = "6m") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that outstanding abnormal results that have not been acknowledged.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.


    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """  


