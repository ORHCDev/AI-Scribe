from chatbot.Tools.Tool import tool, ToolReturn as tr
import matplotlib.pyplot as plt

def population_EF_trends(db_conn, age_range : tuple[int, int], sex : str, num_patients : int = 50) -> list[dict]:
    """
    Queries, plots, and returns the overall EF trend of patients.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    age_range : tuple[ing, int]
        Age range to group patient's by (age_low, age_high).

    sex : str
        Patient's sex (either 'M' or 'F')

    num_patients : int
        Number of patient's to include in the trend.
    """  


def population_BP_trends(db_conn, age_range : tuple[int, int], sex : str, num_patients : int = 50) -> list[dict]:
    """
    Queries, plots, and returns the overall BP trend of patients.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    age_range : tuple[ing, int]
        Age range to group patient's by (age_low, age_high).

    sex : str
        Patient's sex (either 'M' or 'F')

    num_patients : int
        Number of patient's to include in the trend.
    """  


def population_LDL_trends(db_conn, age_range : tuple[int, int], sex : str, num_patients : int = 50) -> list[dict]:
    """
    Queries, plots, and returns the overall LDL trend of patients.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    age_range : tuple[ing, int]
        Age range to group patient's by (age_low, age_high).

    sex : str
        Patient's sex (either 'M' or 'F')

    num_patients : int
        Number of patient's to include in the trend.
    """  


def population_weight_trends(db_conn, age_range : tuple[int, int], sex : str, num_patients : int = 50) -> list[dict]:
    """
    Queries, plots, and returns the overall weight trend of patients.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    age_range : tuple[ing, int]
        Age range to group patient's by (age_low, age_high).

    sex : str
        Patient's sex (either 'M' or 'F')

    num_patients : int
        Number of patient's to include in the trend.
    """  

def population_hospitalization_trends(db_conn, age_range : tuple[int, int], sex : str, num_patients : int = 50) -> list[dict]:
    """
    Queries, plots, and returns the overall hospitalization trend of patients.

    Params
    ------
    db_conn : SOQ | OscarDB
        Database connection.

    age_range : tuple[ing, int]
        Age range to group patient's by (age_low, age_high).

    sex : str
        Patient's sex (either 'M' or 'F')

    num_patients : int
        Number of patient's to include in the trend.
    """  

