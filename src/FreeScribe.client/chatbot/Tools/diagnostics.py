from chatbot.Tools.Tool import tool, ToolReturn as tr
from chatbot.Tools.utils import period_parser, export_data




def patients_with_lab_abnormalities(db_conn, test_names : list[str], period : str = "6m") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have abnormalities in the given tests.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    test_names : list[str]
        List of test names to search for abnormalities. I.e. ['Kpl', 'A1C', ...]

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """   

def stress_and_ischemic_testing(db_conn, test_names : list[str], period : str = "6m") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have had stress and ischemic testing done.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    test_names : list[str]
        List of test names to search for abnormalities. I.e. ['est', 'stress echo', ...]

    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """   


def imaging_done(db_conn, period : str = "6m") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have had imaging (echo) done.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.


    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """  



def patient_interventions(db_conn, period : str = "6m") -> list[dict]:
    """
    Queries and returns a list of dictionaries of patient's that have had interventions (PCI, CABG, TAVR/SAVR, etc).

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.


    period : str
        An integer followed by one of 'd', 'm', or 'y' for days, months, or years respectively. \\
        I.e. '6m' would indicate 6 months.
    """  



